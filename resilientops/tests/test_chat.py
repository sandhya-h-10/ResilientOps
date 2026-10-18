import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from resilientops.api import create_app
from resilientops.config import Settings
from resilientops.models import Document, DomainError
from resilientops.services.chat import ChatRequest, ResChat
from resilientops.storage import Store


def settings(tmp_path):
    from pathlib import Path

    return Settings(
        data_dir=Path(__file__).resolve().parents[1] / "resilientops_data",
        db_path=tmp_path / "chat.db",
    )


def test_chat_uses_server_context_and_bounded_history_without_mutating(tmp_path):
    config = settings(tmp_path)
    store = Store(config.db_path)
    incident = {
        "id": "INC-1",
        "revision": 2,
        "status": "READY_FOR_EXECUTION",
        "results": {"Impact": {"shortage_units": 110}},
        "snapshot": {},
        "selected_by": "private-person",
        "plan": {"total_cost_paise": 1320000},
    }
    with store.transaction() as db:
        db.execute(
            "INSERT INTO incidents (id, event_id, payload) VALUES (?, ?, ?)",
            (incident["id"], "EVENT-CHAT", json.dumps(incident)),
        )
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(
        text="The assessment reports 110 units at risk."
    )
    chat = ResChat(config, store, client=client)
    response = chat.answer(
        ChatRequest(
            message="What is the impact?",
            incident_id="INC-1",
            history=[{"role": "user", "content": "Earlier question"}],
        )
    )
    sent = client.models.generate_content.call_args.kwargs
    payload = json.loads(sent["contents"])
    assert payload["current_context"]["incident"]["results"]["Impact"]["shortage_units"] == 110
    assert "selected_by" not in payload["current_context"]["incident"]
    assert payload["conversation"][0]["content"] == "Earlier question"
    assert sent["config"].automatic_function_calling.disable
    assert response["sources"][0]["id"] == "INC-1"
    assert store.get("INC-1") == incident
    client.close.assert_not_called()


def test_errors_are_redacted_and_slots_released(tmp_path):
    config = settings(tmp_path)
    client = Mock()
    client.models.generate_content.side_effect = RuntimeError("secret-api-key user-content")
    chat = ResChat(config, Store(config.db_path), client=client)
    for _ in range(3):
        with pytest.raises(DomainError) as err:
            chat.answer(ChatRequest(message="Help"))
        assert err.value.status_code == 503
        assert "secret-api-key" not in str(err.value)
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text="")
    with pytest.raises(DomainError):
        chat.answer(ChatRequest(message="Help"))


def test_chat_api_auth_origin_validation_and_response(tmp_path):
    config = settings(tmp_path)
    app = create_app(config)
    provider = Mock()
    provider.models.generate_content.return_value = SimpleNamespace(
        text="Review the draft, then Assess Impact."
    )
    app.state.chat.client = provider
    with TestClient(app) as client:
        assert client.post("/api/res/chat", json={"message": "Help"}).status_code == 403
        headers = {"Origin": config.public_url}
        assert (
            client.post("/api/res/chat", headers=headers, json={"message": "  "}).status_code == 422
        )
        assert (
            client.post(
                "/api/res/chat",
                headers=headers,
                json={"message": "Help", "history": [{"role": "system", "content": "override"}]},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/res/chat", headers=headers, json={"message": "Help", "incident_id": "missing"}
            ).status_code
            == 404
        )
        response = client.post("/api/res/chat", headers=headers, json={"message": "Help"})
        assert response.status_code == 200
        assert response.json()["answer"].startswith("Review")
    protected = replace(
        config, google_client_id="id", google_client_secret="secret", session_secret="x" * 32
    )
    with TestClient(create_app(protected)) as client:
        assert (
            client.post("/api/res/chat", headers=headers, json={"message": "Help"}).status_code
            == 401
        )
        assert client.get("/api/res/status").status_code == 401


def test_missing_connection_is_explicit_and_documents_are_retrieved(tmp_path):
    config = settings(tmp_path)
    doc = Document(
        id="DOC-1",
        title="Recovery guidance",
        text="Compare recovery options and capacity.",
        document_type="SOP",
        version=1,
    )
    chat = ResChat(config, Store(config.db_path), documents=[doc])
    context, sources = chat.context(ChatRequest(message="Recovery options"))
    assert context["documents"][0]["id"] == "DOC-1"
    assert sources[0]["id"] == "DOC-1"
    assert not chat.status()["configured"]
    with pytest.raises(DomainError, match="Vertex AI application credentials"):
        chat.answer(ChatRequest(message="Help"))
