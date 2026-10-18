"""Persistent business workflow with optional Gemini/ADK stage orchestration."""

import asyncio
import uuid
from datetime import datetime, timedelta
from time import perf_counter

from resilientops.adapters.operational import is_operational, load_dataset
from resilientops.agents import STAGES
from resilientops.agents.context import Context
from resilientops.config import Settings
from resilientops.models import Dataset, DomainError, ShipmentUpdate, UpdateSubmission, utcnow
from resilientops.services.scenarios import load_scenario
from resilientops.storage import Store, dumps
from resilientops.tools.erp import ERPTools
from resilientops.tools.knowledge import LocalKnowledge


class Workflow:
    def __init__(self, settings: Settings, store: Store, extractor=None):
        settings.validate()
        self.settings = settings
        self.store = store
        self.extractor = extractor
        self.dataset = load_dataset(settings.data_dir)
        if settings.erp_mode == "bigquery":
            if is_operational(settings.data_dir):
                raise ValueError(
                    "Operational data requires a dedicated BigQuery schema adapter; use local ERP mode"
                )
            from resilientops.adapters.bigquery import BigQueryERP

            self.dataset = BigQueryERP(settings.project, settings.bigquery_dataset).load_dataset(
                self.dataset
            )
        store.seed(self.dataset)

    def snapshot(self, db=None, dataset=None) -> Dataset:
        from resilientops.services.policy import capacity_commitments

        if db is None:
            with self.store.connect() as connection:
                return self.snapshot(connection, dataset)
        source = dataset or self.dataset
        return source.model_copy(
            update={
                "inventories": self.store.inventories(db),
                "source_metadata": {
                    **source.source_metadata,
                    "capacity_commitments": capacity_commitments(db, source),
                },
            }
        )

    def create(self, scenario_id="baseline") -> dict:
        dataset, title = load_scenario(self.dataset, self.settings.data_dir, scenario_id)
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT id FROM incidents WHERE event_id=?", (dataset.event.id,)
            ).fetchone()
            if row:
                return self.store.get(row[0], db)
            incident_id = uuid.uuid4().hex[:16]
            snapshot = self.snapshot(db, dataset)
            incident = {
                "id": incident_id,
                "event_id": snapshot.event.id,
                "status": "DETECTED",
                "created_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
                "revision": 1,
                "agent_mode": self.settings.agent_mode,
                "evidence_mode": self.settings.effective_evidence_mode,
                "scenario_id": scenario_id,
                "scenario_title": title,
                "snapshot": snapshot.model_dump(mode="json"),
                "input_snapshot": snapshot.model_dump(mode="json"),
                "results": {},
                "evidence": {},
                "plan": None,
                "plan_hash": None,
                "approval": None,
                "error": None,
            }
            db.execute(
                "INSERT INTO incidents VALUES (?, ?, ?)",
                (incident_id, snapshot.event.id, dumps(incident)),
            )
            self.store.trace(db, incident_id, "System", "incident_created", {"synthetic": True})
            return incident

    def reanalyze(
        self, incident_id: str, update: UpdateSubmission | None = None, actor_id: str | None = None
    ) -> dict:
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            if incident["status"] not in {
                "AWAITING_SELECTION",
                "PLANNING_BLOCKED",
                "CHANGES_REQUESTED",
                "AWAITING_CLOSURE",
                "AWAITING_APPROVAL",
                "APPROVED",
                "REJECTED",
                "ESCALATED",
                "FAILED",
            }:
                raise DomainError("Only unexecuted decisions can be reanalyzed")
            original = Dataset.model_validate(incident.get("input_snapshot", incident["snapshot"]))
            if update:
                if len(original.updates) >= 8:
                    raise DomainError(
                        "This prototype supports at most eight source messages per incident"
                    )
                source = ShipmentUpdate(
                    id=f"UPDATE-{uuid.uuid4().hex[:12]}",
                    received_at=utcnow(),
                    **update.model_dump(),
                )
                if not set(source.supersedes).issubset({u.id for u in original.updates}):
                    raise DomainError(
                        "A correction can replace only known source IDs in this incident"
                    )
                original.updates.append(source)
                original = Dataset.model_validate(original.model_dump())
                self.store.trace(
                    db,
                    incident_id,
                    "Human",
                    "source_update_received",
                    {
                        "source_id": source.id,
                        "supersedes": source.supersedes,
                        "actor": actor_id,
                    },
                )
            refreshed = self.snapshot(db, original).model_dump(mode="json")
            incident.update(
                status="DETECTED",
                results={},
                evidence={},
                plan=None,
                plan_hash=None,
                approval=None,
                error=None,
                snapshot=refreshed,
                input_snapshot=refreshed,
                agent_reviews={},
                retrievals={},
                commentary={},
                model_usage=[],
                revision=incident["revision"] + 1,
            )
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, "System", "analysis_reset", {"revision": incident["revision"]}
            )
            return incident

    def _claim(self, incident_id: str, owner: str) -> bool:
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            if incident["status"] == "ANALYZING":
                if datetime.fromisoformat(incident["lease_until"]) > utcnow():
                    return False
            elif incident["status"] not in {"DETECTED", "FAILED"}:
                return False
            if incident["status"] == "FAILED":
                incident.update(
                    results={},
                    evidence={},
                    agent_reviews={},
                    retrievals={},
                    commentary={},
                    model_usage=[],
                    plan=None,
                    plan_hash=None,
                    candidates=[],
                    snapshot=incident.get("input_snapshot", incident["snapshot"]),
                )
            incident.update(
                status="ANALYZING",
                agent_mode=self.settings.agent_mode,
                evidence_mode=self.settings.effective_evidence_mode,
                analysis_owner=owner,
                error=None,
                lease_until=(
                    utcnow() + timedelta(seconds=self.settings.analysis_timeout + 10)
                ).isoformat(),
            )
            self.store.save(db, incident)
            return True

    def run_stage(self, incident_id: str, name: str, owner: str) -> dict:
        incident = self.store.get(incident_id)
        if incident["status"] != "ANALYZING" or incident.get("analysis_owner") != owner:
            raise DomainError("Analysis lease is not owned by this worker")
        if name in incident["results"]:
            if incident["results"][name].get("blocking_issues"):
                raise DomainError("Evidence review is required before continuing")
            return incident["results"][name]
        names = [stage.name for stage in STAGES]
        index = names.index(name)
        if self.settings.agent_mode == "google":
            for prior in names[:index]:
                review = incident.get("agent_reviews", {}).get(prior)
                if not review or review["verdict"] != "continue":
                    raise DomainError(f"{prior} reasoning is missing or requires review")
        if any(prior not in incident["results"] for prior in names[:index]):
            raise DomainError("Required predecessor stage has not completed")
        if any(incident["results"][prior].get("blocking_issues") for prior in names[:index]):
            raise DomainError("Unresolved evidence blocks downstream planning")
        dataset = Dataset.model_validate(incident["snapshot"])
        knowledge = LocalKnowledge(dataset.documents)
        if self.settings.knowledge_mode == "vertex":
            from resilientops.adapters.vertex import VertexKnowledge

            knowledge = VertexKnowledge(self.settings, dataset.documents)
        context = Context(
            incident, dataset, ERPTools(dataset), knowledge, self.settings, self.extractor
        )
        with self.store.transaction() as db:
            self.store.trace(db, incident_id, name, "started", {})
        started = perf_counter()
        result = STAGES[index].run(context)
        result["latency_ms"] = round((perf_counter() - started) * 1000, 2)
        with self.store.transaction() as db:
            latest = self.store.get(incident_id, db)
            if latest["status"] != "ANALYZING" or latest.get("analysis_owner") != owner:
                raise DomainError("Analysis was cancelled or superseded; result discarded")
            # ADK may issue retrieval alongside a stage call; preserve their newer audit records.
            for field in ("retrievals", "agent_reviews", "commentary", "model_usage"):
                if field in latest:
                    incident[field] = latest[field]
            incident["results"][name] = result
            incident["snapshot"] = context.dataset.model_dump(mode="json")
            self.store.save(db, incident)
            self.store.trace(
                db, incident_id, name, "completed", {"evidence_count": len(incident["evidence"])}
            )
        if result.get("blocking_issues"):
            raise DomainError("; ".join(result["blocking_issues"]))
        return result

    async def analyze(self, incident_id: str) -> dict:
        started = perf_counter()
        owner = uuid.uuid4().hex
        if not self._claim(incident_id, owner):
            return self.store.get(incident_id)
        try:
            async with asyncio.timeout(self.settings.analysis_timeout):
                if self.settings.agent_mode == "google":
                    from resilientops.agents.google_adk import run_google_workflow

                    await run_google_workflow(self, incident_id, owner)
                else:
                    for stage in STAGES:
                        await asyncio.to_thread(self.run_stage, incident_id, stage.name, owner)
            with self.store.transaction() as db:
                incident = self.store.get(incident_id, db)
                if incident.get("analysis_owner") != owner:
                    raise DomainError("Analysis superseded")
                if any(stage.name not in incident["results"] for stage in STAGES):
                    raise DomainError("Agent workflow did not produce every required stage")
                if (
                    self.settings.effective_evidence_mode == "gemini"
                    and (incident["results"]["Investigator"].get("context_extraction") or {}).get(
                        "provider"
                    )
                    != "gemini"
                ):
                    raise DomainError("Mandatory Gemini extraction was not completed")
                if self.settings.agent_mode == "google":
                    reviews = incident.get("agent_reviews", {})
                    if any(s.name not in reviews for s in STAGES):
                        raise DomainError(
                            "Every Gemini agent must submit an evidence-backed assessment"
                        )
                    if any(r["verdict"] == "needs_review" for r in reviews.values()):
                        raise DomainError("Gemini assessment requires planner review")
                decision = incident["results"]["Commander"]
                if incident.get("workflow_kind") == "diagram":
                    incident["status"] = (
                        "AWAITING_CLOSURE"
                        if incident["plan"]["status"] == "NO_ACTION"
                        else "PLANNING_BLOCKED"
                        if decision["validation_errors"]
                        else "AWAITING_SELECTION"
                    )
                    incident["error"] = "; ".join(decision["validation_errors"]) or None
                elif incident["plan"]["status"] == "NO_ACTION":
                    incident.update(
                        status="RESOLVED",
                        closure_reason="No shortage predicted in this planning snapshot; no action executed.",
                    )
                elif decision["validation_errors"]:
                    incident.update(
                        status="ESCALATED", error="; ".join(decision["validation_errors"])
                    )
                else:
                    incident["status"] = "AWAITING_APPROVAL"
                self.store.save(db, incident)
                self.store.trace(
                    db, incident_id, "System", "analysis_finished", {"status": incident["status"]}
                )
        except Exception as exc:
            with self.store.transaction() as db:
                incident = self.store.get(incident_id, db)
                if incident.get("analysis_owner") == owner:
                    # Unexpected SDK errors may contain credentials or request payloads.
                    error = (
                        str(exc)
                        if isinstance(exc, DomainError)
                        else f"Analysis failed: {type(exc).__name__}"
                    )
                    if (
                        "ResourceExhausted" in type(exc).__name__
                        or getattr(exc, "code", None) == 429
                    ):
                        error = "Gemini request quota exhausted. Wait for the quota window to reset or adjust the project's quota, then retry. No local fallback was used."
                    if type(exc).__name__ == "LlmCallsLimitExceededError":
                        error = (
                            f"Agent analysis reached its {self.settings.max_llm_calls}-call budget "
                            "before all reviews completed. Vertex AI authentication is working; "
                            "the workflow needs a revised call budget or fewer agent requests."
                        )
                    incident.update(
                        status="ESCALATED" if isinstance(exc, DomainError) else "FAILED",
                        error=error,
                    )
                    self.store.save(db, incident)
                    self.store.trace(db, incident_id, "System", "analysis_failed", {"error": error})
        with self.store.transaction() as db:
            incident = self.store.get(incident_id, db)
            if incident.get("analysis_owner") == owner:
                incident["analysis_latency_ms"] = round((perf_counter() - started) * 1000, 2)
                self.store.save(db, incident)
        return self.store.get(incident_id)
