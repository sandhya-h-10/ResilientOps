import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilientops.api import create_app
from resilientops.config import Settings
from resilientops.models import Decision, DomainError, Plan, Principal
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
from resilientops.services.policy import required_role, validate_plan
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"
SENIOR = Principal(id="verified-senior", role="senior")
MANAGER = Principal(id="verified-manager", role="manager")


@pytest.fixture
def services(tmp_path):
    settings = Settings(
        data_dir=ROOT,
        db_path=tmp_path / "diagram.db",
        manager_token="manager-test",
        senior_token="senior-test",
    )
    workflow = Workflow(settings, Store(settings.db_path))
    return workflow, DiagramWorkflow(workflow), ActionService(workflow.store)


def assessed(services, scenario="SCN_001"):
    workflow, diagram, _ = services
    incident = diagram.create(
        DraftRequest(
            title="Reported component delay",
            description="Carrier notice for review",
            evidence="Human supplied source reference",
            scenario_id=scenario,
        ),
        "planner",
    )
    diagram.assess(incident["id"], RevisionRequest(revision=1), "planner")
    return asyncio.run(workflow.analyze(incident["id"]))


def selected(services):
    incident = assessed(services)
    assert incident["status"] == "AWAITING_SELECTION"
    return services[1].select(
        incident["id"],
        SelectionRequest(
            revision=1,
            plan_id=incident["candidates"][0]["id"],
            rationale="Meets the dated material requirement",
            confirm_assumptions=True,
        ),
        "planner",
    )


def released(services):
    incident = selected(services)
    services[2].decide(
        incident["id"], Decision(plan_hash=incident["plan_hash"], decision="APPROVE"), SENIOR
    )
    services[2].execute(incident["id"], incident["plan_hash"], SENIOR)
    return services[0].store.get(incident["id"])


def test_manual_draft_edit_review_and_candidate_selection(services):
    workflow, diagram, actions = services
    incident = diagram.create(
        DraftRequest(
            title="Manual shipment notice",
            description="Two day delay",
            shipment_id="SHIP_00144",
            delay_days=2,
        ),
        "planner",
    )
    assert incident["status"] == "DRAFT"
    assert asyncio.run(workflow.analyze(incident["id"]))["status"] == "DRAFT"
    with pytest.raises(DomainError):
        diagram.select(
            incident["id"],
            SelectionRequest(
                revision=1, plan_id="not-real", rationale="test", confirm_assumptions=True
            ),
            "planner",
        )
    edit = DraftEdit(**incident["draft"], revision=1)
    incident = diagram.edit(incident["id"], edit, "planner")
    with pytest.raises(DomainError, match="changed"):
        diagram.assess(incident["id"], RevisionRequest(revision=1), "planner")
    diagram.assess(incident["id"], RevisionRequest(revision=2), "planner")
    incident = asyncio.run(workflow.analyze(incident["id"]))
    assert incident["status"] == "AWAITING_SELECTION"
    assert len(incident["results"]) == 5
    assert "OPERATOR-EVIDENCE" in incident["evidence"]
    assert incident["results"]["Impact"]["order_exposure"]["potential_order_value_paise"] > 0
    with pytest.raises(DomainError, match="not awaiting approval"):
        actions.decide(
            incident["id"], Decision(plan_hash=incident["plan_hash"], decision="APPROVE"), SENIOR
        )
    plan = incident["candidates"][0]
    with pytest.raises(DomainError, match="acknowledge"):
        diagram.select(
            incident["id"],
            SelectionRequest(
                revision=2, plan_id=plan["id"], rationale="test", confirm_assumptions=False
            ),
            "planner",
        )
    incident = diagram.select(
        incident["id"],
        SelectionRequest(
            revision=2, plan_id=plan["id"], rationale="test", confirm_assumptions=True
        ),
        "planner",
    )
    assert incident["status"] == "READY_FOR_EXECUTION"
    assert incident["approval_report"]["plan_hash"] == incident["plan_hash"]
    assert b"Subject:" in diagram.email(incident["id"])
    with pytest.raises(DomainError, match="senior"):
        actions.decide(
            incident["id"], Decision(plan_hash=incident["plan_hash"], decision="APPROVE"), MANAGER
        )


