#!/usr/bin/env bash
# Deploy Keel to Google Cloud Run (judge = Gemini via AI Studio), backed by
# Cloud SQL for PostgreSQL (pgvector). Idempotent-ish; safe to re-run.
#
# Prereqs: gcloud CLI authed (`gcloud auth login`), billing enabled, and:
#   export GCP_PROJECT=your-project GCP_REGION=us-central1
#   export GEMINI_API_KEY=...            # from https://aistudio.google.com/apikey
#   export DB_PASSWORD=$(openssl rand -base64 24)
# Then: ./deploy/cloudrun/deploy.sh
set -euo pipefail

: "${GCP_PROJECT:?set GCP_PROJECT}"; : "${GCP_REGION:=us-central1}"
: "${GEMINI_API_KEY:?set GEMINI_API_KEY}"; : "${DB_PASSWORD:?set DB_PASSWORD}"
SQL_INSTANCE="${SQL_INSTANCE:-keel-pg}"
SQL_DB="${SQL_DB:-keel}"
SQL_USER="${SQL_USER:-keel}"
SERVICE="${SERVICE:-keel}"
CONN="${GCP_PROJECT}:${GCP_REGION}:${SQL_INSTANCE}"

gcloud config set project "$GCP_PROJECT"
echo "== enable APIs =="
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

echo "== Cloud SQL (Postgres 16 + pgvector) =="
gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1 || \
  gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 \
    --tier=db-g1-small --region="$GCP_REGION" --database-flags=cloudsql.enable_pgvector=on
gcloud sql databases describe "$SQL_DB" --instance="$SQL_INSTANCE" >/dev/null 2>&1 || \
  gcloud sql databases create "$SQL_DB" --instance="$SQL_INSTANCE"
gcloud sql users describe "$SQL_USER" --instance="$SQL_INSTANCE" >/dev/null 2>&1 || \
  gcloud sql users create "$SQL_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD"

echo "== secret: GEMINI_API_KEY =="
gcloud secrets describe keel-gemini-key >/dev/null 2>&1 || \
  gcloud secrets create keel-gemini-key --replication-policy=automatic
printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add keel-gemini-key --data-file=-

# Cloud SQL unix-socket DSN (asyncpg reads host from the query string).
DB_URL="postgresql://${SQL_USER}:${DB_PASSWORD}@/${SQL_DB}?host=/cloudsql/${CONN}"

# Base env. The agent-connect flow (I2/I3) keeps the freshly minted token's
# plaintext in a PROCESS-LOCAL one-shot store, so approve + claim must hit the
# same instance -> pin max-instances=1 until a shared store lands. See
# connect-oneshot-multiinstance / ARCHITECTURE "Identity, tokens & agent onboarding".
ENV_VARS="KEEL_LLM_PROVIDER=gemini,KEEL_LLM_MODEL=gemini/gemini-2.0-flash,KEEL_EMBEDDING_PROVIDER=deterministic,KEEL_CORS_ORIGINS=*,DATABASE_URL=${DB_URL}"
# Optional connect/login env, passed through only when set in the shell.
[ -n "${KEEL_DEFAULT_PROJECT_ID:-}" ]  && ENV_VARS="${ENV_VARS},KEEL_DEFAULT_PROJECT_ID=${KEEL_DEFAULT_PROJECT_ID}"
[ -n "${KEEL_FIREBASE_PROJECT_ID:-}" ] && ENV_VARS="${ENV_VARS},KEEL_FIREBASE_PROJECT_ID=${KEEL_FIREBASE_PROJECT_ID}"
[ -n "${KEEL_FIREBASE_AUDIENCE:-}" ]   && ENV_VARS="${ENV_VARS},KEEL_FIREBASE_AUDIENCE=${KEEL_FIREBASE_AUDIENCE}"

echo "== build + deploy Cloud Run service =="
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$GCP_REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$CONN" \
  --set-secrets "GEMINI_API_KEY=keel-gemini-key:latest" \
  --set-env-vars "$ENV_VARS" \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 1 --timeout 60

URL=$(gcloud run services describe "$SERVICE" --region "$GCP_REGION" --format='value(status.url)')
echo "== DONE =="
echo "Keel URL:   $URL/mcp"
echo "Dashboard:  point KEEL_URL at $URL ; serve keel/dashboard/ anywhere (or Firebase Hosting)."
echo "Schema is applied automatically on first boot (ensure_schema)."
echo "Seed a token:  connect to Cloud SQL and upsert a person (see deploy/cloudrun/README.md)."
