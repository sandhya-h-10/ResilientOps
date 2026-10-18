# Operational data integration

The runtime default is `resilientops_data/`, not `data/demo`. Docker and Python
wheels include the new folder. `RESILIENTOPS_DATA_DIR` can override its location.
The old `data/` remains only for explicit regression/evaluation runs.

Source JSONL files, manifests and the supplied SQLite export are never modified
by the application. Simulated state defaults to `var/operational.db`, keeping the
old `var/resilientops.db` intact. A ledger with different inventory identities is
rejected to prevent mixing datasets. Restart the server after changing source files.

## Included integration

- Import all 90 plant/material-revision inventory positions from lot-linked
  decision-date balances. Combine quality holds and other blocked stock.
- Load all 29 knowledge documents from their catalog and RAG text, retaining IDs.
- Browse all 46 operational tables and selected archived weather, news, calendar
  and external-risk JSONL references through paginated, allowlisted API routes.
- Retain exact material revision IDs; do not merge revisions into material codes.
- Derive the 30-day material demand from BOM-exploded `material_requirements`.
- Include planned incoming shipments on plant-local dates. These are assumptions,
  including proposals, not assertions of confirmed delivery. Daily buckets assume
  arrivals precede consumption; intraday scheduling is not certified.
- Do not subtract inventory reservations and then deduct the same reserved demand.
- Apply SCN_001–SCN_003 shipment delays independently, shifting their target receipt
  while retaining unrelated scheduled receipts. Baseline uses the first target's
  plant/material with no delay. It is a single-component planning view, not a
  claim that every product or plant was fully replanned.

The original `web2` shell now loads `workflow-ui.js` for connected workflow views.
Drafts, selection, approvals, actuals and closure are saved in SQLite. The previous
`operational-app.js` is retained but not loaded. See [diagram mapping](workflow-diagram.md).

## Deliberate boundaries

SCN_004–SCN_012 are visible with unsupported status. Requests to apply them return
422: supplier outages need supply replanning, quality holds need timed lot release,
and demand surges need production rescheduling and BOM explosion. Their deltas
are not silently applied to incomplete dependent records.

Recovery candidates are mapped from approved sourcing agreements and permitted
transfer offers. Exact revisions, dated capacity/exchange rates, route transit,
MOQ/order multiples and donor protection constrain the optimizer. Purchase costs
cover material only; freight and taxes remain unquoted. All purchases require
senior approval under the explicit [OPS-SIMULATION-1 policy](operational-simulation-policy.md).
SCN_001–SCN_003 have feasible alternate-supplier recovery plans in isolated baseline
state. Operational transfers use the POL_002 inclusive senior threshold. No real
purchase orders or transfers are sent.

The supplier performance table does not contain the old detector's complete
four-feature history, so that model is not fitted. The UI detector checks supplied
scenario overlays on request; it is not a continuous live feed. No calibrated delay
simulation or per-component monetary loss model is supplied. Financial loss is
unvalued (`null`); related allocated order value is reported separately as potential
exposure, not realized loss. Baseline requires explicit outcome review and closure.

Public references are browsable context. Their entity links do not establish
causality. Weather coverage is incomplete, and no live Google import is claimed.
The source bundle's EVIDENCE_START_HERE.md describes provenance and gaps.

## APIs and validation

- `GET /api/data/summary`: version, source counts, plants, scenarios and documents.
- `GET /api/data/tables/{table}?offset=0&limit=50`: source operational records.
- `GET /api/data/references/{source}?offset=0&limit=50`: archived reference records.
- `GET /api/data/documents/{id}`: knowledge document text.
- Existing `/api/scenarios`, `/api/inventory` and `/api/incidents` use the new data.

Tests reconcile baseline projections against the supplied daily projection table,
check the three delay overlays, verify unsupported scenarios and cross-dataset
ledger rejection, and run the five agents against isolated state. The original
fixture tests continue to test recovery execution independently.

No golden evaluation suite exists for the operational export. Old benchmark scores
are not served as current results. To explicitly run the archived evaluation:

```sh
RESILIENTOPS_DATA_DIR=data/demo .venv/bin/resilientops evaluate
```

## Synthetic showcase library

Overview → **Explore 12 demo scenarios** opens an additive scenario library. Each
case creates a reviewable draft; assessment and approval remain explicit actions.
The pack is stored in `resilientops_data/showcase/scenarios.json` and rebuilt with
`.venv/bin/python scripts/build_showcase.py`. Original operational exports are unchanged.

The cases span Mumbai, Tokyo and Beijing, four material revisions, short and long
inbound delays, zero-delay control, zero incremental budget, tight arrival deadlines,
conflicting booking confirmations, an explicitly superseding correction, and reduced
confirmed recovery capacity. Described customs and route causes are simulated shipment
timing changes, not models of an entire customs or transport network.

For a demonstration, start with SHOW_001 (recovery choices), SHOW_010 (conflicting
evidence escalation), and SHOW_006 (no-action closure). Use SHOW_007/008 to explain
why cost or timing constraints prevent a feasible plan. SHOW_011 demonstrates that a
corrected confirmation can resolve evidence conflict without making recovery feasible.
Each card provides questions for Res to explain risk, evidence and next steps.

Run `.venv/bin/python scripts/evaluate_showcase.py` to refresh
`docs/evaluation/showcase-results.json`. The 12 isolated-ledger runs produced four
selection outcomes, six blocked-planning outcomes, one evidence escalation and one
closure-ready outcome. These are deterministic local/rules checks, not live Gemini
evaluations or a competition score. In the interactive workspace, reservations from
previous cases share a ledger and can change later results.

The pack supports the competition's technical, manufacturing-impact, innovation and
experience criteria through reviewable evidence and different decision outcomes:
https://aibuildercup.com/themes.html. More synthetic data alone does not demonstrate
production impact or satisfy the separate Google AI/cloud deployment requirements.

## External, internal and market monitoring pack

`resilientops_data/disruptions/` adds 12 synthetic `RISK_` scenarios and 732 dated
observations (60 historical samples plus one held-out observation for each signal).
Rebuild with `.venv/bin/python scripts/build_disruptions.py`. The original export is
unchanged. There are now 24 library cases, including the original 12 showcase cases.

- External: political, economic, environmental, technological, social and legal.
- Internal: equipment downtime, incoming quality rejection and workforce absence.
- Market: supplier lead time, demand surge and a normal-demand negative control.

Isolation Forest is fitted only on prior observations; the latest value is screened
with an adverse-direction robust z-score threshold of 3. EWMA and historical median
provide context. Labels are in a separate evaluation file and are never detector
inputs. These deliberately separated synthetic examples validate mechanics, not
real-world calibration, generalization or causal attribution.

Detect incidents scans supported supplied overlays and these monitoring scenarios.
Reviewable drafts are created for shortages or anomalous signals, with deduplication;
the normal control does not create an incident. No live external feed is implied.
Sentinel displays the signal family, baseline period, sample count and anomaly result.

The numerical consequence of most risk cases is an explicit three-day inbound receipt
delay, including internal receiving interruptions. The demand case applies a 40%
aggregate demand overlay. These scenarios do not simulate full production-machine
scheduling, legal compliance decisions, global tariffs, or economic forecasting.
Customer-order values do not include newly invented orders for the demand overlay.
