# Deploy this package to Cloud Run

This is the current application source, not a prebuilt container or an already
provisioned Google Cloud deployment. Start in the resilientops directory.

## 1. Prepare Google Cloud

Select project project-bceae5b1-7549-4f14-922 and enable billing.
Enable Cloud Run, Cloud Build, Artifact Registry, Vertex AI, Cloud SQL Admin,
and Secret Manager APIs. Authenticate gcloud with your deployment account.
The deployer requires Cloud Run source deployment permissions and permission
to act as the runtime service account. The build identity also needs the
Cloud Run Builder role as described in Google's source deployment guide.

Create a runtime service account named resilientops-runtime. Grant it:
- Vertex AI User on the project.
- Cloud SQL Client on the project.
- Secret Manager Secret Accessor on the four secrets below.

Use the attached runtime identity for Vertex AI. Do not upload personal ADC,
a Gemini API key, or service account key files.

## 2. Prepare Cloud SQL and secrets

Follow docs/cloud-sql.md to create a PostgreSQL database and user. If you want
existing local incidents, migrate them BEFORE starting the cloud application.
Local databases and credentials are intentionally excluded from this ZIP.
The synthetic source dataset is included; a fresh database is initialized and
seeded by the app, but it does not contain your previous incident history.

Create these Secret Manager secrets:
- resilientops-database-url:
  postgresql://USER:ENCODED_PASSWORD@/resilientops?host=/cloudsql/PROJECT:REGION:INSTANCE
- resilientops-google-client-id: Google OAuth web client ID.
- resilientops-google-client-secret: its client secret.
- resilientops-session-secret: a stable random secret of at least 32 characters.

Percent-encode database username/password characters in the URL. The database
user must be able to create and use the application tables and sequences.
Do not use the local proxy address (127.0.0.1) in the Cloud Run database URL.

## 3. Deploy

Copy deploy/cloud-run.env.example to deploy/cloud-run.env. Edit the region,
instance connection name, runtime service account, and secret names to match
your resources. This file contains resource names only, not passwords.

Run from this directory:

```sh
set -a
source deploy/cloud-run.env
set +a
bash deploy/cloud-run.sh
```

The script builds the included Dockerfile using Cloud Build, attaches Cloud SQL,
configures secrets and Vertex AI, and updates the app's public URL. No local
Docker installation is required. It creates a publicly reachable Cloud Run
service; the application uses Google sign-in. Some synthetic source endpoints
remain public. Use only the supplied synthetic data for judging.

The script uses two deployments on first run to discover the service URL.
If interrupted after the first, rerun it before testing sign-in.
One minimum instance with always-allocated CPU incurs ongoing charges and is
needed for the current in-process background analysis. Do not redeploy during
an active analysis: database state persists, but background jobs can be interrupted.
The maximum instance setting is a demo operating choice, not a durable job queue.

## 4. Configure sign-in and verify

Add the printed HTTPS OAuth redirect URI to your Google OAuth web client.
Configure the OAuth audience so judges can sign in, including test users if
your application is restricted to testing.

Visit /health and confirm storage_backend is postgresql. Then verify:
sign-in, Res chat, detection, impact, recovery options, report downloads and
outcome recording. Restart/redeploy after completing a test and confirm records
persist. Never remove the database secret to work around startup errors.

The code was tested locally, including PostgreSQL transactions and migration.
This archive has not been built or deployed on Cloud Run in this session.
The last recorded live evaluation is in docs/evaluation/vertex-connection-results.json;
it records a 40-call workflow limit before the final agent review. A successful
Vertex connection alone does not establish that every scenario completes.

## References

- https://docs.cloud.google.com/run/docs/deploying-source-code
- https://docs.cloud.google.com/sql/docs/postgres/connect-run
- https://docs.cloud.google.com/run/docs/configuring/services/secrets
- https://docs.cloud.google.com/run/docs/securing/service-identity
