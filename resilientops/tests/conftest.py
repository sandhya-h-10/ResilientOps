import json
from pathlib import Path

import pytest

from resilientops.config import Settings
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data" / "demo" / "scenario.json"


@pytest.fixture
def make_workflow(tmp_path):
    count = 0

    def make(change=None, db_path=None):
        nonlocal count
        count += 1
        directory = tmp_path / f"scenario-{count}"
        directory.mkdir()
        data = json.loads(DATA.read_text())
        if change:
            change(data)
        (directory / "scenario.json").write_text(json.dumps(data))
        settings = Settings(
            data_dir=directory,
            db_path=db_path or directory / "state.db",
            manager_token="test-manager-token",
            senior_token="test-senior-token",
        )
        return Workflow(settings, Store(settings.db_path))

    return make
