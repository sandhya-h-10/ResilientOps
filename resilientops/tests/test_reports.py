import asyncio
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from resilientops.api import create_app
from resilientops.config import Settings
from resilientops.services.diagram import DraftRequest, RevisionRequest

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"


@pytest.mark.parametrize("scenario", ["SHOW_001", "SHOW_006", "SHOW_007"])
def test_saved_report_downloads(tmp_path, scenario):
    app = create_app(Settings(data_dir=ROOT, db_path=tmp_path / "reports.db"))
    workflow = app.state.workflow
    from resilientops.services.diagram import DiagramWorkflow

    diagram = DiagramWorkflow(workflow)
    draft = diagram.create(
        DraftRequest(
            title="Report <test> & evidence", description="Saved PDF checks", scenario_id=scenario
        ),
        "test",
    )
    url = f"/api/workflow/incidents/{draft['id']}/reports"
    with TestClient(app) as client:
        assert client.get(url + "/impact.pdf").status_code == 409
        diagram.assess(draft["id"], RevisionRequest(revision=1), "test")
        incident = asyncio.run(workflow.analyze(draft["id"]))
        before = workflow.store.get(draft["id"])
        for kind in ["impact", "recovery"]:
            response = client.get(url + f"/{kind}.pdf")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert "attachment;" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "no-store"
            reader = PdfReader(BytesIO(response.content))
            text = "\n".join(page.extract_text() for page in reader.pages)
            assert incident["id"] in text
            assert "Report <test> & evidence" in text
            assert "Revision 1" in text
            assert "SYNTHETIC SIMULATION" in text
            if kind == "impact":
                assert f"{incident['results']['Impact']['shortage_units']:,} units" in text
                assert "Time-phased material exposure" in text
            else:
                assert "No plan selected" in text
                for candidate in incident["candidates"]:
                    assert candidate["id"] in text
                if scenario == "SHOW_006":
                    assert "No recovery action is needed" in text
                if scenario == "SHOW_007":
                    assert "No feasible recovery plan" in text
        assert workflow.store.get(draft["id"]) == before
        assert client.get(url + "/unknown.pdf").status_code == 404
        assert client.get("/api/workflow/incidents/missing/reports/impact.pdf").status_code == 404


def test_reports_require_login(tmp_path):
    settings = Settings(data_dir=ROOT, db_path=tmp_path / "auth.db")
    settings = replace(
        settings,
        google_client_id="test",
        google_client_secret="test",
        session_secret="test-secret-" * 4,
    )
    with TestClient(create_app(settings)) as client:
        for kind in ["impact", "recovery"]:
            assert (
                client.get(f"/api/workflow/incidents/unknown/reports/{kind}.pdf").status_code == 401
            )
