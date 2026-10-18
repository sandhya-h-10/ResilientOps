# Cloud SQL PostgreSQL deployment

The API, execution service, audit history, inventory ledger and MCP agent tools use
the same PostgreSQL database through `RESILIENTOPS_DATABASE_URL`. The source
CSV/JSON datasets remain read-only application assets. SQLite is retained for
local offline tests; Cloud Run refuses to start without the PostgreSQL URL.

## Provision and connect

1. In project `project-bceae5b1-7549-4f14-922`, enable billing and the Cloud SQL
   Admin API. Create a PostgreSQL instance (17 or a supported newer version)
   in the Cloud Run service's region. Enable automated backups and point-in-time
   recovery. Create a dedicated database named `resilientops` and database user.
2. Grant the Cloud Run runtime service account `roles/cloudsql.client`.
   This grants connection permission, not database login privileges.
3. Attach the instance to the Cloud Run service with `--add-cloudsql-instances
   PROJECT:REGION:INSTANCE`. Use the second-generation execution environment.
4. Store the connection URL in Secret Manager, granting that runtime service
   account access only to the required secret. Map it to
   `RESILIENTOPS_DATABASE_URL`:
   `postgresql://USER:PASSWORD@/resilientops?host=/cloudsql/PROJECT:REGION:INSTANCE`.
   Percent-encode special characters in the username/password. Cloud Run's
   Cloud SQL socket uses the authenticated, encrypted proxy connection.
   Never put the URL in source control, logs, browser code, or a Docker image.
5. The database user needs permission to create tables/indexes/sequences in its
   dedicated schema, and to read/write those objects. The app initializes its
   four tables idempotently. Do not point at another application's schema.
6. Deploy the existing Dockerfile (port 8000) with the secret and instance
   attachment. There is no silent SQLite fallback if PostgreSQL is unavailable.

Official setup: https://docs.cloud.google.com/sql/docs/postgres/connect-run

## Preserve the current SQLite ledger

Stop the local server and all writers before copying; leave them stopped until
cutover completes. Back up `var/operational.db` with SQLite's backup facility.
For local access to Cloud SQL, run the Cloud SQL Auth Proxy on localhost and use
a PostgreSQL TCP URL pointing at that proxy. Load the URL securely into the
environment, then run from the project root:

```sh
.venv/bin/python -m resilientops.migrate_postgres --source var/operational.db
```

The command reads the source in a consistent read-only transaction, requires all
four destination tables to be empty, copies every field (including audit sequence
IDs), verifies the copied rows, and commits atomically. A failure rolls back the
copy; it never deletes source records or overwrites an existing destination.
Successful output contains verified row counts only. Sequence numbers may have
gaps after a failed transaction, which does not affect audit ordering.

After migration, configure the server and all MCP processes with the same URL,
restart, and verify incident counts, report downloads, and an existing workflow.
Keep the source backup. Do not run the SQLite and PostgreSQL versions as independent
writers during cutover. The app has not provisioned a Cloud SQL instance or migrated
the user's current ledger automatically.

## Transactions and limits

Psycopg binds all values separately from SQL. Each connection commits on success
and rolls back on failure. A PostgreSQL transaction-level advisory lock serializes
short business writes across processes, preserving the SQLite prototype's
shared-inventory/capacity guarantees and preventing duplicate releases/lost updates.
Model requests run outside these transactions. Read-only queries do not take this
lock. Locks have a 10-second timeout; SQL statements have a 30-second timeout.

Connections open per operation and close after use; limit Cloud Run instances and
concurrency to fit the database connection budget. For heavier traffic, add a bounded
pool and more granular resource locks after load testing. This change makes ledger
state durable, but does not make in-process background agent jobs durable. Instance
replacement can interrupt an analysis; the existing lease/retry handling remains.
Keep instance-based CPU allocation for the current background-worker design.

Demo/evaluation CLI commands explicitly use isolated temporary SQLite databases;
they never write test incidents to the configured Cloud SQL ledger.

## Verification

Run local regressions with `.venv/bin/pytest -q`.
For PostgreSQL integration tests, set `RESILIENTOPS_TEST_POSTGRES_URL` to a disposable
PostgreSQL database and run `.venv/bin/pytest tests/test_postgres.py -q`.
The integration fixture creates and removes a unique schema. Never give it a
production database. It checks SQLite migration, refusal to overwrite, rollback,
cross-connection concurrent updates, audit sequence continuation and restart reads.
