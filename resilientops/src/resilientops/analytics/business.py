"""Counterfactual planning metrics, with assumptions distinct from actual outcomes."""

from collections import defaultdict

from resilientops.analytics.optimization import optimize
from resilientops.models import Dataset, Plan
from resilientops.services.policy import validate_plan


def compare_outcomes(dataset: Dataset, plan: Plan) -> dict:
    inventory = next(
        i
        for i in dataset.inventories
        if i.plant_id == dataset.event.plant_id and i.material_id == dataset.event.material_id
    )
    options = {o.id: o for o in dataset.options}
    executable = plan.status in {"OPTIMAL", "FEASIBLE"} and not validate_plan(dataset, plan)
    arrivals = defaultdict(int)
    if executable:
        for allocation in plan.allocations:
            arrivals[options[allocation.option_id].arrival_day] += allocation.quantity
    rows, demand, supply = [], 0, inventory.available
    baseline_supply = inventory.available
    for day, units in enumerate(dataset.daily_demand, 1):
        demand += units
        baseline_supply += dataset.receipt_on(day)
        supply += dataset.receipt_on(day) + arrivals[day]
        rows.append(
            {
                "day": day,
                "demand": units,
                "recovery_arrivals": arrivals[day],
                "scheduled_receipts": dataset.receipt_on(day),
                "shortage_without_action": max(0, demand - baseline_supply),
                "shortage_with_plan": max(0, demand - supply),
            }
        )
    before, after = rows[-1]["shortage_without_action"], rows[-1]["shortage_with_plan"]
    reduction = before - after
    cost = plan.total_cost_paise if executable else 0
    return {
        "timeline": rows,
        "without_action_shortage_units": before,
        "with_plan_shortage_units": after,
        "shortage_units_covered": reduction,
        "uncovered_unit_days_without_action": sum(r["shortage_without_action"] for r in rows),
        "uncovered_unit_days_with_plan": sum(r["shortage_with_plan"] for r in rows),
        "recovery_cost_paise": cost,
        "assumed_cost_per_short_unit_paise": dataset.unit_shortage_cost_paise,
        "modeled_exposure_reduction_paise": reduction * dataset.unit_shortage_cost_paise,
        "modeled_net_benefit_paise": reduction * dataset.unit_shortage_cost_paise - cost,
        "scope": "Synthetic planning comparison. Exposure uses an assumed cost per end-of-horizon short unit; it is not measured savings, revenue, downtime or realized benefit. Arrivals precede consumption. Scheduled receipts are included when supplied. Operational data has no per-component exposure valuation; its zero cost input means unvalued, not no loss.",
        "executable_plan": executable,
    }


def structured_only_comparison(original: Dataset, updated: Dataset, incident_id: str):
    plan, _ = optimize(original, f"BASELINE-{incident_id}", [])
    errors = validate_plan(updated, plan) if plan.status != "NO_ACTION" else []
    return {
        "label": "ERP snapshot without shipment-message interpretation",
        "plan_status": plan.status,
        "allocations": [a.model_dump() for a in plan.allocations],
        "cost_paise": plan.total_cost_paise,
        "feasible_after_updates": not errors,
        "invalid_reasons": errors,
        "scope": "Recomputed comparison on this incident's original inventory and options. This is not an industry benchmark or a measured human baseline.",
    }
