# ResilientOps synthetic operational data

A reproducible dependency-ordered baseline for one fictional automotive electronics manufacturer with Mumbai, Tokyo and Beijing plants. All enterprise records, rates, costs, policies and scenario assumptions are synthetic. The operational tables contain no real company records. Separate public reference evidence is included; see EVIDENCE_START_HERE.md.

## Run in VS Code

Requires Python 3.10 or later. No third-party packages, API keys or cloud account are required.

From the extracted resilientops_data directory:

```bash
python scripts/generate_data.py --seed 42 --history-start 2024-01-01 --decision-date 2026-10-01
python scripts/validate_data.py
```

On Windows use `py -3.12` instead of `python` if necessary. Running the generator replaces the generated JSONL files, SQLite database, schema and manifest in this package. Keep source changes outside the generated data folder.

## Public data integration

See PUBLIC_DATA_SETUP.md for the optional NOAA BigQuery importer. Archived NOAA observations and curated official disruption notices are included separately. Google BigQuery imports have not been executed. See EVIDENCE_START_HERE.md for actual counts, dates and limitations. The operational records remain fully synthetic.

## Files

- `scripts/generate_data.py`: the full reproducible generator.
- `scripts/validate_data.py`: independent reconciliation and integrity checks. Nonzero exit code means failure.
- `data/*.jsonl`: one JSON object per line per operational table, suitable for Python and subsequent warehouse ingestion.
- `data/resilientops.sqlite`: the same records in a typed, queryable database with primary and foreign key definitions. Use `PRAGMA foreign_keys=ON` on new connections before modifying it.
- `schema.json`: primary keys, foreign key mappings and preliminary Python value types. It is not a production BigQuery migration; date strings, decimal strings and nullable fields need explicit warehouse type mapping.
- `manifest.json`: seed, date range, exact table counts, generation order and JSONL checksums.
- `validation_report.json`: 25 checks, their outcomes and scope limitations.

## Dependency order

1. Plants, product and material identities, revisions and supplier sites.
2. Plant capabilities and effective BOMs.
3. Supplier approvals, shared logistics hubs, routes and transfer policies.
4. Plant and line calendars.
5. Customer demand and production planning. Demand and matching production orders are created together from one constrained batch specification; allocations are explicit.
6. Component requirements calculated from each production order and its BOM.
7. Purchase orders and planned shipments derived from weekly requirements.
8. Historical receipts and FIFO consumption, creating the actual inventory ledger.
9. Daily historical balances, decision-date inventory and partial near-term reservations.
10. Forward inventory projections from planned receipts and scheduled demand.
11. Supplier commitments and historical service metrics derived from transactions.
12. Independent disruption overlay definitions referencing existing entities.

## Dates and time

Default decision timestamp: 2026-10-01T00:00:00Z. The baseline covers 1,004 plant-local historical dates from January 1, 2024 through September 30, 2026 and 30 planning dates from October 1 through October 30, 2026. Historical tables and planned projections are separate. Orders created before the first historical date and opening balances are explicitly retained as bootstrap context. Event timestamps are UTC; manufacturing calendars use the plant timezone. Opening balances are explicit bootstrap records, not fabricated receipt transactions. All historical actuals are before the decision timestamp. Future purchase orders with status PLANNED are proposals, not already committed ERP orders; future shipments have planned quantities and zero shipped quantity until dispatch.

## Simplifications and scope changes

- Four product definitions contain 48 logical component lines. Eight product-plant BOM headers instantiate these as 96 BOM rows.
- There are 105 sourcing agreements: one primary source per plant-material combination and one alternate for each of five critical components per plant. There are 51 routes, including six directional interplant routes. Counts are derived, rather than forced to previous rough targets.
- Capacity is plentiful; each production batch fits its line slot. Calendars use weekdays, without national holidays. Manufacturing scrap is zero, quality release immediate in the baseline, and components have unlimited shelf life.
- Opening stock covers the first week plus 40 units. Weekly procurement replenishes subsequent demand. This baseline intentionally has no disruption, shortage, or late supplier delivery. Baseline supplier OTIF is therefore 100 percent where deliveries exist. It is not suitable by itself for training or claiming anomaly detection accuracy.
- Supplier capacity is defined as available order-release quantity per UTC day, shared across receiving plants. It is a simplified capacity model, not a detailed supplier shop-floor schedule.
- The three plant-local currencies are retained; synthetic reporting rates are constant JPY to INR 0.56 and CNY to INR 12.00. Prices are strings for exact decimal parsing; they are not market estimates.
- Transfer offers have material-specific capacity and synthetic flat/per-unit charges. No actual customs duties, taxes, regulation or carrier quote is represented.
- Each production order is make-to-order with two customer allocations; no finished-goods warehouse, confirmed customer delivery history, or realized financial loss is generated. Historical customer status PRODUCTION_COMPLETE does not assert delivery.
- Reservations cover available lots for selected near-term requirements and may be partial. Shortage simulation must use gross usable stock and demand once, not subtract reservations and then deduct the same demand again.
- 12 scenarios contain deltas only. They do not modify the baseline, have not been passed through a recovery solver, and are not golden evaluation answers. Demand-surge deltas require production rescheduling and BOM explosion; supplier-outage deltas require supply replanning. Do not merely change a customer quantity and assume dependent schedules updated themselves.
- RAG documents, live public data, evaluation answer sets and AI agents are not included in this operational data package.
- This implementation uses surrogate IDs for daily records rather than composite physical primary keys. The logical dimensions are included as columns. Field defaults, future-date provenance and fuller row-level available-at history need strengthening before production deployment or arbitrary historical replay.

## Scenario application procedure

Copy the baseline into an isolated scenario workspace. Select one scenario and apply only its typed delta after validating the target. Update dependent supply, production and inventory forecasts. Preserve baseline actuals. Recalculate impact with the same decision timestamp. Record assumptions, data version and affected rows. Do not stack unrelated scenarios unless explicitly testing a combined event.

## Read in Python

```python
import sqlite3
connection = sqlite3.connect('data/resilientops.sqlite')
for row in connection.execute('SELECT plant_id, COUNT(*) FROM production_orders GROUP BY plant_id'):
    print(row)
```

## Validation coverage

The validator checks primary/foreign keys, network scope, provenance, all component usage, BOM-derived demand, actual consumption, lot balances, reservations, production/customer allocation, line durations/capacity/overlap, received shipment quantities, procurement pack sizes/approval, supplier capacity, actual-versus-plan cutoff, nonnegative forward inventory, all historical daily stock snapshots and scenario target references. It does not certify commercial realism, forecast accuracy, optimization correctness or production security.
