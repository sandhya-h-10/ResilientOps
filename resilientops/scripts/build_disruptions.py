"""Reproducible synthetic detection histories; no operational export is overwritten."""

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"
SPECS = [
    ("external", "Political", "border clearance hours", "hours", 12, 4),
    ("external", "Economic", "import cost index", "index", 100, 1.8),
    ("external", "Environmental", "rainfall", "mm/day", 15, 7),
    ("external", "Technological", "port system outage", "minutes/day", 10, 15),
    ("external", "Social", "transport absence", "percent", 5, 6),
    ("external", "Legal", "compliance clearance hours", "hours", 8, 5),
    ("internal", "Equipment", "receiving equipment downtime", "minutes/day", 12, 9),
    ("internal", "Quality", "incoming inspection rejection", "percent", 2, 10),
    ("internal", "Workforce", "receiving team absence", "percent", 4, 7),
    ("market", "Supplier", "supplier lead time", "days", 5, 3),
    ("market", "Demand", "daily demand index", "index", 100, 1.8),
    ("market", "Control", "daily demand index", "index", 100, 1.02),
]
CONTEXTS = [
    ("PLT_MUM", "MAT_001_A", "SHIP_00144"),
    ("PLT_TYO", "MAT_002_A", "SHIP_04113"),
    ("PLT_BJS", "MAT_003_A", "SHIP_08082"),
]


def build():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    start = date.fromisoformat(manifest["decision_date"])
    scenarios, signals, labels = [], [], []
    for n, (family, subtype, metric, unit, mean, factor) in enumerate(SPECS, 1):
        sid = f"RISK_{n:03}"
        plant, material, shipment = CONTEXTS[(n - 1) % 3]
        rng = random.Random(42100 + n)
        observations = [
            {
                "day": str(start - timedelta(days=61 - k)),
                "value": round(max(0.01, rng.gauss(mean, mean * 0.06)), 3),
            }
            for k in range(60)
        ]
        observations.append({"day": str(start - timedelta(days=1)), "value": round(mean * factor, 3)})
        effect = (
            "Aggregate demand is increased by 40%; no extra customer-order value is invented."
            if subtype == "Demand"
            else "No disruption overlay is applied."
            if subtype == "Control"
            else "A planner-supplied three-day receipt delay models the material availability consequence; the root cause is not inferred from the outlier."
        )
        narrative = f"Synthetic {family} / {subtype.lower()} monitoring case at {plant} for {material}. {metric} is {mean * factor:g} {unit}, compared with a historical baseline around {mean:g}. {effect} This is an illustrative source notice, not a live or verified event."
        scenarios.append(
            {
                "id": sid,
                "title": f"{subtype} disruption - {plant}",
                "description": narrative,
                "plant": plant,
                "material": material,
                "shipment_id": shipment,
                "delay_days": 0 if subtype in {"Demand", "Control"} else 3,
                "demand_multiplier": 1.4 if subtype == "Demand" else 1,
                "category": f"{family.title()} / {subtype}",
                "questions": [
                    "Which signals are anomalous and what is the historical baseline?",
                    "What evidence links this signal to the incident, and what remains uncertain?",
                ],
                "demonstrates": [
                    "Statistical monitoring",
                    "Grounded agent reasoning",
                    "Cross-domain disruptions",
                ],
            }
        )
        signals.append(
            {
                "id": f"SIGNAL_{n:03}",
                "scenario_id": sid,
                "family": family,
                "subtype": subtype.lower(),
                "plant": plant,
                "material": material,
                "metric": metric,
                "unit": unit,
                "direction": "high",
                "source_text": narrative,
                "synthetic": True,
                "observations": observations,
            }
        )
        labels.append({"scenario_id": sid, "expected_anomaly": subtype != "Control"})
    target = ROOT / "disruptions"
    target.mkdir(exist_ok=True)
    common = {"synthetic": True, "base_dataset_version": manifest["dataset_version"]}
    for filename, key, rows in [
        ("scenarios.json", "scenarios", scenarios),
        ("signals.json", "signals", signals),
        ("evaluation-labels.json", "labels", labels),
    ]:
        (target / filename).write_text(json.dumps(common | {key: rows}, indent=2) + "\n")
    print(
        f"Created {len(scenarios)} cases, {len(signals) * 61} dated observations, separate evaluation labels."
    )


if __name__ == "__main__":
    build()
