#!/usr/bin/env bash
# Deploy the agent API to Cloud Run as a private service.
# Prereqs: a Postgres for sessions (AlloyDB from vertex-alloydb-rag, or Cloud SQL) reachable on
# a private IP in NETWORK, and optionally the rag-api service from vertex-alloydb-rag.
# Cost: cheapest path is to reuse the AlloyDB free trial cluster from vertex-alloydb-rag (same project)
# for sessions: create a database called adk on it and point SESSION_DB_URL at it. Don't create a
# separate Cloud SQL instance just for this. The service scales to zero; Gemini bills per token.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
NETWORK="${NETWORK:-default}"
SERVICE="${SERVICE:-support-agent}"
SA_NAME="${SA_NAME:-agent-runtime}"
SESSION_DB_URL="${SESSION_DB_URL:?set SESSION_DB_URL, e.g. postgresql+asyncpg://postgres:PASS@10.0.0.5:5432/postgres}"
RAG_SERVICE="${RAG_SERVICE:-}"   # optional: name of the rag-api Cloud Run service
LABELS="${LABELS:-app=adk-production-starter,purpose=gde}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud services enable aiplatform.googleapis.com run.googleapis.com secretmanager.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="ADK agent runtime"
for role in roles/aiplatform.user roles/secretmanager.secretAccessor roles/cloudtrace.agent; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" \
    --role="$role" --condition=None >/dev/null
done

if gcloud secrets describe agent-session-db-url >/dev/null 2>&1; then
  printf '%s' "$SESSION_DB_URL" | gcloud secrets versions add agent-session-db-url --data-file=-
else
  printf '%s' "$SESSION_DB_URL" | gcloud secrets create agent-session-db-url --data-file=-
fi

ENV_VARS="GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,TRACE_TO_CLOUD=true"
if [[ -n "$RAG_SERVICE" ]]; then
  RAG_URL=$(gcloud run services describe "$RAG_SERVICE" --region="$REGION" --format='value(status.url)')
  ENV_VARS="$ENV_VARS,RAG_API_URL=$RAG_URL"
  # The agent calls the RAG service with its own identity. Grant exactly that, nothing broader.
  gcloud run services add-iam-policy-binding "$RAG_SERVICE" --region="$REGION" \
    --member="serviceAccount:$SA" --role=roles/run.invoker >/dev/null
fi

gcloud run deploy "$SERVICE" --source . --region="$REGION" --service-account="$SA" \
  --network="$NETWORK" --subnet=default --vpc-egress=private-ranges-only \
  --set-secrets=SESSION_DB_URL=agent-session-db-url:latest \
  --set-env-vars="$ENV_VARS" \
  --no-allow-unauthenticated --cpu=1 --memory=1Gi --concurrency=20 --min-instances=0 --max-instances=2 \
  --timeout=300 --labels="$LABELS"

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
TOKEN='$(gcloud auth print-identity-token)'
cat <<MSG

Deployed: $URL

# 1. Create a session (in a real app, your backend sets tenant from the verified user identity)
curl -s -X POST $URL/apps/support_agent/users/u1/sessions \\
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\
  -d '{"state": {"tenant": "default"}}'

# 2. Send a message (use the session id from step 1)
curl -s -X POST $URL/run -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\
  -d '{"app_name":"support_agent","user_id":"u1","session_id":"SESSION_ID",
       "new_message":{"role":"user","parts":[{"text":"is orders-api ok?"}]}}'
MSG

echo
echo "When you're done: gcloud run services delete $SERVICE --region=$REGION --quiet"
