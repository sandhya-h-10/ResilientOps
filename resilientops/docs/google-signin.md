# Google sign-in setup

The application now supports Google OpenID Connect sign-in. The previous exported
ChatGPT sign-in link had no implementation in this backend. Google sign-in requires
an OAuth client for this application; Gemini credentials or `gcloud auth login`
do not replace it.

## Configure Google

1. Open [Google Auth Platform clients](https://console.cloud.google.com/auth/clients)
   in your chosen Google Cloud project. Configure the application's branding and
   audience. If the app is in testing mode, add your Google account as a test user
   where required by the audience settings.
2. Create an OAuth client with application type **Web application**.
3. Add this exact authorized redirect URI:
   `http://127.0.0.1:8000/auth/google/callback`.
4. Store the client ID and client secret in this project's ignored `.env` file:

   ```dotenv
   RESILIENTOPS_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   RESILIENTOPS_GOOGLE_CLIENT_SECRET=your-client-secret
   RESILIENTOPS_SESSION_SECRET=your-random-secret-at-least-32-characters
   RESILIENTOPS_PUBLIC_URL=http://127.0.0.1:8000
   ```

   Generate the session secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Keep these values local; do not paste the secret into chat or commit `.env`.
   Restrict the file with `chmod 600 .env`.
5. Restart the server from the project directory:

   ```sh
   .venv/bin/resilientops --env-file .env serve --port 8000
   ```

6. Visit `http://127.0.0.1:8000/access.html` and select **Continue with Google**.
   Complete Google's account selection and consent yourself. Successful sign-in
   returns to `/app` and displays your profile name.

For another port or deployment, update both `RESILIENTOPS_PUBLIC_URL` and Google's
authorized redirect URI. The redirect must match exactly. Non-local deployments
require HTTPS; session cookies then use the Secure attribute. If you start from
`localhost`, the login route redirects to the configured origin before setting
OAuth state. A `redirect_uri_mismatch` error means the Google client configuration
and this setting disagree. An audience/access-denied error requires checking the
test-user, organization or consent settings in your Google project.

## Behavior and boundaries

- Authlib handles authorization code flow with PKCE, state and nonce, then verifies
  the Google ID token. Only verified-email identities are accepted.
- The signed, HttpOnly, SameSite=Lax session cookie contains a minimal profile,
  expires after one hour of inactivity, and stores no Google access/refresh token.
  Signing out clears this browser's local session, not the Google account session.
- `/api/me` returns the Google profile for a valid browser session, while retaining
  the existing bearer-token response for approvers. A Google identity alone does
  not authorize operational approvals or execution.
- When configured, `/app` and `/dashboard.html` send anonymous visitors to sign-in.
  The exported static assets and synthetic read APIs remain public in this local
  prototype; this is not a full tenant/data access-control implementation.
- Without credentials, Google sign-in shows a setup message. The browser-local
  dashboard remains available as an explicitly labeled demo.
- `/api/requests` forms remain unimplemented. The operational dashboard connects to the agent workflow for supported
  scenarios; see operational-data.md for dataset coverage.
- Automated tests use simulated Google responses. Live account consent still
  needs to be tested with your own configured OAuth client.

References: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect),
[Authlib Starlette client](https://docs.authlib.org/en/v1.5.2/client/starlette.html).
