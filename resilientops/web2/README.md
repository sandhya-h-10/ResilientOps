# ResilientOps web2 interface

This is the active UI served by FastAPI at `/` and `/app`. Run
`.venv/bin/resilientops --env-file .env serve --port 8000` from the project root.
The backend and source data remain unchanged: `resilientops_data` and the existing
SQLite workflow ledger. Google sign-in uses `/auth/google/login`; sign-out uses
`POST /auth/logout`.

The web2 branding, five-section navigation, plant map, light/dark styling, Res
avatar and motion controls are preserved. `workflow-ui.js` connects incident
intake, impact, plan comparison, approval, release, actuals and outcomes to the
backend. `connected.css` styles these forms using the web2 palette. Authorized
approval still requires an approver credential, independent of Google identity.

Retired browser-only demonstration scripts and unused assets have been removed.
`workflow-ui.js` remains the active workflow implementation. Impact and recovery
PDFs use saved backend records. Res uses the configured Vertex AI connection when
server credentials are available.

Edit `app.js` for the visual shell, `workflow-ui.js` for connected views,
`style.css`, `workflow.css` and `planner-brand.css` for the supplied design, and
`connected.css` for backend form spacing. The landing and supporting pages use
the web2 HTML and marketing assets. A static file server can preview those pages;
the connected dashboard requires FastAPI.

See [workflow mapping](../docs/workflow-diagram.md) for states and limitations.

On first load of an empty operational workspace, the dashboard scans the supported
synthetic scenarios into review-required drafts. It never auto-assesses or approves
them. Data & Sources is always available in navigation. The overview shows source
counts and runtime integration modes; request failures have retry/sign-in controls.
`node scripts/browser_data_smoke.cjs` verifies first-load detection, deduplication,
source browsing and recovery from auth/source failures against an isolated server
on port 8001 and a headless Chrome CDP session on port 9228.

Manual incident creation includes text-based autofill with a suggestion preview and
explicit apply step. It extracts notice text, an explicit shipment/scenario ID and
a stated delay; it does not verify facts or infer operational links. Assess impact
opens the sidebar Impact Assessment section and displays results there.