@pytest.mark.parametrize("decision", ["REJECT", "REQUEST_CHANGES"])
def test_approver_feedback_returns_to_recovery_and_invalidates_report(services, decision):
    workflow, diagram, actions = services
    incident = selected(services)
    old_hash = incident["plan_hash"]
    with pytest.raises(DomainError, match="Explain"):
        actions.decide(incident["id"], Decision(plan_hash=old_hash, decision=decision), SENIOR)
    actions.decide(
        incident["id"],
        Decision(plan_hash=old_hash, decision=decision, comment="Review cost limit"),
        SENIOR,
    )
    assert workflow.store.get(incident["id"])["status"] == "CHANGES_REQUESTED"
    diagram.replan(
        incident["id"],
        ConstraintsRequest(revision=1, max_cost_paise=0, reason="Set tighter budget"),
        "planner",
    )
    blocked = asyncio.run(workflow.analyze(incident["id"]))
    assert blocked["status"] == "PLANNING_BLOCKED"
    assert blocked["revision"] == 2
    assert blocked["approval"] is None and blocked["approval_report"] is None
    assert blocked["history"][0]["approval"]["decision"] == decision
    with pytest.raises(DomainError):
        actions.execute(incident["id"], old_hash, SENIOR)
    diagram.replan(
        incident["id"], ConstraintsRequest(revision=2, reason="Remove budget constraint"), "planner"
    )
    assert asyncio.run(workflow.analyze(incident["id"]))["status"] == "AWAITING_SELECTION"


def test_release_partial_actuals_close_and_restart(services):
    workflow, diagram, actions = services
    incident = released(services)
    plan = incident["plan"]
    allocation = plan["allocations"][0]
    assert (
        actions.execute(incident["id"], incident["plan_hash"], SENIOR)["id"]
        == incident["action_id"]
    )
    with pytest.raises(DomainError):
        diagram.close(
            incident["id"],
            ClosureRequest(revision=1, outcome="Not yet", lessons="Not yet"),
            "planner",
        )
    partial = ProgressRequest(
        revision=1,
        update_id="partial-1",
        received_units={allocation["option_id"]: 50},
        actual_cost_paise=600000,
        note="Partial arrival confirmed",
    )
    incident = diagram.progress(incident["id"], partial, SENIOR.id)
    assert incident["status"] == "MONITORING"

    def stock():
        return next(
            i.on_hand
            for i in workflow.store.inventories()
            if i.plant_id == "PLT_MUM" and i.material_id == "MAT_001_A"
        )

    assert stock() == 90
    diagram.progress(incident["id"], partial, SENIOR.id)
    assert stock() == 90
    with pytest.raises(DomainError, match="reused"):
        diagram.progress(
            incident["id"], partial.model_copy(update={"consumed_units": 10}), SENIOR.id
        )
    with pytest.raises(DomainError, match="cannot decrease"):
        diagram.progress(
            incident["id"],
            partial.model_copy(update={"update_id": "bad-cost", "actual_cost_paise": 0}),
            SENIOR.id,
        )
    full = ProgressRequest(
        revision=1,
        update_id="receipt-full",
        received_units={allocation["option_id"]: allocation["quantity"]},
        actual_cost_paise=plan["total_cost_paise"],
        note="All approved units received",
    )
    incident = diagram.progress(incident["id"], full, SENIOR.id)
    assert incident["status"] == "AWAITING_CLOSURE"
    assert stock() == 40 + allocation["quantity"]
    restarted = DiagramWorkflow(Workflow(workflow.settings, Store(workflow.settings.db_path)))
    incident = restarted.close(
        incident["id"],
        ClosureRequest(
            revision=1,
            outcome="Recovered scheduled supply",
            lessons="Confirm capacity before approval",
        ),
        "planner",
    )
    assert incident["status"] == "RESOLVED"
    assert incident["outcome"]["cost_variance_paise"] == 0
    assert incident["outcome"]["actual_cost_paise"] == plan["total_cost_paise"]


