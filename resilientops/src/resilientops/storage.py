"""Transactional incident ledger for SQLite locally and Cloud SQL PostgreSQL."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from resilientops.models import Dataset, DomainError, Inventory, utcnow


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Store:
    def __init__(self, path: Path | str):
        self.postgres = isinstance(path, str) and path.startswith(("postgresql://", "postgres://"))
        self.path = path if self.postgres else Path(path)
        if not self.postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if self.postgres:
                # Serialize schema initialization across API and MCP processes.
                db.execute("SELECT pg_advisory_xact_lock(726031825)")
            else:
                db.execute("PRAGMA journal_mode=WAL")
            sequence = (
                "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
            for statement in (
                "CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)",
                f"CREATE TABLE IF NOT EXISTS trace (seq {sequence}, incident_id TEXT NOT NULL, agent TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS inventory (plant_id TEXT NOT NULL, material_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (plant_id, material_id))",
                "CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, plan_hash TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS trace_incident_seq ON trace (incident_id, seq)",
            ):
                db.execute(statement)

    @contextmanager
    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict

            options = conninfo_to_dict(self.path).get("options", "")
            with psycopg.connect(
                self.path,
                connect_timeout=10,
                row_factory=_postgres_row,
                options=options + " -c lock_timeout=10000 -c statement_timeout=30000",
            ) as connection:
                yield _PostgresConnection(connection)
            return
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            if self.postgres:
                # Preserve BEGIN IMMEDIATE's global write serialization across
                # workers: plans reserve shared inventory and supplier capacity.
                # Only short ledger operations hold this lock, never LLM calls.
                db.execute("SELECT pg_advisory_xact_lock(726031825)")
            else:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def seed(self, dataset: Dataset):
        with self.transaction() as db:
            existing = {
                (r[0], r[1]) for r in db.execute("SELECT plant_id, material_id FROM inventory")
            }
            incoming = {(item.plant_id, item.material_id) for item in dataset.inventories}
            if existing and existing != incoming:
                raise DomainError(
                    "Ledger belongs to a different dataset; configure a separate RESILIENTOPS_DB"
                )
            for item in dataset.inventories:
                db.execute(
                    "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT (plant_id, material_id) DO NOTHING",
                    (item.plant_id, item.material_id, item.model_dump_json()),
                )

    def inventories(self, db=None) -> list[Inventory]:
        if db is None:
            with self.connect() as connection:
                return self.inventories(connection)
        return [
            Inventory.model_validate_json(r[0]) for r in db.execute("SELECT payload FROM inventory")
        ]

    def put_inventory(self, db, item: Inventory):
        db.execute(
            "UPDATE inventory SET payload=? WHERE plant_id=? AND material_id=?",
            (item.model_dump_json(), item.plant_id, item.material_id),
        )

    def get(self, incident_id: str, db=None) -> dict:
        if db is None:
            with self.connect() as connection:
                return self.get(incident_id, connection)
        row = db.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise DomainError("Incident not found", 404)
        return json.loads(row[0])

    def save(self, db, incident: dict):
        incident["updated_at"] = utcnow().isoformat()
        db.execute("UPDATE incidents SET payload=? WHERE id=?", (dumps(incident), incident["id"]))

    def list(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM incidents ORDER BY payload::jsonb->>'created_at' DESC, id DESC"
                    if self.postgres
                    else "SELECT payload FROM incidents ORDER BY rowid DESC"
                )
            ]

    def trace(self, db, incident_id: str, agent: str, kind: str, detail: dict):
        db.execute(
            "INSERT INTO trace (incident_id, agent, kind, detail, at) VALUES (?, ?, ?, ?, ?)",
            (incident_id, agent, kind, dumps(detail), utcnow().isoformat()),
        )

    def events(self, incident_id: str, after: int = 0):
        self.get(incident_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM trace WHERE incident_id=? AND seq>? ORDER BY seq",
                (incident_id, after),
            ).fetchall()
            return [dict(row) | {"detail": json.loads(row["detail"])} for row in rows]


class _LedgerRow(dict):
    """The ledger's existing callers use both ordinal and named column access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _postgres_row(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: _LedgerRow(zip(names, values, strict=True))


class _PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        # Ledger SQL is internal and uses qmark placeholders, never user SQL.
        # Values remain driver-bound parameters; no value interpolation.
        return self.connection.execute(sql.replace("?", "%s"), parameters)
