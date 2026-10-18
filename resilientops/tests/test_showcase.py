import asyncio
from pathlib import Path

import pytest

from resilientops.adapters.operational import OperationalData
from resilientops.config import Settings
from resilientops.services.diagram import DiagramWorkflow, DraftRequest, RevisionRequest
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"
EXPECTED = [
    "AWAITING_SELECTION",
    "AWAITING_SELECTION",
    "PLANNING_BLOCKED",
    "AWAITING_SELECTION",
    "PLANNING_BLOCKED",
    "AWAITING_CLOSURE",
    "PLANNING_BLOCKED",
    "PLANNING_BLOCKED",
    "AWAITING_SELECTION",
    "ESCALATED",
    "PLANNING_BLOCKED",
    "PLANNING_BLOCKED",
]


def test_showcase_is_additive_and_diverse():
    source = OperationalData(ROOT)
    baseline = source.snapshot()
    assert len(source.showcase) == 24
    assert len({c.plant for c in source.showcase}) == 3
    assert len({c.material for c in source.showcase}) == 4
    original = {
        p: p.read_bytes()
        for p in [
            ROOT / "manifest.json",
            ROOT / "data/scenarios.jsonl",
            ROOT / "data/scenario_changes.jsonl",
        ]
    }
    for case in source.showcase:
        snapshot = source.snapshot(case.id)
        assert snapshot.inventories == baseline.inventories
        assert snapshot.event.plant_id == case.plant
        assert snapshot.event.material_id == case.material
    assert source.snapshot() == baseline
    assert all(p.read_bytes() == contents for p, contents in original.items())


@pytest.mark.parametrize("number,status", list(enumerate(EXPECTED, 1)))
def test_showcase_decision_outcomes(number, status, tmp_path):
    settings = Settings(data_dir=ROOT, db_path=tmp_path / "showcase.db")
    workflow = Workflow(settings, Store(settings.db_path))
    diagram = DiagramWorkflow(workflow)
    incident = diagram.create(
        DraftRequest(
            title="Showcase test",
            description="Synthetic validation",
            scenario_id=f"SHOW_{number:03}",
        ),
        "test",
    )
    diagram.assess(incident["id"], RevisionRequest(revision=1), "test")
    result = asyncio.run(workflow.analyze(incident["id"]))
    assert result["status"] == status, result.get("error")
    assert not result.get("action_id")
