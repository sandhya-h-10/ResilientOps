"""Only this service mutates simulated inventory. It is never exposed to an LLM."""

import json
import uuid

from resilientops.models import Dataset, Decision, DomainError, Plan, Principal, utcnow
from resilientops.services.grounding import validate_claims
from resilientops.services.policy import authorize, current_plan_errors, validate_plan
from resilientops.storage import Store, dumps, fingerprint


class ActionService:
    def __init__(self, store: Store):
        self.store = store

    def _plan(self, incident: dict, digest: str) -> Plan:
        if not incident.get("plan") or digest != incident.get("plan_hash"):
            raise DomainError("Plan version/hash does not match the current decision")
        if fingerprint(incident["plan"]) != digest:
            raise DomainError("Stored plan integrity check failed")
        plan = Plan.model_validate(incident["plan"])
        if fingerprint(incident["snapshot"]) != plan.snapshot_hash:
            raise DomainError("Planning snapshot integrity check failed")
        for ref in plan.evidence_ids:
            if ref not in incident["evidence"]:
                raise DomainError("Plan references missing evidence")
        validate_claims(incident["results"]["Commander"]["claims"], incident["evidence"])
        return plan

    def decide(
        self,
        incident_id: str,
        decision: Decision,
        actor: Principal,
        *,
        simulation_review: bool = False,
    ) -> dict:
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            if incident["status"] not in {"AWAITING_APPROVAL", "READY_FOR_EXECUTION"}:
                raise DomainError("Incident is not awaiting approval")
            plan = self._plan(incident, decision.plan_hash)
            if simulation_review:
                if incident.get("workflow_kind") != "diagram" or decision.decision != "APPROVE":
                    raise DomainError(
                        "Direct simulation review only approves selected workflow plans", 403
                    )
            else:
                authorize(actor, plan)
            if incident.get("workflow_kind") == "diagram":
                if not incident.get("selected_plan_id") or not incident.get("approval_report"):
                    raise DomainError("Planner selection and approval report are required")
                if decision.decision != "APPROVE" and not decision.comment.strip():
                    raise DomainError("Explain the rejection or requested changes", 422)
            if decision.decision == "APPROVE":
                dataset = Dataset.model_validate(incident["snapshot"])
                errors = current_plan_errors(self.store, db, dataset, plan) + validate_plan(
                    dataset, plan
                )
                if errors:
                    raise DomainError("; ".join(errors))
            incident["approval"] = {
                "actor": actor.id,
                "role": "simulation-reviewer" if simulation_review else actor.role,
                "authorization_mode": "planner-simulation-signoff"
                if simulation_review
                else "approver-credential",
                "decision": decision.decision,
                "plan_hash": decision.plan_hash,
                "policy_version": plan.approval_policy,
                "at": utcnow().isoformat(),
                "comment": decision.comment,
            }
            incident["status"] = "APPROVED" if decision.decision == "APPROVE" else "REJECTED"
            if incident.get("workflow_kind") == "diagram":
                incident.setdefault("decision_history", []).append(incident["approval"].copy())
                if decision.decision != "APPROVE":
                    incident["status"] = "CHANGES_REQUESTED"
            self.store.save(db, incident)
            self.store.trace(db, incident_id, "Human", "decision", incident["approval"])
            return incident

    def execute(
        self, incident_id: str, digest: str, actor: Principal, *, simulation_release: bool = False
    ) -> dict:
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            plan = self._plan(incident, digest)
            if simulation_release:
                if incident.get("workflow_kind") != "diagram" or not incident.get(
                    "selected_plan_id"
                ):
                    raise DomainError("Select a workflow plan before release")
            else:
                authorize(actor, plan)
            # Replays return the committed result even if operational state later changes.
            existing = db.execute(
                "SELECT payload FROM actions WHERE plan_hash=? AND incident_id=?",
                (digest, incident_id),
            ).fetchone()
            if existing:
                return json.loads(existing[0])
            if simulation_release:
                if incident["status"] not in {
                    "READY_FOR_EXECUTION",
                    "AWAITING_APPROVAL",
                    "APPROVED",
                }:
                    raise DomainError("Selected plan is not ready for release")
                if incident["selected_plan_id"] != plan.id:
                    raise DomainError("Selected plan does not match release request")
            else:
                if incident["status"] != "APPROVED":
                    raise DomainError("Execution requires an approved incident")
                approval = incident.get("approval") or {}
                if approval.get("decision") != "APPROVE" or approval.get("plan_hash") != digest:
                    raise DomainError("Approval is missing or bound to another plan")
                if approval.get("policy_version") != plan.approval_policy:
                    raise DomainError("Approval policy version is stale")
            dataset = Dataset.model_validate(incident["snapshot"])
            stale = current_plan_errors(self.store, db, dataset, plan)
            if stale:
                raise DomainError("Current state invalidates this plan: " + "; ".join(stale))
            dataset = dataset.model_copy(update={"inventories": self.store.inventories(db)})
            # Capacity is shared across incidents; committed actions consume their option capacity.
            committed = [json.loads(r[0]) for r in db.execute("SELECT payload FROM actions")]
            used: dict[str, int] = {}
            group_used: dict[str, int] = {}
            for action in committed:
                for item in action["allocations"]:
                    quantity = (
                        item.get("received_units", 0)
                        if action["status"] == "CANCELLED"
                        else item["quantity"]
                    )
                    used[item["option_id"]] = used.get(item["option_id"], 0) + quantity
                    group = item["option"].get("capacity_group")
                    if group:
                        group_used[group] = group_used.get(group, 0) + quantity
            dataset = dataset.model_copy(
                update={
                    "options": [
                        option.model_copy(
                            update={
                                "capacity": max(
                                    0,
                                    option.capacity
                                    - (
                                        group_used.get(option.capacity_group, 0)
                                        if option.capacity_group
                                        else used.get(option.id, 0)
                                    ),
                                )
                            }
                        )
                        for option in dataset.options
                    ]
                }
            )
            errors = validate_plan(dataset, plan)
            if errors:
                raise DomainError("Current state invalidates this plan: " + "; ".join(errors))
            options = {o.id: o for o in dataset.options}
            inventories = {(i.plant_id, i.material_id): i for i in dataset.inventories}
            allocations = []
            for allocation in plan.allocations:
                option = options[allocation.option_id]
                if option.action_type == "TRANSFER":
                    source = inventories[(option.source_id, option.material_id)]
                    source.reserved += allocation.quantity
                    self.store.put_inventory(db, source)
                allocations.append(
                    allocation.model_dump()
                    | {"option": option.model_dump(), "received": False, "received_units": 0}
                )
            action = {
                "id": uuid.uuid4().hex,
                "incident_id": incident_id,
                "plan_hash": digest,
                "status": "COMMITTED",
                "synthetic": True,
                "allocations": allocations,
                "committed_at": utcnow().isoformat(),
                "estimated_cost_paise": plan.total_cost_paise,
                "executed_by": actor.id,
            }
            db.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?)",
                (action["id"], incident_id, digest, dumps(action)),
            )
            incident.update(status="MONITORING", action_id=action["id"])
            self.store.save(db, incident)
            self.store.trace(
                db,
                incident_id,
                "ActionService",
                "simulated_action_committed",
                {"action_id": action["id"]},
            )
            return action

    def receive_simulated_delivery(self, incident_id: str, actor: Principal) -> dict:
        """Explicit demo clock advancement; an API success alone cannot close an incident."""
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            if incident.get("workflow_kind") == "diagram":
                raise DomainError(
                    "Record delivery actuals and close through the workflow outcome review"
                )
            plan = self._plan(incident, incident.get("plan_hash", ""))
            authorize(actor, plan)
            if incident["status"] == "RESOLVED" and incident.get("action_id"):
                return incident
            if incident["status"] != "MONITORING":
                raise DomainError("Incident has no committed action to verify")
            row = db.execute(
                "SELECT payload FROM actions WHERE id=?", (incident["action_id"],)
            ).fetchone()
            if row is None:
                raise DomainError("Committed action record is missing")
            action = json.loads(row[0])
            inventory = {(i.plant_id, i.material_id): i for i in self.store.inventories(db)}
            for allocation in action["allocations"]:
                if allocation["received"]:
                    continue
                option = allocation["option"]
                quantity = allocation["quantity"]
                if option["action_type"] == "TRANSFER":
                    source = inventory[(option["source_id"], option["material_id"])]
                    if source.reserved < quantity or source.on_hand < quantity:
                        raise DomainError("Source reservation cannot be reconciled")
                    source.reserved -= quantity
                    source.on_hand -= quantity
                    self.store.put_inventory(db, source)
                target = inventory[(option["destination"], option["material_id"])]
                target.on_hand += quantity
                self.store.put_inventory(db, target)
                allocation["received"] = True
            action.update(status="RECEIVED", received_at=utcnow().isoformat())
            db.execute("UPDATE actions SET payload=? WHERE id=?", (dumps(action), action["id"]))
            incident.update(
                status="RESOLVED",
                closure_reason="All simulated receipts reconciled. Daily service recovery remains a planning projection, not a measured real-world outcome.",
            )
            self.store.save(db, incident)
            self.store.trace(
                db,
                incident_id,
                "Verification",
                "simulated_receipts_verified",
                {"action_id": action["id"]},
            )
            return incident
