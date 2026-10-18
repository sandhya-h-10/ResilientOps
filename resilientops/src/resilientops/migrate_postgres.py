"""Copy a consistent SQLite snapshot into an empty PostgreSQL ledger.

Run with writers stopped. The source is opened read-only and is never modified.
Credentials come from RESILIENTOPS_DATABASE_URL, not command-line arguments.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from resilientops.storage import Store

TABLES = {
    "incidents": ("id", "event_id", "payload"),
    "inventory": ("plant_id", "material_id", "payload"),
    "actions": ("id", "incident_id", "plan_hash", "payload"),
    "trace": ("seq", "incident_id", "agent", "kind", "detail", "at"),
}


def migrate(source: Path, target: Store):
    if not target.postgres:
        raise ValueError("Migration target must be PostgreSQL")
    if not source.is_file():
        raise ValueError("SQLite source does not exist")
    counts = {}
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("BEGIN")
        with target.transaction() as db:
            for table in TABLES:
                if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                    raise ValueError("Target ledger is not empty; migration cancelled")
            for table, columns in TABLES.items():
                fields = ", ".join(columns)
                rows = original.execute(f"SELECT {fields} FROM {table}").fetchall()
                for row in rows:
                    db.execute(
                        f"INSERT INTO {table} ({fields}) VALUES ({', '.join('?' for _ in columns)})",
                        row,
                    )
                counts[table] = len(rows)
                copied = db.execute(f"SELECT {fields} FROM {table}").fetchall()
                if sorted(tuple(row) for row in rows) != sorted(
                    tuple(row[column] for column in columns) for row in copied
                ):
                    raise ValueError(f"Migration verification failed for {table}")
            db.execute(
                "SELECT setval(pg_get_serial_sequence('trace', 'seq'), "
                "COALESCE((SELECT MAX(seq) FROM trace), 1), "
                "EXISTS(SELECT 1 FROM trace))"
            )
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("RESILIENTOPS_DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgres://")):
        parser.error("Set RESILIENTOPS_DATABASE_URL to the destination PostgreSQL URL")
    try:
        counts = migrate(args.source, Store(url))
    except Exception:
        # Connection errors may contain host/user information; never print the URL.
        parser.exit(
            1,
            "Migration failed; verify connectivity and an empty target ledger. Source is unchanged.\n",
        )
    print(json.dumps({"verified_rows": counts}))


if __name__ == "__main__":
    main()
