import time
from pathlib import Path

from fastapi.testclient import TestClient

from resilientops.api import create_app


def test_web2_routes_and_api_isolation(make_workflow):
    web = Path(__file__).resolve().parents[1] / "web2"
    with TestClient(create_app(make_workflow().settings)) as client:
        assert client.get("/").content == (web / "home.html").read_bytes()
        assert client.get("/app").content == (web / "dashboard.html").read_bytes()
        for file in web.iterdir():
            if file.suffix in {".html", ".css", ".js", ".svg", ".png"}:
                response = client.get(f"/{file.name}")
                assert response.status_code == 200, file.name
                assert response.content == file.read_bytes(), file.name
        assert client.get("/assets/app.js").content == (web / "app.js").read_bytes()
        for path in ("/api/unknown", "/missing.html", "/pyproject.toml", "/%2e%2e/pyproject.toml"):
            assert client.get(path).status_code == 404
        assert client.get("/api/me").status_code == 401
        assert client.get("/health").json()["execution"] == "simulated"


def wait_for_analysis(client, incident_id):
    for _ in range(200):
        result = client.get(f"/api/incidents/{incident_id}").json()
        if result["status"] not in {"DETECTED", "ANALYZING"}:
            return result
        time.sleep(0.02)
    raise AssertionError("Analysis did not complete")


def test_api_lifecycle_auth_and_sse(make_workflow):
    workflow = make_workflow()
    with TestClient(create_app(workflow.settings)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/health").json()["execution"] == "simulated"
        incident = client.post("/api/incidents").json()
        prefix = f"/api/incidents/{incident['id']}"
        assert client.post(prefix + "/analyze").status_code == 202
        incident = wait_for_analysis(client, incident["id"])
        assert incident["status"] == "AWAITING_APPROVAL"
        body = {"plan_hash": incident["plan_hash"], "decision": "APPROVE"}
        assert client.post(prefix + "/decision", json=body).status_code == 401
        assert (
            client.post(
                prefix + "/decision", json=body, headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 403
        )
        headers = {"Authorization": "Bearer test-manager-token"}
        assert (
            client.post(
                prefix + "/decision", json=body | {"role": "senior"}, headers=headers
            ).status_code
            == 422
        )
        assert client.post(prefix + "/decision", json=body, headers=headers).status_code == 200
        assert (
            client.post(
                prefix + "/execute", json={"plan_hash": incident["plan_hash"]}, headers=headers
            ).status_code
            == 200
        )
        assert client.get(prefix).json()["status"] == "MONITORING"
        assert (
            client.post(prefix + "/simulate-receipt", headers=headers).json()["status"]
            == "RESOLVED"
        )
        events = client.get(prefix + "/trace").json()
        stream = client.get(
            prefix + "/stream", headers={"Last-Event-ID": str(events[-2]["seq"])}
        ).text
        assert "simulated_receipts_verified" in stream
        assert "incident_created" not in stream
        assert "event: complete" in stream


def test_missing_incident_and_invalid_stream_cursor(make_workflow):
    with TestClient(create_app(make_workflow().settings)) as client:
        assert client.get("/api/incidents/missing").status_code == 404
        incident = client.post("/api/incidents").json()
        assert (
            client.get(
                f"/api/incidents/{incident['id']}/stream", headers={"Last-Event-ID": "bad"}
            ).status_code
            == 400
        )


def test_update_requires_identity_and_invalidates_approval(make_workflow):
    workflow = make_workflow()
    headers = {"Authorization": "Bearer test-manager-token"}
    with TestClient(create_app(workflow.settings)) as client:
        assert client.get("/api/scenarios").json()[0]["id"] == "baseline"
        assert client.post("/api/incidents", json={"scenario_id": "unknown"}).status_code == 404
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/me", headers=headers).json()["role"] == "manager"
        assert client.get("/api/evaluation").json() == {"available": False}
        incident = client.post("/api/incidents").json()
        prefix = f"/api/incidents/{incident['id']}"
        client.post(prefix + "/analyze")
        initial = wait_for_analysis(client, incident["id"])
        client.post(
            prefix + "/decision",
            json={"plan_hash": initial["plan_hash"], "decision": "APPROVE"},
            headers=headers,
        )
        update = {
            "source_label": "Carrier",
            "text": "PUNE-TRANSFER. Confirmed arrival: 2026-10-19. Available: 400 units.",
        }
        assert client.post(prefix + "/updates", json=update).status_code == 401
        assert (
            client.post(
                prefix + "/updates", json=update | {"supersedes": ["UNKNOWN"]}, headers=headers
            ).status_code
            == 409
        )
        assert client.get(prefix).json()["status"] == "APPROVED"
        assert client.post(prefix + "/updates", json=update, headers=headers).status_code == 202
        revised = wait_for_analysis(client, incident["id"])
        assert revised["approval"] is None
        assert revised["revision"] == 2
        assert revised["plan_hash"] != initial["plan_hash"]
        assert (
            client.post(
                prefix + "/execute", json={"plan_hash": initial["plan_hash"]}, headers=headers
            ).status_code
            == 409
        )
