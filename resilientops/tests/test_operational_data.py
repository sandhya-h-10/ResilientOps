import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilientops.adapters.operational import OperationalData, load_dataset
from resilientops.analytics.impact import calculate_impact
from resilientops.analytics.optimization import optimize
from resilientops.api import create_app
from resilientops.config import Settings
from resilientops.models import Dataset, DomainError
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"


def test_operational_inventory_and_projection_reconcile():
    source = OperationalData(ROOT)
    dataset = source.snapshot()
    assert len(dataset.inventories) == 90
    assert len(dataset.documents) == 29
    assert dataset.event.plant_id == "PLT_MUM"
    assert dataset.event.material_id == "MAT_001_A"
    assert dataset.event.planning_start.isoformat() == source.manifest["decision_date"]
    assert sum(item.on_hand for item in dataset.inventories) == sum(
        row["physical_qty"] for row in source.rows("inventory_balances")
    )
    balance = next(
        i.available
        for i in dataset.inventories
        if i.plant_id == "PLT_MUM" and i.material_id == "MAT_001_A"
    )
    projections = sorted(
        (
            r
            for r in source.rows("inventory_projection_daily")
            if r["plant_id"] == "PLT_MUM" and r["material_revision_id"] == "MAT_001_A"
        ),
        key=lambda r: r["local_date"],
    )
    for day, row in enumerate(projections, 1):
        balance += dataset.receipt_on(day) - dataset.daily_demand[day - 1]
        assert balance == row["projected_physical_qty"]
    assert calculate_impact(dataset)["shortage_units"] == 0


@pytest.mark.parametrize(
    "scenario,peak,first", [("SCN_001", 110, 5), ("SCN_002", 270, 13), ("SCN_003", 110, 21)]
)
def test_independent_delays_change_timing_not_total_supply(scenario, peak, first):
    source = OperationalData(ROOT)
    before = (ROOT / "manifest.json").read_bytes()
    base, delayed = source.snapshot(), source.snapshot(scenario)
    assert delayed.daily_demand == base.daily_demand
    assert delayed.inventories == base.inventories
    assert sum(delayed.scheduled_receipts) == sum(base.scheduled_receipts)
    impact = calculate_impact(delayed)
    assert impact["shortage_units"] == peak
    assert impact["first_shortage_day"] == first
    assert impact["simulation"]["available"] is False
    plan, _ = optimize(delayed, "test", [])
    assert plan.status == "OPTIMAL"
    assert sum(a.quantity for a in plan.allocations) == peak
    assert all(a.quantity % 10 == 0 for a in plan.allocations)
    assert plan.total_cost_paise == peak * 12000
    assert (ROOT / "manifest.json").read_bytes() == before
    assert source.snapshot().scheduled_receipts == base.scheduled_receipts


def test_operational_api_workflow_and_unsupported_scenarios(tmp_path):
    settings = Settings(data_dir=ROOT, db_path=tmp_path / "operational.db")
    app = create_app(settings)
    with TestClient(app) as client:
        summary = client.get("/api/data/summary").json()
        assert summary["dataset"] == "resilientops_data"
        assert summary["row_count"] == 292016
        assert summary["reference_sources"]["weather_observations"] == 3911
        assert client.get("/api/data/references/curated_news?limit=1").json()["total"] == 16
        assert client.get("/api/data/references/unknown").status_code == 404
        assert len(client.get("/api/scenarios").json()) == 37
        assert client.get("/api/data/tables/plants?limit=2").json()["total"] == 3
        assert client.get("/api/data/tables/not-a-table").status_code == 404
        assert client.get("/api/data/tables/plants?limit=999").status_code == 422
        assert (
            client.get("/api/data/documents/POL_002").json()["title"]
            == "Transfer and spending authorization policy"
        )
        assert client.get("/api/evaluation").json()["available"] is False
        assert client.get("/evaluation").status_code == 404
        for scenario in summary["scenarios"]:
            if not scenario["supported"]:
                assert (
                    client.post("/api/incidents", json={"scenario_id": scenario["id"]}).status_code
                    == 422
                )
    workflow = app.state.workflow
    for scenario, expected in [("baseline", "RESOLVED"), ("SCN_001", "AWAITING_APPROVAL")]:
        incident = workflow.create(scenario)
        asyncio.run(workflow.analyze(incident["id"]))
        result = workflow.store.get(incident["id"])
        assert result["status"] == expected, result["error"]
        assert len(result["results"]) == 5


def test_legacy_ledger_is_not_mixed_with_new_data(make_workflow):
    legacy = make_workflow()
    with pytest.raises(DomainError, match="different dataset"):
        Workflow(replace(legacy.settings, data_dir=ROOT), Store(legacy.settings.db_path))


def test_defaults_and_scheduled_receipts_validation(monkeypatch):
    monkeypatch.delenv("RESILIENTOPS_DATA_DIR", raising=False)
    monkeypatch.delenv("RESILIENTOPS_DB", raising=False)
    settings = Settings.from_env()
    assert settings.data_dir == ROOT
    assert settings.db_path.name == "operational.db"
    dataset = load_dataset(ROOT)
    malformed = dataset.model_dump()
    malformed["scheduled_receipts"] = [-1]
    with pytest.raises(ValueError, match="Scheduled receipts"):
        Dataset.model_validate(malformed)
    assert json.loads((ROOT / "manifest.json").read_text())["decision_date"] == "2026-10-01"
