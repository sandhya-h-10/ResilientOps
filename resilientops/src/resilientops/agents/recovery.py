from resilientops.agents.context import Context
from resilientops.analytics.business import compare_outcomes, structured_only_comparison
from resilientops.analytics.optimization import optimize
from resilientops.models import Dataset
from resilientops.services.policy import validate_plan
from resilientops.storage import fingerprint


class Recovery:
    name = "Recovery"
    description = (
        "Compare candidate actions and optimize integer allocation under deterministic constraints."
    )

    @staticmethod
    def selection_rationale(dataset: Dataset, plan, candidates) -> str:
        """Grounded local-agent explanation of a validated candidate, not a final quote."""
        options = {o.id: o for o in dataset.options}
        actions = "; ".join(
            f"{a.quantity} units from {options[a.option_id].source_id} "
            f"via {options[a.option_id].action_type.lower().replace('_', ' ')} "
            f"arriving on day {options[a.option_id].arrival_day}"
            for a in plan.allocations
        )
        cheapest = min(p["total_cost_paise"] for p in candidates)
        comparison = (
            "It has the lowest estimated cost among the current feasible candidates."
            if plan.total_cost_paise == cheapest
            else "A lower-cost candidate exists; review the source and timing trade-offs before confirming."
        )
        cost_scope = (
            "Purchase estimates exclude unquoted freight and taxes. "
            if any(
                options[a.option_id].action_type == "ALTERNATE_SUPPLIER" for a in plan.allocations
            )
            else ""
        )
        return (
            f"Plan {plan.id} provides {actions}. "
            f"Its estimated cost is INR {plan.total_cost_paise / 100:,.2f}. "
            "Against the recorded planning snapshot, the plan passes daily demand, source qualification, capacity, "
            "minimum-order and pack-size constraints. "
            f"{comparison} {cost_scope}"
            "Feasibility assumes scheduled supply and arrivals before consumption. "
            "Review these assumptions before approval; execution remains simulated."
        )[:2000]

    def run(self, context: Context) -> dict:
        plan, excluded = optimize(
            context.dataset,
            context.incident["id"],
            list(context.incident["evidence"]),
            context.incident["revision"],
        )
        errors = (
            validate_plan(context.dataset, plan) if plan.status in {"OPTIMAL", "FEASIBLE"} else []
        )
        data = plan.model_dump(mode="json")
        context.incident["plan"] = data
        context.incident["plan_hash"] = fingerprint(data)
        if context.incident.get("workflow_kind") == "diagram":
            candidates = []
            if plan.status in {"OPTIMAL", "FEASIBLE"}:
                candidates.append(plan)
                for option in context.dataset.options[:16]:
                    trial = context.dataset.model_copy(update={"options": [option]})
                    alternative, _ = optimize(
                        trial,
                        context.incident["id"],
                        list(context.incident["evidence"]),
                        context.incident["revision"],
                    )
                    alternative.snapshot_hash = fingerprint(context.dataset.model_dump(mode="json"))
                    if alternative.status in {"OPTIMAL", "FEASIBLE"} and not validate_plan(
                        context.dataset, alternative
                    ):
                        if not any(c.allocations == alternative.allocations for c in candidates):
                            candidates.append(alternative)
            for index, candidate in enumerate(candidates, 1):
                candidate.id = (
                    f"PLAN-{context.incident['id']}-R{context.incident['revision']}-{index}"
                )
            context.incident["candidates"] = [c.model_dump(mode="json") for c in candidates]
        context.evidence(
            "EV-RECOVERY",
            "CALCULATION",
            "OR-Tools SCIP",
            data,
            "Feasibility checked independently; optimality applies only to supplied candidates and assumptions.",
        )
        business = compare_outcomes(context.dataset, plan)
        comparison = structured_only_comparison(
            Dataset.model_validate(
                context.incident.get("input_snapshot", context.incident["snapshot"])
            ),
            context.dataset,
            context.incident["id"],
        )
        context.evidence(
            "EV-BUSINESS",
            "ESTIMATE",
            "Deterministic counterfactual comparison",
            business,
            business["scope"],
        )
        return {
            "plan": data,
            "plan_hash": fingerprint(data),
            "excluded_options": excluded,
            "validation_errors": errors,
            "no_action_shortage_units": context.incident["results"]["Impact"]["shortage_units"],
            "business_impact": business,
            "structured_only_baseline": comparison,
        }
