"""Set RESILIENTOPS_TEST_POSTGRES_URL to a disposable database for integration tests."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from resilientops.config import Settings
from resilientops.migrate_postgres import migrate
from resilientops.storage import Store, _LedgerRow, _PostgresConnection, dumps


def test_postgres_config_and_cloud_run_guard(tmp_path, monkeypatch):
    config = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "local.db",
        database_url="postgresql://user:secret@localhost/ledger",
    )
    assert config.database_target == config.database_url
    assert config.database_url not in repr(config)
    monkeypatch.setenv("K_SERVICE", "resilientops")
    config.validate()
    with pytest.raises(ValueError, match="ephemeral SQLite"):
        replace(config, database_url="").validate()


def test_bound_parameters_and_row_access():
    from unittest.mock import Mock

    raw = Mock()
    connection = _PostgresConnection(raw)
    value = "quote'; SELECT ?; --"
    connection.execute("SELECT payload FROM incidents WHERE id=?", (value,))
    raw.execute.assert_called_once_with("SELECT payload FROM incidents WHERE id=%s", (value,))
    row = _LedgerRow(id="a", payload="{}")
    assert row[0] == row["id"] == "a"
    assert dict(row) == {"id": "a", "payload": "{}"}


@pytest.fixture
def postgres_url():
    url = os.getenv("RESILIENTOPS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL URL not configured")
    import psycopg

    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(f'CREATE SCHEMA "{schema}"')
    # Store expects URI: use a URI option for schema isolation.
    from urllib.parse import quote

    scoped = url + ("&" if "?" in url else "?") + "options=" + quote(f"-c search_path={schema}")
    # Store's explicit options must preserve the test search path.
    try:
        yield scoped
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_postgres_rollback_concurrency_and_migration(postgres_url, tmp_path):
    source = Store(tmp_path / "source.db")
    with source.transaction() as db:
        db.execute(
            "INSERT INTO incidents VALUES (?, ?, ?)",
            ("i", "e", dumps({"id": "i", "created_at": "2026-10-18", "count": 0})),
        )
        source.trace(db, "i", "System", "created", {})
    target = Store(postgres_url)
    assert migrate(source.path, target)["incidents"] == 1
    with pytest.raises(ValueError, match="not empty"):
        migrate(source.path, target)
    with pytest.raises(RuntimeError):
        with target.transaction() as db:
            incident = target.get("i", db)
            incident["count"] = 99
            target.save(db, incident)
            raise RuntimeError("rollback")
    assert target.get("i")["count"] == 0

    def increment(_):
        with target.transaction() as db:
            incident = target.get("i", db)
            incident["count"] += 1
            target.save(db, incident)
            target.trace(db, "i", "System", "increment", {})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment, range(12)))
    assert Store(postgres_url).get("i")["count"] == 12
    assert len(target.events("i")) == 13
    assert target.events("i")[-1]["seq"] > 1
    assert target.list()[0]["id"] == "i"


def test_postgres_complete_workflow_and_duplicate_release(postgres_url, tmp_path):
    import asyncio
    from pathlib import Path

    from resilientops.models import Decision, Principal
    from resilientops.services.execution import ActionService
    from resilientops.services.workflow import Workflow

    config = Settings(
        data_dir=Path(__file__).resolve().parents[1] / "data" / "demo",
        db_path=tmp_path / "unused.db",
        database_url=postgres_url,
    )
    workflow = Workflow(config, Store(config.database_target))
    incident = asyncio.run(workflow.analyze(workflow.create()["id"]))
    assert incident["status"] == "AWAITING_APPROVAL"
    actor = Principal(id="test-manager", role="manager")
    actions = ActionService(Store(postgres_url))
    actions.decide(
        incident["id"], Decision(plan_hash=incident["plan_hash"], decision="APPROVE"), actor
    )

    def release(_):
        return actions.execute(incident["id"], incident["plan_hash"], actor)["id"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(release, range(3)))
    assert len(set(ids)) == 1
    assert actions.receive_simulated_delivery(incident["id"], actor)["status"] == "RESOLVED"
    assert Store(postgres_url).get(incident["id"])["status"] == "RESOLVED"
