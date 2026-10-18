from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

import pytest
from resilientops.config import Settings
from resilientops.services.chat import ResChat
from resilientops.storage import Store


def test_vertex_ignores_stale_api_key_and_requires_project(tmp_path):
    settings = Settings(data_dir=Path("resilientops_data"), db_path=tmp_path / "db",
                        model_backend="vertex", chat_api_key="stale-key",
                        project="test-project", location="global")
    assert settings.model_client_kwargs() == {
        "vertexai": True, "project": "test-project", "location": "global"
    }
    with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
        replace(settings, project="").model_client_kwargs()
    with patch("google.auth.default", side_effect=RuntimeError("No ADC")):
        status = ResChat(settings, Store(settings.db_path)).status()
    assert status["configured"] is False
    assert "Vertex AI" in status["detail"]


def test_environment_defaults_to_vertex(monkeypatch):
    monkeypatch.delenv("RESILIENTOPS_MODEL_BACKEND", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "stale-key")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    assert Settings.from_env().model_client_kwargs()["vertexai"] is True
