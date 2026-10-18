# OPS-SIMULATION-1

The connected local simulation workflow has no approver gate. Confirming a plan
selection makes it `READY_FOR_EXECUTION`. The planner releases it directly and
records actuals using the same session. No approval record is manufactured.
Previously selected plans awaiting approval become ready for release on startup;
existing audit history is retained.

Google-configured deployments require a verified session. Cookie/local-demo
writes require the configured origin. Direct planner release and actuals are
available only in local ERP mode. No email or real purchase order is sent.

Release validates the exact selected plan hash, current planning data, supplier
qualification, dated capacity, route timing, MOQ, pack multiples and inventory.
Reservations and receipts remain transactional and retries are idempotent.
Estimates exclude unquoted freight and taxes; selection acknowledges assumptions.
Changed relevant data or constraints require replanning, not a timed expiry.
Replanning invalidates the previous selection. Material deviations retain actual
receipts, cancel outstanding reservations and trigger reassessment. Closure
requires outcomes and lessons; release does not imply delivery.

Legacy decision/execution APIs retain their credential-based role policy for
compatibility: alternate-supplier purchases and transfers of at least ₹500,000
require senior authority; lower-cost transfers require manager authority. Those
APIs are not required by the connected dashboard. Source policy documents remain
unchanged. The archived `data/demo` fixture retains `DEMO-POLICY-1`.
