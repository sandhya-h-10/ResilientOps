# Evidence and decision evaluation

This evaluation provides reproducible evidence for technical merit and problem alignment. It is not a prediction of hackathon scores, a held-out benchmark, or a claim of production model accuracy.

## Design

`data/demo/scenario.json` contains the base ERP fixture. `data/scenarios/catalog.json` contains eleven authored variations and source messages. `data/evaluation/cases.json` stores expected facts, outcomes and independent changes to ground-truth planning inputs. Expected labels are read by the evaluator only; neither the application prompt nor the extraction adapter receives them.

Every case runs with a fresh temporary SQLite ledger and identical initial inventory. No approval, procurement or receipt is executed by the evaluation. Three modes can be compared:

| Mode | Information used | Purpose |
| --- | --- | --- |
| `structured-only` | ERP snapshot and policies; messages ignored | Measures the risk of planning from stale structured data. |
| `rules` | Same data plus a strict booking/ISO-date/quantity template | Provides a disclosed deterministic message-processing baseline. This is not the strongest possible non-LLM parser. |
| `gemini` | Same data plus Gemini's cited structured interpretation | Measures semantic extraction on these cases when the configured model actually runs. |

All modes use the same deterministic calculations, optimizer and validators. The evaluator uses local stage orchestration to isolate extraction effects; it does not measure the extra cost/latency of the five-node ADK graph. Run a separate Google-mode demo to verify that integration.

## Cases

| Case | Expected behavior |
| --- | --- |
| Original disruption | Feasible recovery at the known baseline cost. |
| Transfer delayed | Replan; the original transfer misses day-4 demand. |
| Reduced capacity | Combine options without exceeding the new transfer capacity. |
| Conflicting reports | Escalate and preserve both sources. |
| Prose correction | Recognize the withdrawn date and use the explicitly confirmed replacement. |
| Tentative arrival | Escalate; do not turn uncertainty into a confirmed date. |
| Missing policy | Escalate before recovery planning. |
| Unapproved supplier | Keep qualification restrictions despite instructions embedded in the message. |
| Explicit correction | Use only the active source identified by trusted supersession metadata. |
| Reduced demand | Resolve the planning assessment with no action. |
| All early routes delayed | Report infeasibility instead of an executable plan. |

## Metrics

- **Decision success:** expected plan/no-action/escalation outcome, plus feasibility against independent labeled truth when a plan is returned. API/SDK failures count as failures, not successful abstentions. Known fixture costs are checked where labeled.
- **Extraction precision/recall:** micro-averaged exact matches of `(source ID, option ID, field, value)` before reconciliation against labeled arrival dates and quantities. Unknown values should be omitted. An empty prediction set has undefined precision, never an automatic 100% score.
- **Citation span validity:** quoted value and entity passages must occur verbatim in the named source. This checks provenance, not semantic entailment, sender authenticity or whether an assertion is current. Separate adversarial unit tests validate known entities, normalized dates/quantities and capacity bounds.
- **Feasible-plan rate:** fraction of returned action plans that satisfy truth-based constraints and were appropriate to propose. Reporting a plan in an expected-conflict case fails this check.
- **Escalation recall and false escalations:** distinguish appropriate abstention from missed opportunities to recover.
- **Latency:** local wall-clock time around incident creation and analysis, reported as median and nearest-rank p95. A single small pass does not establish production performance or SLA percentiles.
- **Model usage/cost:** actual extraction usage metadata. Optional rates supplied by the operator produce an estimate, including reported thinking tokens. ADK orchestration, other Google services, retries outside this adapter and infrastructure are excluded. Failed runs can have unknown usage; the report does not claim a complete cost in that case.
- **Human review time:** unmeasured. Measure it in a consented operator study against the same cases and record task completion/decision quality; do not infer time savings from model latency.

## Running and inspecting

```sh
.venv/bin/resilientops evaluate
.venv/bin/resilientops --env-file .env evaluate --mode gemini --output var/gemini-evaluation.json
.venv/bin/resilientops --env-file .env evaluate --mode all
```

Only `gemini` or `all` makes live extraction calls. Missing project/model configuration fails explicitly. The test suite's scripted model and mocked Gemini response are never reported as live evaluation results. The report includes a fingerprint of Python source, scenario data and labels, making old results distinguishable from current code. Rerun after changing those inputs.

Record the selected model, region, prompt version and model price assumptions when presenting a run. Do not cherry-pick successful cases. The checked-in offline report under `docs/evaluation/` is an inspectable snapshot; the dashboard's report under `var/` is regenerated locally.

## Next evidence needed

Run live Gemini across the complete suite, then add unseen messages authored by another reviewer. Expand to multiple suppliers/materials, date formats, ambiguous identity, partial shipment and changing demand. Measure at least repeated live runs before making reliability claims. Obtain operator feedback before claiming faster decisions or economic benefit.