def test_material_deviation_preserves_receipts_and_invalidates_old_approval(services):
    workflow, diagram, actions = services
    incident = released(services)
    old_hash = incident["plan_hash"]
    allocation = incident["plan"]["allocations"][0]
    update = ProgressRequest(
        revision=1,
        update_id="deviation-1",
        received_units={allocation["option_id"]: 50},
        actual_cost_paise=600000,
        note="Outstanding quantity delayed",
        material_deviation=True,
    )
    revised = diagram.progress(incident["id"], update, SENIOR.id)
    assert revised["status"] == "DETECTED" and revised["revision"] == 2
    assert revised["approval"] is None
    with workflow.store.connect() as db:
        action = json.loads(db.execute("SELECT payload FROM actions").fetchone()[0])
    assert action["status"] == "CANCELLED"
    assert action["allocations"][0]["received_units"] == 50
    assert diagram.progress(incident["id"], update, SENIOR.id)["revision"] == 2
    with pytest.raises(DomainError):
        actions.execute(incident["id"], old_hash, SENIOR)
    revised = asyncio.run(workflow.analyze(incident["id"]))
    assert revised["status"] == "PLANNING_BLOCKED"  # New order cannot cover day five.
    assert len(revised["results"]) == 5


def test_late_delivery_automatically_reassesses_without_double_counting_scheduled_receipts(
    services,
):
    workflow, diagram, _ = services
    incident = released(services)
    a = incident["plan"]["allocations"][0]
    revised = diagram.progress(
        incident["id"],
        ProgressRequest(
            revision=1,
            update_id="late",
            received_units={a["option_id"]: 50},
            actual_cost_paise=600000,
            note="Partial shipment plus scheduled delivery",
            as_of_day=7,
            scheduled_received_units=320,
            consumed_units=150,
        ),
        SENIOR.id,
    )
    assert revised["revision"] == 2  # Automatic: remaining recovery delivery overdue.
    assert revised["snapshot"]["scheduled_receipts"][:7] == [0] * 7
    assert sum(revised["snapshot"]["daily_demand"][:7]) == 0
    assert (
        next(
            i["on_hand"]
            for i in revised["snapshot"]["inventories"]
            if i["plant_id"] == "PLT_MUM" and i["material_id"] == "MAT_001_A"
        )
        == 260
    )


def test_detector_deduplicates_and_baseline_needs_explicit_outcome_review(services):
    workflow, diagram, _ = services
    assert len(diagram.detect()) == 14
    assert len(diagram.detect()) == 14
    assert len(workflow.store.list()) == 14
    baseline = assessed(services, "baseline")
    assert baseline["status"] == "AWAITING_CLOSURE"
    closed = diagram.close(
        baseline["id"],
        ClosureRequest(
            revision=1,
            outcome="No disruption in baseline",
            lessons="Baseline remains fully covered",
        ),
        "planner",
    )
    assert closed["outcome"]["planned_cost_paise"] == 0


def test_workflow_api_auth_csrf_and_persistent_boundaries(services):
    settings = services[0].settings
    headers = {"Authorization": "Bearer senior-test"}
    with TestClient(create_app(settings)) as client:
        draft = {
            "title": "Review supplied scenario",
            "description": "Recorded notice",
            "scenario_id": "SCN_001",
        }
        assert client.post("/api/workflow/incidents", json=draft).status_code == 403
        response = client.post(
            "/api/workflow/incidents", json=draft, headers={"Origin": settings.public_url}
        )
        assert response.status_code == 201
        incident = response.json()
        path = "/api/workflow/incidents/" + incident["id"]
        assert (
            client.post(path + "/assess", json={"revision": 1}, headers=headers).status_code == 202
        )
        for _ in range(200):
            incident = client.get("/api/incidents/" + incident["id"]).json()
            if incident["status"] not in {"DETECTED", "ANALYZING"}:
                break
            time.sleep(0.02)
        assert incident["status"] == "AWAITING_SELECTION"
        assert (
            client.post(
                "/api/incidents/" + incident["id"] + "/reanalyze", headers=headers
            ).status_code
            == 409
        )
        selection = {
            "revision": 1,
            "plan_id": incident["candidates"][0]["id"],
            "rationale": "Feasible arrival",
            "confirm_assumptions": True,
        }
        assert client.post(path + "/select", json=selection, headers=headers).status_code == 200
        assert (
            client.get(path + "/report.eml", headers=headers)
            .headers["content-type"]
            .startswith("message/rfc822")
        )
        assert (
            client.post(
                path + "/progress",
                json={
                    "revision": 1,
                    "update_id": "forged",
                    "actual_cost_paise": 0,
                    "note": "Not allowed",
                },
            ).status_code
            == 403
        )
    configured = replace(
        settings, google_client_id="id", google_client_secret="secret", session_secret="x" * 32
    )
    with TestClient(create_app(configured)) as client:
        assert client.get("/api/workflow/incidents").status_code == 401


