"""Export validated demo tables as JSONL. Does not contact Google Cloud."""

import json
from pathlib import Path

from resilientops.adapters.operational import load_dataset
from resilientops.config import Settings

root = Path(__file__).resolve().parents[1]
dataset = load_dataset(Settings.from_env().data_dir)
output = root / "var/bigquery"
output.mkdir(parents=True, exist_ok=True)
tables = {
    "inventory": [item.model_dump() for item in dataset.inventories],
    "recovery_options": [item.model_dump() for item in dataset.options],
    "demand": [
        {"day": day, "quantity": quantity, "scheduled_receipts": dataset.receipt_on(day)}
        for day, quantity in enumerate(dataset.daily_demand, 1)
    ],
    "supplier_history": [
        dict(zip(["otif", "lead_days", "defect_rate", "delay_days"], row, strict=True))
        | {"period": period}
        for period, row in enumerate(dataset.supplier_history, 1)
    ],
    "dependencies": [{"source": source, "target": target} for source, target in dataset.edges],
}
for table, rows in tables.items():
    path = output / f"{table}.jsonl"
    path.write_text(
        "".join(json.dumps({"scenario_id": dataset.event.id, **row}) + "\n" for row in rows)
    )
print(f"Exported {len(tables)} tables to {output}")
