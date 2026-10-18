"""Local control-tower API. Approval identity is derived from server-configured tokens."""

import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from resilientops.adapters.operational import OperationalData, is_operational
from resilientops.auth import browser_user, configure_login
from resilientops.config import Settings
from resilientops.models import (
    Decision,
    DomainError,
    ExecuteRequest,
    IncidentRequest,
    Principal,
    UpdateSubmission,
)
from resilientops.services.chat import ChatRequest, ResChat
from resilientops.services.diagram import (
    ClosureRequest,
    ConstraintsRequest,
    DiagramWorkflow,
    DraftEdit,
    DraftRequest,
    ProgressRequest,
    RevisionRequest,
    SelectionRequest,
)
from resilientops.services.execution import ActionService
from resilientops.services.reports import render_report
from resilientops.services.scenarios import catalog
from resilientops.services.workflow import Workflow
from resilientops.storage import Store, dumps


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    store = Store(settings.database_target)
    workflow = Workflow(settings, store)
    actions = ActionService(store)
    diagram = DiagramWorkflow(workflow)
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app):
        diagram.migrate_selected_simulations()
        yield
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="ResilientOps", version="0.1.0", lifespan=lifespan)
    app.state.workflow = workflow
    app.state.store = store
    app.state.diagram = diagram
    configure_login(app, settings)
    operational = OperationalData(settings.data_dir) if is_operational(settings.data_dir) else None

    @app.get("/api/data/summary")
    def data_summary():
        if operational:
            return operational.summary()
        return {"dataset": "legacy-scenario", "synthetic": True}

    @app.get("/api/data/tables/{table}")
    def data_table(table: str, offset: int = 0, limit: int = 50):
        if not operational:
            raise HTTPException(404, "Operational dataset is not configured")
        if offset < 0 or not 1 <= limit <= 200:
            raise HTTPException(422, "Use offset >= 0 and limit between 1 and 200")
        rows = operational.rows(table)
        return {
            "table": table,
            "total": len(rows),
            "offset": offset,
            "rows": rows[offset : offset + limit],
        }

    @app.get("/api/data/documents/{document_id}")
    def data_document(document_id: str):
        if operational:
            for document in operational.documents():
                if document.id == document_id:
                    return document.model_dump()
        raise HTTPException(404, "Unknown knowledge document")

    @app.get("/api/data/references/{source}")
    def data_reference(source: str, offset: int = 0, limit: int = 50):
        if not operational:
            raise HTTPException(404, "Operational dataset is not configured")
        if offset < 0 or not 1 <= limit <= 200:
            raise HTTPException(422, "Use offset >= 0 and limit between 1 and 200")
        rows = operational.reference_rows(source)
        return {
            "source": source,
            "total": len(rows),
            "offset": offset,
            "rows": rows[offset : offset + limit],
        }

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    def principal(authorization: str | None = Header(default=None)) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "An approver token is required")
        token = authorization.removeprefix("Bearer ")
        for role, expected in [
            ("senior", settings.senior_token),
            ("manager", settings.manager_token),
        ]:
            if expected and hmac.compare_digest(token, expected):
                return Principal(id=f"local-{role}", role=role)
        raise HTTPException(403, "Invalid approver token")

    def schedule(incident_id: str):
        task = asyncio.create_task(workflow.analyze(incident_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def planner(request: Request, authorization: str | None = Header(default=None)) -> str:
        if authorization:
            return principal(authorization).id
        user = browser_user(request)
        if settings.google_login_enabled and not user:
            raise HTTPException(401, "Sign in to work on incidents")
        if (
            request.method not in {"GET", "HEAD"}
            and request.headers.get("origin") != settings.public_url
        ):
            raise HTTPException(403, "Submit workflow changes from this application")
        return user["id"] if user else "local-demo-planner"

    chat = ResChat(settings, store, operational.documents() if operational else [])
    app.state.chat = chat

    @app.get("/api/res/status")
    def chat_status(actor: Annotated[str, Depends(planner)]):
        return chat.status()

    @app.post("/api/res/chat")
    def chat_answer(body: ChatRequest, actor: Annotated[str, Depends(planner)]):
        return chat.answer(body)

    @app.get("/api/workflow/incidents")
    def workflow_incidents(actor: Annotated[str, Depends(planner)]):
        return [i for i in store.list() if i.get("workflow_kind") == "diagram"]

    @app.post("/api/workflow/incidents", status_code=201)
    def draft_incident(body: DraftRequest, actor: Annotated[str, Depends(planner)]):
        return diagram.create(body, actor)

    @app.post("/api/workflow/detect")
    def detect_incidents(actor: Annotated[str, Depends(planner)]):
        return {
            "incidents": diagram.detect(),
            "scope": "Supplied synthetic overlays; no live external-event causality inferred.",
        }

    @app.put("/api/workflow/incidents/{incident_id}/draft")
    def edit_draft(incident_id: str, body: DraftEdit, actor: Annotated[str, Depends(planner)]):
        return diagram.edit(incident_id, body, actor)

    @app.post("/api/workflow/incidents/{incident_id}/assess", status_code=202)
    async def assess_draft(
        incident_id: str, body: RevisionRequest, actor: Annotated[str, Depends(planner)]
    ):
        incident = diagram.assess(incident_id, body, actor)
        schedule(incident_id)
        return incident

    @app.post("/api/workflow/incidents/{incident_id}/replan", status_code=202)
    async def replan_incident(
        incident_id: str, body: ConstraintsRequest, actor: Annotated[str, Depends(planner)]
    ):
        incident = diagram.replan(incident_id, body, actor)
        schedule(incident_id)
        return incident

    @app.get("/api/workflow/incidents/{incident_id}/candidates/{plan_id}/rationale")
    def selection_rationale(
        incident_id: str, plan_id: str, revision: int, actor: Annotated[str, Depends(planner)]
    ):
        return diagram.selection_rationale(incident_id, plan_id, revision)

    @app.post("/api/workflow/incidents/{incident_id}/approve")
    def approve_selected_simulation(
        incident_id: str, body: ExecuteRequest, actor: Annotated[str, Depends(planner)]
    ):
        if settings.erp_mode != "local":
            raise HTTPException(
                403, "Direct planner approval is available only for local simulations"
            )
        return actions.decide(
            incident_id,
            Decision(
                plan_hash=body.plan_hash,
                decision="APPROVE",
                comment="Planner confirmed the selected plan from the dashboard (simulation).",
            ),
            Principal(id=actor, role="manager"),
            simulation_review=True,
        )

    @app.post("/api/workflow/incidents/{incident_id}/select")
    def select_plan(
        incident_id: str, body: SelectionRequest, actor: Annotated[str, Depends(planner)]
    ):
        return diagram.select(incident_id, body, actor)

    @app.get("/api/workflow/incidents/{incident_id}/reports/{kind}.pdf")
    def download_report(incident_id: str, kind: str, actor: Annotated[str, Depends(planner)]):
        incident = store.get(incident_id)
        content = render_report(incident, kind)
        filename = f"ResilientOps_{kind}_{incident['id']}_r{incident.get('revision', 1)}.pdf"
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/workflow/incidents/{incident_id}/report.eml")
    def approval_email(incident_id: str, actor: Annotated[str, Depends(planner)]):
        return Response(
            diagram.email(incident_id),
            media_type="message/rfc822",
            headers={
                "Content-Disposition": 'attachment; filename="approval-report.eml"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/workflow/incidents/{incident_id}/release")
    def release_selected_plan(
        incident_id: str, body: ExecuteRequest, actor: Annotated[str, Depends(planner)]
    ):
        if settings.erp_mode != "local":
            raise HTTPException(403, "Planner release is only available for local simulations")
        return actions.execute(
            incident_id,
            body.plan_hash,
            Principal(id=actor, role="manager"),
            simulation_release=True,
        )

    @app.post("/api/workflow/incidents/{incident_id}/progress")
    async def record_progress(
        incident_id: str, body: ProgressRequest, actor: Annotated[str, Depends(planner)]
    ):
        if settings.erp_mode != "local":
            raise HTTPException(403, "Planner actuals are only available for local simulations")
        incident = diagram.progress(incident_id, body, actor)
        if incident["status"] == "DETECTED":
            schedule(incident_id)
        return incident

    @app.post("/api/workflow/incidents/{incident_id}/close")
    def close_incident(
        incident_id: str, body: ClosureRequest, actor: Annotated[str, Depends(planner)]
    ):
        return diagram.close(incident_id, body, actor)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "storage_backend": "postgresql" if store.postgres else "sqlite",
            "agent_mode": settings.agent_mode,
            "retrieval_mode": settings.knowledge_mode,
            "execution": "simulated",
            "evidence_mode": settings.effective_evidence_mode,
        }

    @app.get("/api/scenarios")
    def scenarios():
        return catalog(settings.data_dir)

    @app.get("/api/me")
    def identity(request: Request, authorization: str | None = Header(default=None)):
        if authorization:
            identity = principal(authorization).model_dump()
        else:
            identity = browser_user(request)
            if not identity:
                raise HTTPException(401, "Sign in with Google or provide an approver token")
        return JSONResponse(identity, headers={"Cache-Control": "no-store"})

    @app.get("/api/evaluation")
    def evaluation_summary():
        if operational:
            return {
                "available": False,
                "reason": "No labeled evaluation suite for resilientops_data; archived demo scores do not apply.",
            }
        import json

        from resilientops.evaluation import suite_fingerprint

        path = settings.db_path.parent / "evaluation.json"
        if not path.exists():
            return {"available": False}
        report = json.loads(path.read_text())
        return {
            "available": True,
            "generated_at": report["generated_at"],
            "gemini_live": report["gemini_live"],
            "current": report["suite_fingerprint"] == suite_fingerprint(settings),
            "modes": {name: value["summary"] for name, value in report["modes"].items()},
        }

    @app.get("/evaluation", include_in_schema=False)
    def evaluation_report():
        if operational:
            raise HTTPException(404, "No evaluation report for the operational dataset")
        path = settings.db_path.parent / "evaluation.html"
        if not path.exists():
            raise HTTPException(404, "Run resilientops evaluate to generate the evaluation report")
        return FileResponse(path, media_type="text/html")

    @app.get("/api/incidents")
    def incidents():
        return store.list()

    @app.post("/api/incidents", status_code=201)
    def create_incident(body: IncidentRequest | None = None):
        return workflow.create(body.scenario_id if body else "baseline")

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: str):
        return store.get(incident_id)

    @app.post("/api/incidents/{incident_id}/analyze", status_code=202)
    async def analyze(incident_id: str):
        store.get(incident_id)
        schedule(incident_id)
        return {"incident_id": incident_id, "accepted": True}

    @app.post("/api/incidents/{incident_id}/reanalyze", status_code=202)
    async def reanalyze(incident_id: str, actor: Annotated[Principal, Depends(principal)]):
        if store.get(incident_id).get("workflow_kind") == "diagram":
            raise HTTPException(409, "Use the workflow replan action to preserve selection history")
        workflow.reanalyze(incident_id)
        schedule(incident_id)
        return {"incident_id": incident_id, "accepted": True}

    @app.post("/api/incidents/{incident_id}/updates", status_code=202)
    async def source_update(
        incident_id: str, body: UpdateSubmission, actor: Annotated[Principal, Depends(principal)]
    ):
        if store.get(incident_id).get("workflow_kind") == "diagram":
            raise HTTPException(409, "Use draft evidence and workflow replanning for this incident")
        workflow.reanalyze(incident_id, update=body, actor_id=actor.id)
        schedule(incident_id)
        return {"incident_id": incident_id, "accepted": True}

    @app.post("/api/incidents/{incident_id}/decision")
    def decide(incident_id: str, body: Decision, actor: Annotated[Principal, Depends(principal)]):
        return actions.decide(incident_id, body, actor)

    @app.post("/api/incidents/{incident_id}/execute")
    def execute(
        incident_id: str, body: ExecuteRequest, actor: Annotated[Principal, Depends(principal)]
    ):
        return actions.execute(incident_id, body.plan_hash, actor)

    @app.post("/api/incidents/{incident_id}/simulate-receipt")
    def simulate_receipt(incident_id: str, actor: Annotated[Principal, Depends(principal)]):
        return actions.receive_simulated_delivery(incident_id, actor)

    @app.get("/api/inventory")
    def inventory():
        return [
            i.model_dump() | {"available": i.available, "transferable": i.transferable}
            for i in store.inventories()
        ]

    @app.get("/api/incidents/{incident_id}/trace")
    def trace(incident_id: str, after: int = 0):
        return store.events(incident_id, after)

    @app.get("/api/incidents/{incident_id}/stream")
    async def stream(
        incident_id: str, request: Request, last_event_id: str | None = Header(default=None)
    ):
        store.get(incident_id)
        try:
            cursor = max(0, int(last_event_id or 0))
        except ValueError as exc:
            raise HTTPException(400, "Invalid Last-Event-ID") from exc

        async def events():
            nonlocal cursor
            while not await request.is_disconnected():
                rows = store.events(incident_id, cursor)
                for row in rows:
                    cursor = row["seq"]
                    yield f"id: {cursor}\nevent: progress\ndata: {dumps(row)}\n\n"
                status = store.get(incident_id)["status"]
                if status not in {"DETECTED", "ANALYZING"}:
                    yield f"event: complete\ndata: {dumps({'status': status})}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Use the editable export in a checkout, or its bundled copy in a wheel.
    web = Path(__file__).resolve().parents[2] / "web2"
    if not web.is_dir():
        web = Path(__file__).parent / "web2"
    app.mount("/assets", StaticFiles(directory=web), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(web / "home.html")

    @app.get("/app", include_in_schema=False)
    @app.get("/dashboard.html", include_in_schema=False)
    def dashboard(request: Request):
        if settings.google_login_enabled and not browser_user(request):
            return RedirectResponse("/access.html", status_code=303)
        return FileResponse(web / "dashboard.html", headers={"Cache-Control": "no-store"})

    # Register last so API routes keep precedence. The export uses root-relative
    # assets and links; missing paths must remain 404s, not an HTML SPA fallback.
    app.mount("/", StaticFiles(directory=web, html=True), name="ui")

    return app
