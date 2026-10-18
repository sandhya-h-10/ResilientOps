"""Google OIDC browser identity; operational approvals still require role tokens."""

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from resilientops.config import Settings


def browser_user(request: Request):
    return request.scope.get("session", {}).get("user")


def configure_login(app: FastAPI, settings: Settings):
    settings.validate_login()
    oauth = OAuth()
    if settings.google_login_enabled:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            session_cookie="resilientops_session",
            max_age=3600,
            same_site="lax",
            https_only=settings.public_url.startswith("https://"),
        )
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
        )
    app.state.oauth = oauth

    @app.get("/api/auth/status")
    def login_status():
        return {"googleEnabled": settings.google_login_enabled}

    @app.get("/auth/google/login", include_in_schema=False)
    async def login(request: Request):
        if not settings.google_login_enabled:
            return RedirectResponse("/access.html?auth_error=not_configured", status_code=303)
        # Always start and finish on the configured origin so the state cookie
        # survives users switching between localhost and 127.0.0.1.
        if str(request.base_url).rstrip("/") != settings.public_url:
            return RedirectResponse(settings.public_url + "/auth/google/login", status_code=303)
        request.session.clear()
        try:
            return await oauth.google.authorize_redirect(
                request, settings.public_url + "/auth/google/callback", prompt="select_account"
            )
        except Exception:
            request.session.clear()
            return RedirectResponse("/access.html?auth_error=unavailable", status_code=303)

    @app.get("/auth/google/callback", include_in_schema=False)
    async def callback(request: Request):
        if not settings.google_login_enabled:
            return RedirectResponse("/access.html?auth_error=not_configured", status_code=303)
        try:
            # Authlib validates state, signature, issuer, audience, expiry and nonce.
            token = await oauth.google.authorize_access_token(request)
            user = token.get("userinfo")
            if not user or not user.get("sub") or user.get("email_verified") is not True:
                raise ValueError("A verified Google identity is required")
            identity = {
                "id": "google:" + user["sub"],
                "displayName": user.get("name") or user.get("email") or "Google user",
                "email": user.get("email", ""),
                "provider": "google",
            }
        except Exception:
            # Never expose provider messages, authorization codes or tokens.
            request.session.clear()
            return RedirectResponse("/access.html?auth_error=failed", status_code=303)
        request.session.clear()
        request.session["user"] = identity
        return RedirectResponse("/app", status_code=303, headers={"Cache-Control": "no-store"})

    @app.post("/auth/logout", include_in_schema=False)
    def logout(request: Request):
        if request.headers.get("origin") != settings.public_url:
            raise HTTPException(403, "Sign out from this application")
        if "session" in request.scope:
            request.session.clear()
        return RedirectResponse("/access.html", status_code=303)
