"""Persistent human decision points and feedback loops from mermaid-diagram.png."""

import json
import re
import uuid
from email.message import EmailMessage

from pydantic import Field

from resilientops.adapters.operational import OperationalData, is_operational
from resilientops.agents.commander import Commander
from resilientops.agents.context import Context
from resilientops.agents.recovery import Recovery
from resilientops.analytics.business import compare_outcomes
from resilientops.analytics.impact import calculate_impact
from resilientops.models import Dataset, Document, DomainError, Identifier, Model, Plan, utcnow
from resilientops.services.policy import current_plan_errors, validate_plan
from resilientops.services.scenarios import load_scenario
from resilientops.storage import dumps, fingerprint
from resilientops.tools.erp import ERPTools
from resilientops.tools.knowledge import LocalKnowledge


class DraftRequest(Model):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(default="", max_length=8000)
    scenario_id: Identifier = "baseline"
    shipment_id: Identifier | None = None
    delay_days: int = Field(default=0, ge=0, le=30)


class DraftEdit(DraftRequest):
    revision: int = Field(ge=1)


class RevisionRequest(Model):
    revision: int = Field(ge=1)


class ConstraintsRequest(RevisionRequest):
    max_cost_paise: int | None = Field(default=None, ge=0)
    latest_arrival_day: int | None = Field(default=None, ge=1, le=30)
    excluded_option_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    reason: str = Field(min_length=3, max_length=2000)


class SelectionRequest(RevisionRequest):
    plan_id: Identifier
    rationale: str = Field(min_length=3, max_length=2000)
    confirm_assumptions: bool


class ProgressRequest(RevisionRequest):
    update_id: Identifier
    received_units: dict[Identifier, int] = Field(default_factory=dict)
    actual_cost_paise: int = Field(ge=0)
    note: str = Field(min_length=3, max_length=2000)
    material_deviation: bool = False
    as_of_day: int = Field(default=1, ge=1, le=30)
    consumed_units: int = Field(default=0, ge=0)
    scheduled_received_units: int = Field(default=0, ge=0)


class ClosureRequest(RevisionRequest):
    outcome: str = Field(min_length=3, max_length=4000)
    lessons: str = Field(min_length=3, max_length=4000)


