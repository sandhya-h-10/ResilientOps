"""Rebuild the deterministic, synthetic judging demo pack without changing base data."""

import json
from pathlib import Path

from resilientops.adapters.operational import OperationalData

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"
SPECS = [
    (
        "Mumbai inbound delay",
        "PLT_MUM",
        "MAT_001_A",
        "SHIP_00144",
        2,
        "Inbound logistics",
        "A synthetic carrier notice delays the inbound material shipment by two days. Compare qualified recovery sources and explain the first shortage day.",
    ),
    (
        "Tokyo customs clearance delay",
        "PLT_TYO",
        "MAT_002_A",
        "SHIP_04113",
        5,
        "Customs & timing",
        "A synthetic customs-clearance hold is modeled as a five-day inbound shipment delay. The cause is a demonstration narrative, not a live customs event.",
    ),
    (
        "Beijing component delivery interruption",
        "PLT_BJS",
        "MAT_003_A",
        "SHIP_08082",
        4,
        "Supplier delivery",
        "A synthetic supplier dispatch interruption delays the shipment by four days. Compare local timing and the related customer-order exposure.",
    ),
    (
        "Mumbai extended route disruption",
        "PLT_MUM",
        "MAT_004_A",
        "SHIP_00585",
        9,
        "Extended disruption",
        "A synthetic logistics disruption postpones one shipment by nine days. Show why more severe delay can increase uncovered demand; do not infer closure of other routes.",
    ),
    (
        "Tokyo short delay",
        "PLT_TYO",
        "MAT_001_A",
        "SHIP_03966",
        1,
        "Early warning",
        "A one-day synthetic shipment delay tests whether available stock and dated receipts cover demand. Recommend action only if the calculation warrants it.",
    ),
    (
        "Beijing no-disruption control",
        "PLT_BJS",
        "MAT_002_A",
        "SHIP_07935",
        0,
        "Control case",
        "A zero-delay control case tests that the system does not manufacture a disruption or recommend unnecessary procurement.",
    ),
    (
        "Mumbai budget-constrained recovery",
        "PLT_MUM",
        "MAT_001_A",
        "SHIP_00144",
        5,
        "Budget trade-off",
        "A five-day synthetic delay with a zero additional-spend ceiling. Demonstrate blocked planning and revising constraints instead of inventing an affordable plan.",
    ),
    (
        "Tokyo deadline-constrained recovery",
        "PLT_TYO",
        "MAT_003_A",
        "SHIP_04260",
        6,
        "Feasibility boundary",
        "A six-day synthetic delay with recovery required by planning day 2. Show whether qualified supply can meet the deadline and explain infeasibility when it cannot.",
    ),
    (
        "Beijing prolonged inbound delay",
        "PLT_BJS",
        "MAT_004_A",
        "SHIP_08229",
        8,
        "Regional comparison",
        "An eight-day synthetic inbound delay on a different material and plant. Compare affected orders, qualified sources and INR-normalized purchase estimates.",
    ),
    (
        "Mumbai conflicting supplier messages",
        "PLT_MUM",
        "MAT_001_A",
        "SHIP_00144",
        3,
        "Evidence conflict",
        "Two synthetic reports disagree about the same recovery booking arrival. The Investigator must surface the conflict rather than silently choose the newer message.",
    ),
    (
        "Tokyo corrected supplier confirmation",
        "PLT_TYO",
        "MAT_002_A",
        "SHIP_04113",
        3,
        "Evidence correction",
        "A synthetic correction explicitly supersedes an earlier report for a recovery booking. Demonstrate cited evidence reconciliation and explain the revised arrival.",
    ),
    (
        "Beijing limited recovery availability",
        "PLT_BJS",
        "MAT_003_A",
        "SHIP_08082",
        5,
        "Capacity trade-off",
        "A synthetic supplier message confirms only 10 units for one recovery source. Recalculate options from the bounded availability; never assume other sources share the reduction.",
    ),
]


def build():
    source = OperationalData(ROOT)
    cases = []
    for n, (title, plant, material, shipment, delay, category, description) in enumerate(SPECS, 1):
        case = {
            "id": f"SHOW_{n:03}",
            "title": title,
            "description": description,
            "plant": plant,
            "material": material,
            "shipment_id": shipment,
            "delay_days": delay,
            "category": category,
            "questions": [
                "What is at risk, and which evidence supports it?",
                "What should I do next, and what assumptions should I review?",
            ],
            "demonstrates": ["Problem alignment & impact", "User experience & solution design"],
        }
        if n == 7:
            case["max_cost_paise"] = 0
        if n == 8:
            case["latest_arrival_day"] = 2
        if n in (10, 11, 12):
            option = next(
                o for o in source.recovery_options(plant, material) if o.approved and o.route_open
            )

            def msg(suffix, day, qty, supersedes=None, n=n, option=option):
                return {
                    "id": f"SHOW_{n:03}_{suffix}",
                    "source_label": "Synthetic supplier confirmation",
                    "text": f"Booking {option.id}. Confirmed arrival: 2026-10-{day:02}. Available: {qty} units.",
                    "received_at": f"2026-10-01T0{1 if suffix == 'A' else 2}:00:00Z",
                    "supersedes": supersedes or [],
                }

            day = max(option.arrival_day, 6)
            qty = min(option.capacity, 300)
            if n == 10:
                case["updates"] = [msg("A", day, qty), msg("B", day + 2, qty)]
            if n == 11:
                case["updates"] = [msg("A", day + 2, qty), msg("B", day, qty, [f"SHOW_{n:03}_A"])]
            if n == 12:
                case["updates"] = [msg("A", day, 10)]
            case["demonstrates"] += [
                "Technical merit & Gen AI implementation",
                "Innovation in evidence reconciliation",
            ]
            case["questions"].insert(
                0,
                "Explain the supplier messages, conflicts or corrections and their effect on recovery options.",
            )
        cases.append(case)
    target = ROOT / "showcase"
    target.mkdir(exist_ok=True)
    (target / "scenarios.json").write_text(
        json.dumps(
            {
                "version": "showcase-v1",
                "synthetic": True,
                "base_dataset_version": source.manifest["dataset_version"],
                "scenarios": cases,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {len(cases)} synthetic cases across three plants and four material revisions.")


if __name__ == "__main__":
    build()
