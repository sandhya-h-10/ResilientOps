import json
from collections import defaultdict

from resilientops.analytics.optimization import eligibility
from resilientops.models import Dataset, DomainError, Plan, Principal
from resilientops.storage import fingerprint

POLICY_VERSION = "DEMO-POLICY-1"
MANAGER_LIMIT_PAISE = 500_000 * 100


def required_role(plan: Plan) -> str:
    if plan.approval_policy == "OPS-SIMULATION-1":
        # Operational purchases require a senior reviewer under the explicit
        # application simulation policy; POL_002's transfer limit is inclusive.
        if any(a.option_id.startswith("SRC_") for a in plan.allocations):
            return "senior"
        return "senior" if plan.total_cost_paise >= MANAGER_LIMIT_PAISE else "manager"
    return "senior" if plan.total_cost_paise > MANAGER_LIMIT_PAISE else "manager"


def authorize(principal: Principal, plan: Plan):
    if required_role(plan) == "senior" and principal.role != "senior":
        raise DomainError("This plan requires a senior approver", 403)


def validate_plan(dataset: Dataset, plan: Plan) -> list[str]:
    errors = []
    if plan.status not in {"OPTIMAL", "FEASIBLE"}:
        return ["Plan has no executable feasible recovery"]
    if len({a.option_id for a in plan.allocations}) != len(plan.allocations):
        errors.append("Duplicate allocation IDs")
    eligible, _ = eligibility(dataset)
    options = {o.id: o for o in eligible}
    source_totals: dict[tuple[str, str], int] = defaultdict(int)
    arrivals: dict[int, int] = defaultdict(int)
    calculated_cost = 0
    groups = defaultdict(int)
    for allocation in plan.allocations:
        option = options.get(allocation.option_id)
        if option is None:
            errors.append(f"Ineligible or unknown option: {allocation.option_id}")
            continue
        if allocation.quantity > option.capacity:
            errors.append(f"Capacity exceeded: {option.id}")
        if (
            allocation.quantity < option.minimum_order_qty
            or allocation.quantity % option.order_multiple
        ):
            errors.append(f"Order minimum/multiple violated: {option.id}")
        if option.capacity_group:
            groups[option.capacity_group] += allocation.quantity
        calculated_cost += allocation.quantity * option.unit_cost_paise + option.fixed_cost_paise
        arrivals[option.arrival_day] += allocation.quantity
        if option.action_type == "TRANSFER":
            if option.source_id == option.destination:
                errors.append("Transfer source and destination are identical")
            source_totals[(option.source_id, option.material_id)] += allocation.quantity
    inventory = {(i.plant_id, i.material_id): i for i in dataset.inventories}
    for key, quantity in source_totals.items():
        if key not in inventory or quantity > inventory[key].transferable:
            errors.append(f"Insufficient source inventory after safety stock: {key[0]}")
    if calculated_cost != plan.total_cost_paise:
        errors.append("Plan cost does not match authoritative option costs")
    if dataset.max_cost_paise is not None and calculated_cost > dataset.max_cost_paise:
        errors.append("Planner budget exceeded")
    for group, quantity in groups.items():
        if quantity > min(o.capacity for o in options.values() if o.capacity_group == group):
            errors.append(f"Shared capacity exceeded: {group}")
    balance = inventory[(dataset.event.plant_id, dataset.event.material_id)].available
    for day, demand in enumerate(dataset.daily_demand, 1):
        balance += dataset.receipt_on(day) + arrivals[day] - demand
        if balance < 0:
            errors.append(f"Uncovered demand on day {day}")
    return errors


def capacity_commitments(db, dataset):
    """Track only reservations consuming this snapshot's supplier capacity pools."""
    keys = {o.capacity_group or o.id for o in dataset.options if o.action_type != "TRANSFER"}
    used = dict.fromkeys(sorted(keys), 0)
    for row in db.execute("SELECT payload FROM actions"):
        action = json.loads(row[0])
        for item in action["allocations"]:
            key = item["option"].get("capacity_group") or item["option_id"]
            if key in used:
                used[key] += (
                    item.get("received_units", 0)
                    if action["status"] == "CANCELLED"
                    else item["quantity"]
                )
    return used


def current_plan_errors(store, db, dataset, plan):
    errors = []
    if fingerprint(dataset.model_dump(mode="json")) != plan.snapshot_hash:
        errors.append("Planning data or constraints changed; refresh recovery plans")
    options = {o.id: o for o in dataset.options}
    relevant = {(dataset.event.plant_id, dataset.event.material_id)}
    for allocation in plan.allocations:
        option = options.get(allocation.option_id)
        if option and option.action_type == "TRANSFER":
            relevant.add((option.source_id, option.material_id))
    original = {(i.plant_id, i.material_id): i.model_dump() for i in dataset.inventories}
    current = {(i.plant_id, i.material_id): i.model_dump() for i in store.inventories(db)}
    if any(original.get(key) != current.get(key) for key in relevant):
        errors.append("Relevant inventory changed; refresh recovery plans")
    current_capacity = capacity_commitments(db, dataset)
    recorded = dataset.source_metadata.get("capacity_commitments", {})
    if any(value != recorded.get(key, 0) for key, value in current_capacity.items()):
        errors.append("Supplier capacity commitments changed; refresh recovery plans")
    return errors
