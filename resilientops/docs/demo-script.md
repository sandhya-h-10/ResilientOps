# Three-minute judging demonstration

Use the Manufacturing theme. Run the complete live Gemini evaluation and Google-mode workflow before recording a Gemini demonstration. If credentials are unavailable, label the recording as the local rules baseline; do not describe mocked tests as live AI.

## 0:00–0:25 — Problem and user

“A manufacturing planner has enough usable PCB inventory for 3.2 days. A supplier disruption threatens 280 units of demand. The recovery decision depends on shipment updates, supplier qualification, timing and inventory constraints.”

Show the original scenario, the six-day horizon and the no-action shortage. Explain that all entities and operations in this prototype are synthetic.

## 0:25–1:05 — Meaningful AI contribution

In a configured live Gemini run, select **Supplier prose · Gemini case**. Open the original message and show the withdrawn date, confirmed replacement, exact citations and normalized arrival day. Explain that Gemini interprets the message; deterministic tools calculate stock and optimize quantities.

Show that the original ERP-only plan violates dated-demand constraints after the update. Then show the revised, approved-option recovery plan and its cost. Use the actual observed results from the recording, not a predicted model outcome.

## 1:05–1:40 — Adaptation and review

Select **Conflicting arrival reports**. Show both quoted dates and the escalation. Connect an approver credential without exposing it in the recording. Add an explicit corrected message, selecting the earlier reports it replaces. Show the new revision and preserved source history. Explain that changed evidence clears old approval.

## 1:40–2:10 — Business outcome and controlled action

Show no-action versus planned shortages. Distinguish recovery cost from the assumed short-unit financial exposure. Explain that the figures are modeled, not measured savings. Approve the exact plan, execute the simulated action, and confirm simulated receipt.

Use an isolated demo database for the recording: dashboard scenarios share inventory, so executing one scenario changes the starting stock for subsequent analyses.

## 2:10–2:40 — Evaluation evidence

Open the generated evaluation report. Show all cases, baselines, errors, model identity, extraction/citation metrics and latency. Disclose the small authored dataset and any failed or unrun live cases. Do not convert test success into a real-world accuracy claim.

## 2:40–3:00 — Architecture and next step

Show the five roles, read-only MCP access, evidence-driven planning and separate human approval/action service. Close with the current deployment URL and the concrete path to broader supplier data and operator validation. A hosted Google Cloud demo, public repository, PDF deck and public video are still required submission artifacts.
