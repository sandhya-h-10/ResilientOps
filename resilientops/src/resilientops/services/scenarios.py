"""Named synthetic demonstrations; evaluation labels live in a separate directory."""

import json

from resilientops.adapters.operational import OperationalData, is_operational
from resilientops.models import Dataset, DomainError


def catalog(data_dir):
    if is_operational(data_dir):
        return OperationalData(data_dir).catalog()
    path = data_dir.parent / "scenarios" / "catalog.json"
    if not path.exists():
        return [
            {
                "id": "baseline",
                "title": "Original disruption",
                "description": "Structured ERP snapshot; no shipment messages.",
            }
        ]
    return json.loads(path.read_text())


def scenario_dataset(base, spec):
    data = base.model_dump(mode="json")
    if spec["id"] != "baseline":
        data["event"]["id"] = f"DEMO-{spec['id']}"
    data["updates"] = spec.get("updates", [])
    removed = spec.get("remove_documents", [])
    data["documents"] = [d for d in data["documents"] if d["id"] not in removed]
    if "daily_demand" in spec:
        data["daily_demand"] = spec["daily_demand"]
    return Dataset.model_validate(data)


def load_scenario(base, data_dir, scenario_id):
    if is_operational(data_dir):
        data = OperationalData(data_dir)
        snapshot = data.snapshot(scenario_id)
        title = next(s["title"] for s in data.catalog() if s["id"] == scenario_id)
        return snapshot, title
    if scenario_id == "baseline":
        return base.model_copy(deep=True), "Original disruption"
    spec = next((s for s in catalog(data_dir) if s["id"] == scenario_id), None)
    if spec is None:
        raise DomainError("Unknown demonstration scenario", 404)
    return scenario_dataset(base, spec), spec["title"]