class DiagramWorkflow:
    def __init__(self, workflow):
        self.workflow = workflow
        self.store = workflow.store

    def _get(self, incident_id, revision=None, allowed=None, db=None):
        incident = self.store.get(incident_id, db)
        if incident.get("workflow_kind") != "diagram":
            raise DomainError("This incident uses the legacy workflow")
        if revision is not None and incident["revision"] != revision:
            raise DomainError("Incident changed; refresh before continuing")
        if allowed is not None and incident["status"] not in allowed:
            raise DomainError(f"Action not allowed while incident is {incident['status']}")
        return incident

    def _dataset(self, request):
        if request.shipment_id:
            root = self.workflow.settings.data_dir
            if not is_operational(root):
                raise DomainError("Shipment entry requires operational data", 422)
            source = OperationalData(root)
            known = {
                row["shipment_id"]
                for row in source.rows("shipments")
                if row["status"] != "RECEIVED"
            }
            if request.shipment_id not in known:
                raise DomainError("Select a known outstanding shipment", 422)
            source._tables["scenarios"] = [
                *source.rows("scenarios"),
                {
                    "scenario_id": "MANUAL",
                    "scenario_name": request.title,
                    "scenario_type": "SHIPMENT_DELAY",
                    "description": request.description,
                },
            ]
            source._tables["scenario_changes"] = [
                *source.rows("scenario_changes"),
                {
                    "scenario_id": "MANUAL",
                    "change_id": "MANUAL-ENTRY",
                    "change_type": "SHIPMENT_DELAY",
                    "target_id": request.shipment_id,
                    "parameters": {"delay_days": request.delay_days},
                },
            ]
            return source.snapshot("MANUAL")
        return load_scenario(
            self.workflow.dataset, self.workflow.settings.data_dir, request.scenario_id
        )[0]

    def create(self, request: DraftRequest, actor: str, detection_key=None):
        dataset = self._dataset(request)
        self._add_evidence(dataset, request)
        with self.store.transaction() as db:
            event_id = detection_key or f"MANUAL-{uuid.uuid4().hex}"
            found = db.execute("SELECT id FROM incidents WHERE event_id=?", (event_id,)).fetchone()
            if found:
                return self.store.get(found[0], db)
            dataset.event.id = event_id
            dataset = self.workflow.snapshot(db, dataset)
            incident = {
                "id": uuid.uuid4().hex[:16],
                "event_id": event_id,
                "workflow_kind": "diagram",
                "status": "DRAFT",
                "created_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
                "revision": 1,
                "agent_mode": self.workflow.settings.agent_mode,
                "evidence_mode": self.workflow.settings.effective_evidence_mode,
                "scenario_id": request.scenario_id,
                "scenario_title": request.title,
                "entry_mode": "detected" if detection_key else "manual",
                "created_by": actor,
                "draft": request.model_dump(),
                "snapshot": dataset.model_dump(mode="json"),
                "input_snapshot": dataset.model_dump(mode="json"),
                "results": {},
                "evidence": {},
                "plan": None,
                "plan_hash": None,
                "approval": None,
                "error": None,
                "candidates": [],
                "history": [],
                "decision_history": [],
                "progress": [],
            }
            db.execute(
                "INSERT INTO incidents VALUES (?, ?, ?)",
                (incident["id"], event_id, dumps(incident)),
            )
            self.store.trace(
                db,
                incident["id"],
                actor,
                "incident_drafted",
                {"entry_mode": incident["entry_mode"]},
            )
            return incident

    def detect(self):
        """Evaluate supplied synthetic overlays; never infer causal outages from archived news."""
        root = self.workflow.settings.data_dir
        if not is_operational(root):
            return []
        source = OperationalData(root)
        found = []
        for spec in source.catalog():
            if (
                spec["id"] == "baseline"
                or not spec["supported"]
                or (spec.get("showcase") and not spec["id"].startswith("RISK_"))
            ):
                continue
            dataset = source.snapshot(spec["id"])
            impact = calculate_impact(dataset)
            from resilientops.analytics.disruptions import assess_disruptions

            monitoring = assess_disruptions(dataset.source_metadata.get("disruption_signals", []))
            if impact["shortage_units"] or monitoring["anomalies"]:
                draft = DraftRequest(
                    title=spec["title"],
                    description=spec["description"],
                    scenario_id=spec["id"],
                    evidence=f"Synthetic overlay {spec['id']}: peak shortage {impact['shortage_units']} units. Human review required.",
                )
                found.append(
                    self.create(
                        draft,
                        "Synthetic overlay detector",
                        f"DETECT-{source.manifest['dataset_version']}-{spec['id']}",
                    )
                )
        return found

    def edit(self, incident_id, request: DraftEdit, actor):
        dataset = self._dataset(request)
        self._add_evidence(dataset, request)
        with self.store.transaction() as db:
            incident = self._get(incident_id, request.revision, {"DRAFT"}, db)
            dataset.event.id = incident["event_id"]
            dataset = self.workflow.snapshot(db, dataset)
            incident.update(
                draft=request.model_dump(exclude={"revision"}),
                scenario_title=request.title,
                scenario_id=request.scenario_id,
                snapshot=dataset.model_dump(mode="json"),
                input_snapshot=dataset.model_dump(mode="json"),
                revision=incident["revision"] + 1,
            )
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, actor, "draft_edited", {"revision": incident["revision"]}
            )
            return incident

    def _add_evidence(self, dataset, request):
        dataset.documents.append(
            Document(
                id="OPERATOR-EVIDENCE",
                title="Operator incident evidence",
                text=request.description + "\n" + request.evidence,
                document_type="INCIDENT",
                version=1,
            )
        )

    def assess(self, incident_id, request: RevisionRequest, actor):
        with self.store.transaction() as db:
            incident = self._get(incident_id, request.revision, {"DRAFT"}, db)
            incident.update(status="DETECTED", reviewed_by=actor, reviewed_at=utcnow().isoformat())
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, actor, "assessment_requested", {"revision": incident["revision"]}
            )
            return incident

    def _archive(self, incident, reason):
        incident["history"].append(
            {
                key: incident.get(key)
                for key in (
                    "revision",
                    "snapshot",
                    "results",
                    "evidence",
                    "plan",
                    "plan_hash",
                    "approval",
                    "selected_plan_id",
                    "approval_report",
                    "status",
                    "progress",
                    "action_id",
                    "actual_cost_paise",
                )
            }
            | {"reason": reason, "at": utcnow().isoformat()}
        )

    def _reset(self, incident, dataset):
        incident.update(
            revision=incident["revision"] + 1,
            status="DETECTED",
            results={},
            evidence={},
            plan=None,
            plan_hash=None,
            approval=None,
            selected_plan_id=None,
            approval_report=None,
            candidates=[],
            agent_reviews={},
            retrievals={},
            error=None,
            commentary={},
            model_usage=[],
            snapshot=dataset.model_dump(mode="json"),
            input_snapshot=dataset.model_dump(mode="json"),
        )

    def replan(self, incident_id, request: ConstraintsRequest, actor):
        with self.store.transaction() as db:
            incident = self._get(
                incident_id,
                request.revision,
                {
                    "AWAITING_SELECTION",
                    "PLANNING_BLOCKED",
                    "CHANGES_REQUESTED",
                    "AWAITING_APPROVAL",
                    "APPROVED",
                    "READY_FOR_EXECUTION",
                    "ESCALATED",
                },
                db,
            )
            dataset = Dataset.model_validate(incident["input_snapshot"])
            if not set(request.excluded_option_ids).issubset({o.id for o in dataset.options}):
                raise DomainError("Unknown recovery option constraint", 422)
            dataset.max_cost_paise = request.max_cost_paise
            dataset.latest_arrival_day = request.latest_arrival_day
            dataset.excluded_option_ids = request.excluded_option_ids
            dataset = self.workflow.snapshot(db, dataset)
            self._archive(incident, request.reason)
            self._reset(incident, dataset)
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, actor, "recovery_replanning_requested", request.model_dump()
            )
            return incident

    def migrate_selected_simulations(self):
        if self.workflow.settings.erp_mode != "local":
            return
        with self.store.transaction() as db:
            for row in db.execute("SELECT payload FROM incidents").fetchall():
                incident = json.loads(row[0])
                if (
                    incident.get("workflow_kind") == "diagram"
                    and incident.get("selected_plan_id")
                    and incident["status"] in {"AWAITING_APPROVAL", "APPROVED"}
                ):
                    incident["status"] = "READY_FOR_EXECUTION"
                    incident["results"]["Commander"].update(
                        requires_approval=False, required_role=None
                    )
                    incident["approval_report"] = self.report(incident)
                    self.store.save(db, incident)
                    self.store.trace(
                        db,
                        incident["id"],
                        "System",
                        "approval_gate_removed",
                        {"scope": "Local simulation; explicit planner release retained"},
                    )

    def selection_rationale(self, incident_id, plan_id, revision):
        with self.store.transaction() as db:
            incident = self._get(incident_id, revision, {"AWAITING_SELECTION"}, db)
            candidate = next((p for p in incident["candidates"] if p["id"] == plan_id), None)
            if candidate is None:
                raise DomainError("Unknown candidate plan", 422)
            plan = Plan.model_validate(candidate)
            dataset = Dataset.model_validate(incident["snapshot"])
            errors = validate_plan(dataset, plan)
            if errors:
                raise DomainError("; ".join(errors))
            return {
                "plan_id": plan_id,
                "revision": revision,
                "stale": bool(current_plan_errors(self.store, db, dataset, plan)),
                "stale_reasons": current_plan_errors(self.store, db, dataset, plan),
                "generated_by": "Recovery agent · validated plan analysis",
                "rationale": Recovery.selection_rationale(dataset, plan, incident["candidates"]),
            }

    def select(self, incident_id, request: SelectionRequest, actor):
        with self.store.transaction() as db:
            incident = self._get(incident_id, request.revision, {"AWAITING_SELECTION"}, db)
            if not request.confirm_assumptions:
                raise DomainError("Review and acknowledge the plan assumptions", 422)
            candidate = next(
                (p for p in incident["candidates"] if p["id"] == request.plan_id), None
            )
            if candidate is None:
                raise DomainError("Unknown candidate plan", 422)
            plan = Plan.model_validate(candidate)
            dataset = Dataset.model_validate(incident["snapshot"])
            errors = current_plan_errors(self.store, db, dataset, plan) + validate_plan(
                dataset, plan
            )
            if errors:
                raise DomainError("; ".join(errors))
            incident.update(
                plan=plan.model_dump(mode="json"),
                plan_hash=fingerprint(plan.model_dump(mode="json")),
                selected_plan_id=plan.id,
                selected_by=actor,
                selection_rationale=request.rationale,
                selected_at=utcnow().isoformat(),
                status="READY_FOR_EXECUTION"
                if self.workflow.settings.erp_mode == "local"
                else "AWAITING_APPROVAL",
                approval=None,
            )
            context = Context(
                incident, dataset, ERPTools(dataset), LocalKnowledge(dataset.documents)
            )
            context.evidence(
                "EV-RECOVERY",
                "CALCULATION",
                "Planner-selected feasible recovery",
                incident["plan"],
                "Independently validated selected plan.",
            )
            business = compare_outcomes(dataset, plan)
            context.evidence(
                "EV-BUSINESS", "ESTIMATE", "Selected plan comparison", business, business["scope"]
            )
            incident["results"]["Recovery"].update(
                plan=incident["plan"], plan_hash=incident["plan_hash"], business_impact=business
            )
            incident["results"]["Commander"] = Commander().run(context)
            incident["approval_report"] = self.report(incident)
            self.store.save(db, incident)
            self.store.trace(
                db,
                incident_id,
                actor,
                "plan_selected_report_generated",
                {"plan_id": plan.id, "plan_hash": incident["plan_hash"]},
            )
            return incident

    def report(self, incident):
        plan = Plan.model_validate(incident["plan"])
        dataset = Dataset.model_validate(incident["snapshot"])
        options = {o.id: o for o in dataset.options}
        lines = [
            f"Incident: {incident['scenario_title']} ({incident['id']})",
            f"Plan: {plan.id}; revision {incident['revision']}",
            f"Plan hash: {incident['plan_hash']}",
            f"Planner: {incident['selected_by']}",
            f"Rationale: {incident['selection_rationale']}",
            f"Execution policy: {plan.approval_policy}. Planner release; no separate approval gate in local simulation.",
            f"Estimated cost: INR {plan.total_cost_paise / 100:,.2f}",
            "Validity: until relevant planning data, inventory, capacity commitments or constraints change.",
            "Proposed simulated actions:",
        ]
        for allocation in plan.allocations:
            option = options[allocation.option_id]
            lines.append(
                f"- {option.action_type}: {allocation.quantity} units of {option.material_id}, {option.source_id} -> {option.destination}, arrival day {option.arrival_day}; source {option.id}"
            )
        lines += [
            "Evidence: " + ", ".join(plan.evidence_ids),
            "Assumptions:",
            *plan.assumptions,
            *dataset.source_metadata.get("limitations", []),
            "Select a plan and release it separately. No real order, transfer or email is sent.",
        ]
        return {
            "subject": f"Recovery execution plan: {incident['scenario_title']} · revision {incident['revision']}",
            "body": "\n".join(lines),
            "generated_at": utcnow().isoformat(),
            "plan_hash": incident["plan_hash"],
        }

    def email(self, incident_id):
        incident = self._get(incident_id)
        report = incident.get("approval_report")
        if not report:
            raise DomainError("Select a feasible plan to generate an execution report")
        message = EmailMessage()
        message["Subject"] = report["subject"].replace("\r", " ").replace("\n", " ")
        message.set_content(
            re.sub(
                r"^Expires:.*$",
                "Validity: until relevant planning data or constraints change.",
                report["body"],
                flags=re.MULTILINE,
            )
        )
        return message.as_bytes()

    def progress(self, incident_id, request: ProgressRequest, actor):
        if any(not isinstance(qty, int) or qty < 0 for qty in request.received_units.values()):
            raise DomainError("Received quantities must be nonnegative integers", 422)
        with self.store.transaction() as db:
            incident = self._get(incident_id, db=db)
            previous = next(
                (p for p in incident["progress"] if p["update_id"] == request.update_id), None
            )
            if previous:
                if previous["request"] != request.model_dump():
                    raise DomainError("Progress update ID reused with different data")
                return incident
            self._get(incident_id, request.revision, {"MONITORING"}, db)
            action = json.loads(
                db.execute(
                    "SELECT payload FROM actions WHERE id=?", (incident["action_id"],)
                ).fetchone()[0]
            )
            dataset = Dataset.model_validate(incident["snapshot"])
            if (
                request.as_of_day < incident.get("actuals_as_of_day", 1)
                or request.as_of_day > dataset.event.planning_days
            ):
                raise DomainError("Actuals date must advance within the planning horizon", 422)
            by_id = {a["option_id"]: a for a in action["allocations"]}
            if request.actual_cost_paise < incident.get("actual_cost_paise", 0):
                raise DomainError("Cumulative actual cost cannot decrease", 422)
            if not set(request.received_units).issubset(by_id):
                raise DomainError("Actuals reference an unknown action", 422)
            inventory = {(i.plant_id, i.material_id): i for i in self.store.inventories(db)}
            destination = inventory[(dataset.event.plant_id, dataset.event.material_id)]
            for option_id, quantity in request.received_units.items():
                allocation = by_id[option_id]
                delta = quantity - allocation.get("received_units", 0)
                if delta < 0 or quantity > allocation["quantity"]:
                    raise DomainError(
                        "Cumulative receipts cannot decrease or exceed approved quantity", 422
                    )
                option = allocation["option"]
                if option["action_type"] == "TRANSFER":
                    donor = inventory[(option["source_id"], option["material_id"])]
                    if donor.reserved < delta or donor.on_hand < delta:
                        raise DomainError("Transfer reservation cannot be reconciled")
                    donor.reserved -= delta
                    donor.on_hand -= delta
                    self.store.put_inventory(db, donor)
                destination.on_hand += delta
                allocation.update(
                    received_units=quantity, received=quantity == allocation["quantity"]
                )
            destination.on_hand += request.scheduled_received_units
            if request.consumed_units > destination.available:
                raise DomainError("Consumption exceeds usable stock", 422)
            destination.on_hand -= request.consumed_units
            self.store.put_inventory(db, destination)
            complete = all(a["received"] for a in action["allocations"])
            late = any(
                not a["received"] and a["option"]["arrival_day"] < request.as_of_day
                for a in action["allocations"]
            )
            deviation = (
                request.material_deviation
                or late
                or request.actual_cost_paise > incident["plan"]["total_cost_paise"]
            )
            incident["progress"].append(
                {
                    "update_id": request.update_id,
                    "request": request.model_dump(),
                    "at": utcnow().isoformat(),
                    "actor": actor,
                    "material_deviation": deviation,
                }
            )
            incident.update(
                actual_cost_paise=request.actual_cost_paise, actuals_as_of_day=request.as_of_day
            )
            action["actual_cost_paise"] = request.actual_cost_paise
            if deviation:
                # Cancel only the unreceived remainder; preserve real simulated receipts.
                for allocation in action["allocations"]:
                    if allocation["option"]["action_type"] == "TRANSFER":
                        donor = inventory[
                            (allocation["option"]["source_id"], allocation["option"]["material_id"])
                        ]
                        donor.reserved -= allocation["quantity"] - allocation.get(
                            "received_units", 0
                        )
                        self.store.put_inventory(db, donor)
                action["status"] = "CANCELLED"
                self._archive(incident, "Material deviation: " + request.note)
                dataset = self.workflow.snapshot(db, dataset)
                # Reassessment starts after the recorded day. Actual receipts
                # replace elapsed scheduled receipts; unconsumed demand remains
                # backlog, rather than disappearing from the impact calculation.
                consumed = sum(
                    p["request"]["consumed_units"]
                    for p in incident["progress"]
                    if p["request"]["revision"] == incident["revision"]
                )
                backlog = max(0, sum(dataset.daily_demand[: request.as_of_day]) - consumed)
                dataset.daily_demand = [
                    0 if day <= request.as_of_day else qty
                    for day, qty in enumerate(dataset.daily_demand, 1)
                ]
                dataset.scheduled_receipts = [
                    0 if day <= request.as_of_day else dataset.receipt_on(day)
                    for day in range(1, dataset.event.planning_days + 1)
                ]
                dataset.daily_demand[min(request.as_of_day, dataset.event.planning_days - 1)] += (
                    backlog
                )
                if is_operational(self.workflow.settings.data_dir):
                    dataset.options = OperationalData(
                        self.workflow.settings.data_dir
                    ).recovery_options(
                        dataset.event.plant_id, dataset.event.material_id, request.as_of_day + 1
                    )
                else:
                    dataset.options = [
                        o.model_copy(update={"arrival_day": o.arrival_day + request.as_of_day})
                        for o in dataset.options
                        if o.arrival_day + request.as_of_day <= dataset.event.planning_days
                    ]
                dataset.source_metadata["reassessment"] = {
                    "as_of_day": request.as_of_day,
                    "note": request.note,
                }
                self._reset(incident, dataset)
                incident["actual_cost_paise"] = 0
                incident.pop("action_id", None)
            else:
                action["status"] = "RECEIVED" if complete else "COMMITTED"
                incident["status"] = "AWAITING_CLOSURE" if complete else "MONITORING"
            db.execute("UPDATE actions SET payload=? WHERE id=?", (dumps(action), action["id"]))
            self.store.save(db, incident)
            self.store.trace(
                db,
                incident_id,
                actor,
                "material_deviation_reassessment" if deviation else "actuals_recorded",
                {"update_id": request.update_id, "complete": complete},
            )
            return incident

    def close(self, incident_id, request: ClosureRequest, actor):
        with self.store.transaction() as db:
            incident = self._get(incident_id, request.revision, {"AWAITING_CLOSURE"}, db)
            actions = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM actions WHERE incident_id=?", (incident_id,)
                )
            ]
            actual = sum(a.get("actual_cost_paise", 0) for a in actions)
            planned = sum(a.get("estimated_cost_paise", 0) for a in actions)
            incident["outcome"] = {
                "summary": request.outcome,
                "lessons": request.lessons,
                "recorded_by": actor,
                "closed_at": utcnow().isoformat(),
                "planned_cost_paise": planned,
                "actual_cost_paise": actual,
                "cost_variance_paise": actual - planned,
                "revisions": incident["revision"],
                "scope": "Operator-reported simulated outcomes; retained lessons, not model retraining.",
            }
            incident["status"] = "RESOLVED"
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, actor, "incident_closed_learning_captured", incident["outcome"]
            )
            return incident