def test_order_multiples_budget_and_operational_policy_threshold(services):
    from resilientops.analytics.optimization import optimize
    from resilientops.models import Dataset

    incident = assessed(services)
    data = Dataset.model_validate(incident["snapshot"])
    plan = Plan.model_validate(incident["candidates"][0])
    assert not validate_plan(data, plan)
    plan.allocations[0].quantity += 1
    assert any("multiple" in e for e in validate_plan(data, plan))
    blocked, _ = optimize(data.model_copy(update={"max_cost_paise": 1}), "budget", [])
    assert blocked.status == "INFEASIBLE"
    plan.allocations[0].option_id = "OF_TRANSFER"
    plan.total_cost_paise = 50000000
    assert required_role(plan) == "senior"


def test_agent_selection_rationale_is_grounded_and_does_not_select(services):
    workflow, diagram, _ = services
    incident = assessed(services)
    candidate = incident["candidates"][0]
    result = diagram.selection_rationale(incident["id"], candidate["id"], incident["revision"])
    assert candidate["id"] in result["rationale"]
    assert f"INR {candidate['total_cost_paise'] / 100:,.2f}" in result["rationale"]
    assert "unquoted freight and taxes" in result["rationale"]
    assert len(result["rationale"]) <= 2000
    assert workflow.store.get(incident["id"])["status"] == "AWAITING_SELECTION"
    with pytest.raises(DomainError):
        diagram.selection_rationale(incident["id"], candidate["id"], 99)
    with pytest.raises(DomainError):
        diagram.selection_rationale(incident["id"], "UNKNOWN", incident["revision"])
    with TestClient(create_app(workflow.settings)) as client:
        url = f"/api/workflow/incidents/{incident['id']}/candidates/{candidate['id']}/rationale"
        response = client.get(url, params={"revision": incident["revision"]})
        assert response.status_code == 200
        assert response.json()["rationale"] == result["rationale"]


def test_legacy_timestamp_does_not_invalidate_unchanged_candidate(services):
    from datetime import timedelta

    from resilientops.models import utcnow

    workflow, diagram, _ = services
    incident = assessed(services)
    candidate = incident["candidates"][0]
    candidate["expires_at"] = (utcnow() - timedelta(days=7)).isoformat()
    with workflow.store.transaction() as db:
        workflow.store.save(db, incident)
    result = diagram.selection_rationale(incident["id"], candidate["id"], incident["revision"])
    assert result["stale"] is False
    chosen = diagram.select(
        incident["id"],
        SelectionRequest(
            revision=incident["revision"],
            plan_id=candidate["id"],
            rationale=result["rationale"],
            confirm_assumptions=True,
        ),
        "planner",
    )
    assert chosen["status"] == "READY_FOR_EXECUTION"


def test_relevant_inventory_change_requires_refresh_but_unrelated_change_does_not(services):
    workflow, diagram, _ = services
    incident = assessed(services)
    candidate = incident["candidates"][0]
    with workflow.store.transaction() as db:
        unrelated = next(i for i in workflow.store.inventories(db) if i.plant_id == "PLT_TYO")
        unrelated.on_hand += 1
        workflow.store.put_inventory(db, unrelated)
    assert not diagram.selection_rationale(incident["id"], candidate["id"], 1)["stale"]
    with workflow.store.transaction() as db:
        relevant = next(
            i
            for i in workflow.store.inventories(db)
            if i.plant_id == "PLT_MUM" and i.material_id == "MAT_001_A"
        )
        relevant.on_hand += 1
        workflow.store.put_inventory(db, relevant)
    result = diagram.selection_rationale(incident["id"], candidate["id"], 1)
    assert result["stale"]
    with pytest.raises(DomainError, match="inventory changed"):
        diagram.select(
            incident["id"],
            SelectionRequest(
                revision=1,
                plan_id=candidate["id"],
                rationale=result["rationale"],
                confirm_assumptions=True,
            ),
            "planner",
        )
    diagram.replan(
        incident["id"], ConstraintsRequest(revision=1, reason="Refresh inventory inputs"), "planner"
    )
    updated = asyncio.run(workflow.analyze(incident["id"]))
    assert not diagram.selection_rationale(updated["id"], updated["candidates"][0]["id"], 2)[
        "stale"
    ]


