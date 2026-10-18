#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:?Set REGION}"
: "${RUNTIME_SERVICE_ACCOUNT:?Set RUNTIME_SERVICE_ACCOUNT}"
: "${INSTANCE_CONNECTION_NAME:?Set INSTANCE_CONNECTION_NAME}"
: "${DATABASE_SECRET:?Set DATABASE_SECRET}"
: "${GOOGLE_CLIENT_ID_SECRET:?Set GOOGLE_CLIENT_ID_SECRET}"
: "${GOOGLE_CLIENT_SECRET_SECRET:?Set GOOGLE_CLIENT_SECRET_SECRET}"
: "${SESSION_SECRET:?Set SESSION_SECRET}"
SERVICE="${SERVICE:-resilientops}"
if [[ "$INSTANCE_CONNECTION_NAME" == *":REGION:"* || "$INSTANCE_CONNECTION_NAME" == *":INSTANCE" ]]; then
  echo "Replace the instance connection-name placeholders first." >&2
  exit 1
fi
command -v gcloud >/dev/null
# First deployment uses a nonfunctional sign-in origin, replaced below before use.
# For an existing deployment, preserve its origin during the build.
origin="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
origin="${origin:-https://setup.invalid}"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" --source . \
  --execution-environment gen2 --port 8000 \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME" \
  --cpu 2 --memory 2Gi --concurrency 8 \
  --min-instances 1 --max-instances 1 --no-cpu-throttling --timeout 1800 \
  --allow-unauthenticated \
  --update-env-vars "RESILIENTOPS_MODEL_BACKEND=vertex,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,RESILIENTOPS_AGENT_MODE=google,RESILIENTOPS_EVIDENCE_MODE=gemini,RESILIENTOPS_MODEL=gemini-3.5-flash,RESILIENTOPS_CHAT_MODEL=gemini-3.5-flash,RESILIENTOPS_ERP_MODE=local,RESILIENTOPS_KNOWLEDGE_MODE=local,RESILIENTOPS_ANALYSIS_TIMEOUT=1800,RESILIENTOPS_MAX_LLM_CALLS=80,RESILIENTOPS_LLM_REQUESTS_PER_MINUTE=4,RESILIENTOPS_PUBLIC_URL=$origin" \
  --update-secrets "RESILIENTOPS_DATABASE_URL=$DATABASE_SECRET:latest,RESILIENTOPS_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID_SECRET:latest,RESILIENTOPS_GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET_SECRET:latest,RESILIENTOPS_SESSION_SECRET=$SESSION_SECRET:latest"
origin="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --update-env-vars "RESILIENTOPS_PUBLIC_URL=$origin"
printf '\nApplication: %s\nOAuth redirect URI: %s/auth/google/callback\n' "$origin" "$origin"
