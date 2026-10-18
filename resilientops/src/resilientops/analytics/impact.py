from collections import deque

import numpy as np

from resilientops.models import Dataset


def downstream(edges: list[tuple[str, str]], root: str) -> list[str]:
    graph: dict[str, list[str]] = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
    seen = {root}
    queue = deque([root])
    while queue:
        for child in graph.get(queue.popleft(), []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return sorted(seen - {root})


def calculate_impact(dataset: Dataset) -> dict:
    event = dataset.event
    inventory = next(
        i
        for i in dataset.inventories
        if i.plant_id == event.plant_id and i.material_id == event.material_id
    )
    available = inventory.available
    cumulative = 0
    scheduled = 0
    timeline = []
    for day, demand in enumerate(dataset.daily_demand, 1):
        cumulative += demand
        scheduled += dataset.receipt_on(day)
        timeline.append(
            {
                "day": day,
                "demand": demand,
                "cumulative_demand": cumulative,
                "scheduled_receipts": dataset.receipt_on(day),
                "cumulative_shortage": max(0, cumulative - available - scheduled),
            }
        )
    mean_demand = cumulative / event.planning_days
    shortage = max(row["cumulative_shortage"] for row in timeline)
    rng = np.random.default_rng(17)
    delays = rng.triangular(event.delay_min_days, event.delay_mode_days, event.delay_max_days, 1000)
    shortages = np.maximum(0, delays * mean_demand - available)
    exposed_orders = [
        row
        for row in dataset.source_metadata.get("related_orders", [])
        if timeline[row["required_day"] - 1]["cumulative_shortage"] > 0
    ]
    return {
        "available_units": available,
        "days_of_cover": round(available / mean_demand, 3) if mean_demand else None,
        "daily_demand": dataset.daily_demand,
        "shortage_units": shortage,
        "timeline": timeline,
        "first_shortage_day": next(
            (r["day"] for r in timeline if r["cumulative_shortage"] > 0), None
        ),
        "exposure_paise": None
        if dataset.source_metadata.get("dataset") == "resilientops_data"
        else shortage * dataset.unit_shortage_cost_paise,
        "order_exposure": {
            "orders": exposed_orders,
            "potential_order_value_paise": sum(
                r["allocated_order_value_paise"] or 0 for r in exposed_orders
            ),
            "scope": "Allocated order value related to shortage-day production; potential exposure, not lost sales or realized loss.",
        }
        if dataset.source_metadata.get("dataset") == "resilientops_data"
        else None,
        "affected_entities": downstream(dataset.edges, event.supplier_id),
        "simulation": {
            "available": False,
            "reason": "No calibrated delay distribution in operational data.",
        }
        if dataset.source_metadata.get("dataset") == "resilientops_data"
        else {
            "samples": 1000,
            "seed": 17,
            "stockout_probability_under_assumptions": round(float(np.mean(shortages > 0)), 4),
            "expected_shortage_units": round(float(np.mean(shortages)), 2),
            "p90_shortage_units": round(float(np.quantile(shortages, 0.9)), 2),
            "assumptions": "Synthetic triangular delay; constant mean consumption; no incoming supply during disruption. Not a calibrated forecast.",
        },
    }