def test_new_supplier_commitment_invalidates_other_candidate(services):
    workflow, diagram, actions = services
    first = selected(services)
    second = assessed(services, "SCN_002")
    actions.decide(first["id"], Decision(plan_hash=first["plan_hash"], decision="APPROVE"), SENIOR)
    actions.execute(first["id"], first["plan_hash"], SENIOR)
    result = diagram.selection_rationale(second["id"], second["candidates"][0]["id"], 1)
    assert result["stale"]
    assert any("capacity commitments changed" in reason for reason in result["stale_reasons"])


def test_direct_simulation_approval_keeps_identity_and_does_not_execute(services):
    workflow, _, _ = services
    incident = selected(services)
    with TestClient(create_app(workflow.settings)) as client:
        path = f"/api/workflow/incidents/{incident['id']}/approve"
        payload = {"plan_hash": incident["plan_hash"]}
        assert client.post(path, json=payload).status_code == 403
        response = client.post(path, json=payload, headers={"Origin": workflow.settings.public_url})
        assert response.status_code == 200
        saved = response.json()
        assert saved["status"] == "APPROVED"
        assert saved["approval"]["role"] == "simulation-reviewer"
        assert saved["approval"]["actor"] == "local-demo-planner"
        assert not saved.get("action_id")
        assert (
            client.post(f"/api/incidents/{incident['id']}/execute", json=payload).status_code == 401
        )
    configured = replace(
        workflow.settings,
        google_client_id="id",
        google_client_secret="secret",
        session_secret="x" * 32,
    )
    with TestClient(create_app(configured)) as client:
        assert (
            client.post(path, json=payload, headers={"Origin": configured.public_url}).status_code
            == 401
        )


def test_planner_releases_and_records_actuals_without_approval(services):
    workflow, _, _ = services
    incident = selected(services)
    assert incident["status"] == "READY_FOR_EXECUTION"
    assert incident["approval"] is None
    path = f"/api/workflow/incidents/{incident['id']}"
    payload = {"plan_hash": incident["plan_hash"]}
    headers = {"Origin": workflow.settings.public_url}
    with TestClient(create_app(workflow.settings)) as client:
        assert client.post(path + "/release", json=payload).status_code == 403
        assert client.post(
            path + "/release", json={"plan_hash": "wrong"}, headers=headers
        ).status_code in (409, 422)
        result = client.post(path + "/release", json=payload, headers=headers)
        assert result.status_code == 200, result.text
        assert client.post(path + "/release", json=payload, headers=headers).json() == result.json()
        saved = workflow.store.get(incident["id"])
        assert saved["status"] == "MONITORING"
        assert saved["approval"] is None
        assert not saved["decision_history"]
        plan = incident["plan"]
        result = client.post(
            path + "/progress",
            headers=headers,
            json={
                "revision": 1,
                "update_id": "planner-receipt",
                "received_units": {a["option_id"]: a["quantity"] for a in plan["allocations"]},
                "actual_cost_paise": plan["total_cost_paise"],
                "note": "All planned units received",
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "AWAITING_CLOSURE"
        result = client.post(
            path + "/close",
            headers=headers,
            json={
                "revision": 1,
                "outcome": "Supply recovered",
                "lessons": "Validate supplier timing",
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "RESOLVED"
    configured = replace(
        workflow.settings,
        google_client_id="id",
        google_client_secret="secret",
        session_secret="x" * 32,
    )
    with TestClient(create_app(configured)) as client:
        assert client.post(path + "/release", json=payload, headers=headers).status_code == 401


def test_existing_selected_simulation_migrates_without_inventing_approval(services):
    workflow, diagram, _ = services
    incident = selected(services)
    incident["status"] = "AWAITING_APPROVAL"
    with workflow.store.transaction() as db:
        workflow.store.save(db, incident)
    diagram.migrate_selected_simulations()
    migrated = workflow.store.get(incident["id"])
    assert migrated["status"] == "READY_FOR_EXECUTION"
    assert migrated["plan_hash"] == incident["plan_hash"]
    assert migrated["approval"] is None
    assert not migrated["decision_history"]
