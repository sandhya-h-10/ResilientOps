"""Integer recovery allocation with cumulative daily supply constraints."""

from ortools.linear_solver import pywraplp

from resilientops.models import Allocation, Dataset, Plan
from resilientops.storage import fingerprint


def eligibility(dataset: Dataset) -> tuple[list, dict[str, str]]:
    eligible, excluded = [], {}
    event = dataset.event
    for option in dataset.options:
        reason = None
        if option.id in dataset.excluded_option_ids:
            reason = "Excluded by planner constraint"
        elif dataset.latest_arrival_day and option.arrival_day > dataset.latest_arrival_day:
            reason = "Later than planner arrival deadline"
        elif option.material_id != event.material_id or option.destination != event.plant_id:
            reason = "Wrong material or destination"
        elif not option.approved:
            reason = "Supplier/route is not approved"
        elif not option.compatible or not option.route_open:
            reason = "Incompatible material or closed route"
        elif option.capacity == 0:
            reason = "No available capacity"
        elif option.action_type == "TRANSFER" and not any(
            i.plant_id == option.source_id
            and i.material_id == option.material_id
            and i.transferable > 0
            for i in dataset.inventories
        ):
            reason = "Source inventory is missing or has no transferable stock"
        if reason:
            excluded[option.id] = reason
        else:
            eligible.append(option)
    return eligible, excluded


def optimize(
    dataset: Dataset, incident_id: str, evidence_ids: list[str], version: int = 1
) -> tuple[Plan, dict]:
    event = dataset.event
    inventory = next(
        i
        for i in dataset.inventories
        if i.plant_id == event.plant_id and i.material_id == event.material_id
    )
    eligible, excluded = eligibility(dataset)
    common = dict(
        id=f"PLAN-{incident_id}",
        version=version,
        evidence_ids=evidence_ids,
        snapshot_hash=fingerprint(dataset.model_dump(mode="json")),
        expires_at=None,
        solver="OR-Tools SCIP MILP",
        approval_policy="OPS-SIMULATION-1"
        if dataset.source_metadata.get("dataset") == "resilientops_data"
        else "DEMO-POLICY-1",
        assumptions=[
            "Arrivals occur before consumption on their scheduled day.",
            "Demand and capacities are synthetic planning inputs.",
            "All material units are integers; money is INR paise.",
            "Scheduled incoming supply is included where provided; it is assumed, not confirmed.",
        ],
    )
    balance = inventory.available
    covered = True
    for day, demand in enumerate(dataset.daily_demand, 1):
        balance += dataset.receipt_on(day) - demand
        covered = covered and balance >= 0
    if covered:
        return Plan(**common, status="NO_ACTION", allocations=[], total_cost_paise=0), excluded
    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        raise RuntimeError("OR-Tools SCIP solver is unavailable")
    solver.SetTimeLimit(5000)
    amounts, selected = {}, {}
    for option in eligible:
        amounts[option.id] = solver.IntVar(0, option.capacity, f"quantity_{option.id}")
        selected[option.id] = solver.BoolVar(f"selected_{option.id}")
        packs = solver.IntVar(0, option.capacity // option.order_multiple, f"packs_{option.id}")
        solver.Add(amounts[option.id] == packs * option.order_multiple)
        solver.Add(amounts[option.id] <= option.capacity * selected[option.id])
        solver.Add(amounts[option.id] >= option.minimum_order_qty * selected[option.id])
    for group in {o.capacity_group for o in eligible if o.capacity_group}:
        members = [o for o in eligible if o.capacity_group == group]
        solver.Add(solver.Sum([amounts[o.id] for o in members]) <= min(o.capacity for o in members))
    # Multiple routes from one plant cannot each consume its full transferable balance.
    for source in dataset.inventories:
        transfers = [
            o
            for o in eligible
            if o.action_type == "TRANSFER"
            and o.source_id == source.plant_id
            and o.material_id == source.material_id
        ]
        if transfers:
            solver.Add(solver.Sum([amounts[o.id] for o in transfers]) <= source.transferable)
    cumulative = 0
    scheduled = 0
    for day, demand in enumerate(dataset.daily_demand, 1):
        cumulative += demand
        scheduled += dataset.receipt_on(day)
        arrivals = [amounts[o.id] for o in eligible if o.arrival_day <= day]
        solver.Add(inventory.available + scheduled + solver.Sum(arrivals) >= cumulative)
    total_cost = solver.Sum(
        [amounts[o.id] * o.unit_cost_paise + selected[o.id] * o.fixed_cost_paise for o in eligible]
    )
    if dataset.max_cost_paise is not None:
        solver.Add(total_cost <= dataset.max_cost_paise)
    solver.Minimize(total_cost)
    result = solver.Solve()
    if result not in {pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE}:
        return Plan(**common, status="INFEASIBLE", allocations=[], total_cost_paise=0), excluded
    allocations = [
        Allocation(option_id=o.id, quantity=round(amounts[o.id].solution_value()))
        for o in eligible
        if amounts[o.id].solution_value() > 0.5
    ]
    by_id = {o.id: o for o in eligible}
    cost = sum(
        a.quantity * by_id[a.option_id].unit_cost_paise + by_id[a.option_id].fixed_cost_paise
        for a in allocations
    )
    status = "OPTIMAL" if result == pywraplp.Solver.OPTIMAL else "FEASIBLE"
    return Plan(**common, status=status, allocations=allocations, total_cost_paise=cost), excluded
