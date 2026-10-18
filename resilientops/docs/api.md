# API

FastAPI publishes the complete schemas at `/docs` and `/openapi.json`. All money fields use integer INR paise. IDs are opaque. Timestamps use UTC.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Runtime mode and simulated execution status |
| POST | `/api/incidents` | Optional `{"scenario_id":"late-arrival"}`; create/return that synthetic event, deduplicated by event ID |
| GET | `/api/scenarios` | Named scenario titles and descriptions |
| GET | `/api/me` | Authenticate the supplied bearer token and return its server-derived identity/role |
| GET | `/api/evaluation` | Available benchmark summaries, live-model status, and report freshness |
| GET | `/evaluation` | Generated HTML evaluation report, if present |
| GET | `/api/incidents` | List persisted incidents |
| GET | `/api/incidents/{id}` | Snapshot, results, evidence, plan, approval and status |
| POST | `/api/incidents/{id}/analyze` | Queue analysis; return HTTP 202 |
| GET | `/api/incidents/{id}/stream` | SSE `progress` and `complete` events; supports `Last-Event-ID` |
| GET | `/api/incidents/{id}/trace` | Persistent event history, optionally `?after=sequence` |
| GET | `/api/inventory` | Current simulated balances |
| POST | `/api/incidents/{id}/decision` | Authenticated approval or rejection bound to an exact plan hash |
| POST | `/api/incidents/{id}/execute` | Authenticated, idempotent simulated execution |
| POST | `/api/incidents/{id}/simulate-receipt` | Authenticated demo receipt and reconciliation |
| POST | `/api/incidents/{id}/reanalyze` | Authenticated refresh of an unexecuted decision; invalidate prior approval |
| POST | `/api/incidents/{id}/updates` | Authenticated source message/correction; clear approval and queue a revised analysis |

## Shipment updates

Send an approver bearer token and:

```json
{
  "source_label": "Synthetic carrier correction",
  "text": "PUNE-TRANSFER. Confirmed arrival: 2026-10-19. Available: 400 units.",
  "supersedes": []
}
```

Source IDs and timestamps are assigned by the server. To resolve conflicting reports, explicitly include the earlier source IDs in `supersedes`. Only known sources within the same incident may be replaced. Original text is retained for review. Up to eight messages of at most 8,000 characters are supported. Sources are untrusted data, and this prototype does not authenticate message senders.

Updates are accepted only for unexecuted decisions, including escalated analyses. They invalidate prior approval and plan hashes. Messages cannot modify prices, qualification, authorization or actual inventory. Interpretation results expose citations, validated facts, active sources, conflicts, changed inputs, and extraction usage. `input_snapshot` retains the original inputs; `snapshot` is the planning view after reconciliation.

## Decision

Send `Authorization: Bearer <local-approver-token>` and:

```json
{
  "plan_hash": "the exact 64-character hash returned with the current incident",
  "decision": "APPROVE",
  "comment": "Reviewed source inventory and arrival timing."
}
```

Use `REJECT` to reject. The server derives identity and role from the configured token. Client-supplied role fields are rejected.

Execution accepts only `{"plan_hash": "..."}` and the authorization header. An already committed request returns the same action. Plans do not expire with time. Changed planning snapshots, constraints, relevant inventory or supplier capacity commitments require reassessment and renewed selection/approval.

## Errors and streaming

Expected domain conflicts return HTTP 409 with a readable `detail`. Missing entities return 404; missing/invalid approval credentials return 401/403; invalid payloads return 422. No cloud SDK request details or raw prompts are exposed in analysis errors.

Analysis progress is persisted before SSE delivery. Reconnect with the last event ID to replay subsequent events. The stream ends when analysis finishes; it does not keep a worker alive while awaiting human approval. Decisions and actions can be read back through the incident endpoint.

## Diagram workflow API

The active dashboard uses these routes in addition to the decision and execution
routes above. Each incident has `workflow_kind: "diagram"`. Google sessions or
verified approver tokens identify planners; cookie/local-demo writes require the
configured same-origin `Origin` header. Local simulation release and progress use
the planner session; neither requires approval or a separate approver token. Mutations include the current `revision` except
draft creation/detection; decision/release bind the current `plan_hash` instead.

| Method | Route | Purpose |
| --- | --- | --- |
| GET / POST | `/api/workflow/incidents` | List / create persistent drafts |
| POST | `/api/workflow/detect` | Scan supplied delay scenarios into deduplicated drafts |
| PUT | `/api/workflow/incidents/{id}/draft` | Edit a draft before assessment |
| POST | `/api/workflow/incidents/{id}/assess` | Explicit review gate; queue five-agent assessment |
| POST | `/api/workflow/incidents/{id}/replan` | Revise cost, arrival and source constraints; invalidate old approvals |
| POST | `/api/workflow/incidents/{id}/select` | Select a candidate with rationale and `confirm_assumptions: true` |
| POST | `/api/workflow/incidents/{id}/release` | Release a selected plan directly, bound to its exact `plan_hash`; local ERP mode only |
| GET | `/api/workflow/incidents/{id}/report.eml` | Download selected plan's email-ready report |
| POST | `/api/workflow/incidents/{id}/progress` | Record simulated execution actuals; trigger deviation reassessment |
| POST | `/api/workflow/incidents/{id}/close` | Explicit outcome and lessons capture |

Diagram decisions support `APPROVE`, `REJECT` and `REQUEST_CHANGES`; the last two
require a nonblank comment. Legacy `updates`, `reanalyze` and `simulate-receipt`
mutations reject diagram incidents, preventing bypass of the new review gates.

Progress accepts a client-generated `update_id`. Identical retries return the
stored result without applying inventory again; different payloads with the same
ID are rejected. `received_units` maps option IDs to cumulative recovery receipts;
`actual_cost_paise` is cumulative for this execution. `consumed_units` and
`scheduled_received_units` are incremental since the previous update. `as_of_day`
cannot move backwards. Explicit `material_deviation`, overdue open allocations,
or cost overruns trigger a new assessment revision. See [workflow mapping](workflow-diagram.md).

New plans have `expires_at: null`; old timestamps remain in stored plans for hash/audit compatibility but no longer invalidate them. Rationale responses include `stale` and `stale_reasons`, based on the current ledger. Source files are immutable runtime inputs; importing changed source data requires a fresh assessment.

### PDF reports

`GET /api/workflow/incidents/{incident_id}/reports/impact.pdf` and
`GET /api/workflow/incidents/{incident_id}/reports/recovery.pdf` download styled,
revision-labelled PDFs from the saved assessment. They use the same planner/session
access as the workspace, return `409` before the relevant assessment is available,
and send `Cache-Control: no-store`. Exporting does not recalculate, approve or execute.
Recovery exports include all generated candidates and the confirmed selection, if any;
no-action and infeasible outcomes are also reportable. Values are synthetic modeled
results, with source references and assumptions. ReportLab is a runtime dependency.
