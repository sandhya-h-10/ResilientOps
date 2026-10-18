from resilientops.agents.context import Context
from resilientops.models import Plan
from resilientops.services.grounding import CLAIMS, validate_claims
from resilientops.services.policy import required_role, validate_plan


class Commander:
    name = "Commander"
    description = (
        "Prepare an evidence-grounded decision package; never authorize or execute actions."
    )

    def run(self, context: Context) -> dict:
        plan = Plan.model_validate(context.incident["plan"])
        claims = [
            {
                "label": label,
                "evidence_id": ref,
                "field": field,
                "value": context.incident["evidence"][ref]["value"][field],
            }
            for label, (ref, field) in CLAIMS.items()
        ]
        validate_claims(claims, context.incident["evidence"])
        errors = validate_plan(context.dataset, plan) if plan.status != "NO_ACTION" else []
        return {
            "claims": claims,
            "requires_approval": plan.status in {"OPTIMAL", "FEASIBLE"}
            and context.incident.get("status") != "READY_FOR_EXECUTION",
            "required_role": None
            if context.incident.get("status") == "READY_FOR_EXECUTION"
            else required_role(plan),
            "policy_version": plan.approval_policy,
            "validation_errors": errors,
            "recommendation": "Review the proposed simulated recovery plan."
            if not errors
            else "Escalate: no executable plan satisfies the constraints.",
            "evidence_coverage": 1.0,
            "scope": "Machine-checkable claims only; free-form model commentary is not an executable decision.",
        }
