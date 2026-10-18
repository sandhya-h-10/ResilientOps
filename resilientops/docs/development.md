# Development conventions

1. Put role behavior in `agents/`, pure calculations in `analytics/`, and external I/O in `tools/` or `adapters/`.
2. Define and validate new externally supplied data in `models.py`.
3. Keep inventory/action mutations in `services/execution.py`; manage evidence revisions in `services/workflow.py`. Do not expose arbitrary SQL, approval credentials, or execution methods to an LLM or MCP server.
4. Store source fixtures under `data/`; write runtime output under ignored `var/` or a temporary directory. A deliberately reviewed synthetic evaluation snapshot may be copied into `docs/evaluation/` for submission reviewers.
5. Add meaningful tests for changes to authorization, calculations, evidence support, optimization constraints, and concurrency.
6. Update the lockfile intentionally when dependencies change: `uv lock`, then `uv sync --frozen --all-extras`.

## Adding a scenario

Add a variation to `data/scenarios/catalog.json` and independently author expected facts/outcomes in `data/evaluation/cases.json`. Keep evaluation labels out of prompts and application source fixtures. Named variants can supply source updates, remove policy evidence or change daily demand. For a different base dataset, copy `data/demo/scenario.json` into a new directory and set `RESILIENTOPS_DATA_DIR` to it. Use a separate `RESILIENTOPS_DB` for independent simulation universes. Event IDs are ingestion deduplication keys. Input validation checks identifiers, inventory balances, daily demand horizon, delay bounds and supersession references.

The demo's demand is material demand, not finished-product demand. Dependency traversal identifies exposed entities; it does not fabricate BOM quantities or infer a number of finished goods from missing conversion ratios.

## Runtime files

- `var/resilientops.db`, WAL and shared-memory files: persistent state and simulated inventory.
- `var/dev_credentials.json`: random local approval tokens, created with owner-only permissions.
- `var/demo-report.json`: generated isolated demo report.
- `var/evaluation.json` and `var/evaluation.html`: generated metrics and readable report.
- `var/bigquery/`: generated newline-delimited table exports.

None of these should be committed. `.env`, virtual environments and tool caches are also excluded.

## Browser verification

Use `scripts/browser_data_smoke.cjs` for the active interface. See
[web2 browser verification](../web2/README.md) for the isolated application server
(port 8001) and Chrome CDP session (port 9228) requirements. This check mutates its
isolated ledger; do not point it at the existing workspace database.

## Local container

The Dockerfile packages the same single-host application. Use a persistent volume for `/app/var`, and bind the published port to localhost:

```sh
docker build -t resilientops .
docker run --rm -p 127.0.0.1:8000:8000 -v resilientops-state:/app/var resilientops
```

Container execution is optional and was not used to validate the local Python runtime. Do not run multiple replicas against this SQLite deployment. For a shared cloud deployment, implement a transactional shared repository, platform identity, a durable task dispatcher and production outcome monitoring before exposing the service.
