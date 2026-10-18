"""Role-specific reasoning contracts. Only evidence-backed review decisions are persisted."""

from typing import Literal

from pydantic import Field

from resilientops.models import DomainError, Model

ROLE_INSTRUCTIONS = {
    "Sentinel": "Independently triage external (political, economic, environmental, technological, social, legal), internal (equipment, quality, workforce, systems), and market (supplier or demand) signals. Compare held-out observations against historical baselines. Distinguish anomaly from causality and source category from verified cause. Explain whether investigation is warranted.",
    "Investigator": "Independently challenge the disruption hypothesis. Retrieve notices, supplier evidence and policies. Gemini extraction is mandatory in your stage tool. Reconcile explicit corrections, report competing explanations, and request review for unresolved evidence rather than guessing operational facts.",
    "Impact": "Independently interpret the validated time-phased exposure. Identify when shortages begin, which dependencies and orders matter, and what assumptions could change the conclusion. Do not equate allocated order value with loss or invent production rescheduling results.",
    "Recovery": "Independently compare candidate plans on timing, source concentration, cost and evidence quality. Explain trade-offs and recommend a supplied candidate ID when feasible. If none are feasible, explain the binding constraints and suggest which assumptions the planner should review. Never invent a plan or override constraints.",
    "Commander": "Independently critique the complete decision package using all earlier agents and cited policies. Check unresolved uncertainties, evidence coverage and release readiness. Produce a concise recommendation for the human planner. You cannot approve or execute; request review when an unresolved material issue remains.",
}


class AgentReview(Model):
    summary: str = Field(min_length=10, max_length=3000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    uncertainties: list[str] = Field(max_length=10)
    next_action: str = Field(min_length=3, max_length=1000)
    verdict: Literal["continue", "needs_review"]
    recommended_plan_id: str | None = None


def save_review(workflow, incident_id, owner, stage, values):
    review = AgentReview.model_validate(values)
    with workflow.store.transaction() as db:
        incident = workflow.store.get(incident_id, db)
        if incident.get("analysis_owner") != owner or incident["status"] != "ANALYZING":
            raise DomainError("Analysis superseded")
        if stage not in incident["results"]:
            raise DomainError("Run the stage analysis before submitting its reasoning")
        retrievals = incident.get("retrievals", {}).get(stage, [])
        if not retrievals:
            raise DomainError("Retrieve evidence before submitting agent reasoning")
        allowed = set(incident["evidence"]) | {d for row in retrievals for d in row["document_ids"]}
        if not set(review.evidence_ids).issubset(allowed):
            raise DomainError("Agent cited evidence that was not available")
        if review.recommended_plan_id and review.recommended_plan_id not in {
            p["id"] for p in incident.get("candidates", [])
        }:
            raise DomainError("Recommendation must reference a generated candidate")
        record = review.model_dump(mode="json")
        record["model"] = workflow.settings.model
        record["scope"] = (
            "Gemini assessment; citations validate references, not semantic truth. Deterministic plan checks remain authoritative."
        )
        incident.setdefault("agent_reviews", {})[stage] = record
        workflow.store.save(db, incident)
        workflow.store.trace(db, incident_id, stage, "reasoned_review", record)
    return record
