import time
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient

from resilientops.api import create_app


@pytest.fixture
def google_app(make_workflow):
    settings = replace(
        make_workflow().settings,
        google_client_id="test-client",
        google_client_secret="test-secret",
        session_secret="test-session-secret-" * 3,
        public_url="http://127.0.0.1:8000",
    )
    app = create_app(settings)
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    public = key.as_dict(is_private=False)
    public["kid"] = "test-key"
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "sub": "google-test-user",
        "email": "person@example.com",
        "email_verified": True,
        "name": "Test Person",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }

    def provider(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://accounts.google.com",
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/token":
            signing_key = (
                JsonWebKey.generate_key("RSA", 2048, is_private=True)
                if claims.pop("_invalid_signature", False)
                else key
            )
            token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, signing_key).decode()
            return httpx.Response(
                200,
                json={
                    "access_token": "never-store-this",
                    "token_type": "Bearer",
                    "id_token": token,
                },
            )
        if request.url.path == "/oauth2/v3/certs":
            return httpx.Response(200, json={"keys": [public]})
        raise AssertionError(f"Unexpected provider request: {request.url}")

    app.state.oauth.google.client_kwargs["transport"] = httpx.MockTransport(provider)
    return app, settings, claims


def start_login(client, claims):
    response = client.get("/auth/google/login")
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/auth/google/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == {"openid", "email", "profile"}
    claims["nonce"] = query["nonce"][0]
    return query["state"][0]


def test_google_login_profile_logout_and_no_approval_authority(google_app):
    app, settings, claims = google_app
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        assert client.get("/app").status_code == 303
        assert client.get("/dashboard.html").status_code == 303
        state = start_login(client, claims)
        response = client.get("/auth/google/callback", params={"code": "test", "state": state})
        assert response.headers["location"] == "/app"
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        identity = client.get("/api/me").json()
        assert identity["displayName"] == "Test Person"
        assert identity["id"] == "google:google-test-user"
        assert "role" not in identity
        assert client.get("/app").status_code == 200
        assert client.get("/api/me", headers={"Authorization": "Bearer wrong"}).status_code == 403
        assert client.post("/api/incidents/missing/reanalyze").status_code == 401
        assert (
            client.post("/auth/logout", headers={"Origin": "https://other.test"}).status_code == 403
        )
        assert client.get("/api/me").status_code == 200
        assert (
            client.post("/auth/logout", headers={"Origin": settings.public_url}).status_code == 303
        )
        assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [
        ("nonce", "wrong"),
        ("aud", "wrong-client"),
        ("iss", "https://other.test"),
        ("exp", 1),
        ("email_verified", False),
        ("_invalid_signature", True),
    ],
)
def test_google_invalid_identity_rejected(google_app, field, value):
    app, settings, claims = google_app
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        state = start_login(client, claims)
        claims[field] = value
        response = client.get("/auth/google/callback", params={"code": "test", "state": state})
        assert response.headers["location"] == "/access.html?auth_error=failed"
        assert client.get("/api/me").status_code == 401


def test_google_state_and_cancelled_consent(google_app):
    app, settings, claims = google_app
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        start_login(client, claims)
        response = client.get("/auth/google/callback?code=bad&state=forged")
        assert response.headers["location"] == "/access.html?auth_error=failed"
        response = client.get("/auth/google/callback?error=access_denied")
        assert response.headers["location"] == "/access.html?auth_error=failed"
        assert client.get("/api/me").status_code == 401


def test_google_missing_configuration_and_canonical_origin(make_workflow, google_app):
    with TestClient(create_app(make_workflow().settings), follow_redirects=False) as client:
        assert client.get("/api/auth/status").json() == {"googleEnabled": False}
        assert client.get("/auth/google/login").headers["location"].endswith("not_configured")
        assert client.get("/app").status_code == 200
    app, settings, _ = google_app
    with TestClient(app, base_url="http://localhost:8000", follow_redirects=False) as client:
        response = client.get("/auth/google/login")
        assert response.headers["location"] == settings.public_url + "/auth/google/login"
        assert "set-cookie" not in response.headers


def test_google_configuration_fails_closed(make_workflow):
    settings = make_workflow().settings
    with pytest.raises(ValueError, match="requires client ID"):
        create_app(replace(settings, google_client_id="partial"))
    with pytest.raises(ValueError, match="HTTPS origin"):
        create_app(
            replace(
                settings,
                google_client_id="id",
                google_client_secret="secret",
                session_secret="x" * 32,
                public_url="http://public.example",
            )
        )


def test_google_session_tampering_and_secure_cookie(google_app):
    app, settings, claims = google_app
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        state = start_login(client, claims)
        client.get("/auth/google/callback", params={"code": "test", "state": state})
        cookie = client.cookies.get("resilientops_session")
        client.cookies.clear()
        client.cookies.set("resilientops_session", cookie[:-5] + "xxxxx")
        assert client.get("/api/me").status_code == 401
    secure_app = create_app(replace(settings, public_url="https://app.example.test"))
    secure_app.state.oauth.google.client_kwargs["transport"] = app.state.oauth.google.client_kwargs[
        "transport"
    ]
    with TestClient(
        secure_app, base_url="https://app.example.test", follow_redirects=False
    ) as client:
        response = client.get("/auth/google/login")
        assert response.status_code == 302
        assert "secure" in response.headers["set-cookie"].lower()


def test_res_chat_uses_google_session_and_requires_relogin_after_logout(google_app):
    from types import SimpleNamespace
    from unittest.mock import Mock

    app, settings, claims = google_app
    provider = Mock()
    provider.models.generate_content.return_value = SimpleNamespace(text="Review the incident.")
    app.state.chat.client = provider
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        state = start_login(client, claims)
        client.get("/auth/google/callback", params={"code": "test", "state": state})
        assert client.get("/api/res/status").status_code == 200
        response = client.post(
            "/api/res/chat", json={"message": "What next?"}, headers={"Origin": settings.public_url}
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "Review the incident."
        assert (
            client.post(
                "/api/res/chat",
                json={"message": "What next?"},
                headers={"Origin": "https://other.test"},
            ).status_code
            == 403
        )
        client.post("/auth/logout", headers={"Origin": settings.public_url})
        assert client.get("/api/res/status").status_code == 401
        assert (
            client.post(
                "/api/res/chat",
                json={"message": "What next?"},
                headers={"Origin": settings.public_url},
            ).status_code
            == 401
        )
        provider.models.generate_content.assert_called_once()
