# Deploy Keel on Google Cloud (Cloud Run + Gemini)

Keel satisfies the platform requirement two ways:
- **Google AI model:** the conflict judge runs on **Gemini** (`gemini/gemini-2.0-flash`
  via AI Studio, or `vertex_ai/gemini-*` / Gemma on Vertex). Wired through litellm —
  one env switch. (Embeddings stay deterministic/offline; retrieval uses Postgres FTS
  + pgvector, so no embedding-dimension coupling to a provider.)
- **Google Cloud deploy:** the server runs on **Cloud Run**, backed by **Cloud SQL for
  PostgreSQL 16 + pgvector**. Secrets in **Secret Manager**.

## One-command deploy
```bash
gcloud auth login
export GCP_PROJECT=your-project GCP_REGION=us-central1
export GEMINI_API_KEY=...                      # https://aistudio.google.com/apikey
export DB_PASSWORD=$(openssl rand -base64 24)
./deploy/cloudrun/deploy.sh
```
It enables APIs, creates the Cloud SQL instance (with `cloudsql.enable_pgvector`), the
DB + user, stores the Gemini key in Secret Manager, and `gcloud run deploy --source .`
(uses the repo `Dockerfile`, which installs the `[llm]` extra). The schema is applied on
first boot by `ensure_schema`.

## After deploy
- **Service URL** is printed; the MCP endpoint is `<URL>/mcp`, the dashboard API is `<URL>/api/*`.
- **Seed a person/token** (Cloud SQL):
  ```sql
  -- gcloud sql connect keel-pg --user=keel --database=keel
  INSERT INTO project (name) VALUES ('demo') ON CONFLICT DO NOTHING;
  INSERT INTO person (project_id, display_name, token_hash)
  SELECT id, 'alice', encode(sha256('alice-token'), 'hex') FROM project WHERE name='demo';
  ```
  (token_hash = sha256 of the bearer token.)
- **Point the adapter / dashboard** at the service: `KEEL_URL=<URL>/mcp`, bearer `<token>`.
- **Dashboard hosting:** serve `keel/dashboard/` as static files — Firebase Hosting
  (`firebase init hosting && firebase deploy`) or any static host; it calls `<URL>/api/*`
  with the token (CORS is `*` by default; lock it with `KEEL_CORS_ORIGINS`).

## Semantic embeddings (optional)
By default embeddings are deterministic/offline (retrieval still works via Postgres FTS +
pgvector). For semantic recall, point the embedder at a **1536-dim-capable** model so it
fits the `vector(1536)` column:
```
KEEL_EMBEDDING_PROVIDER=gemini  KEEL_EMBEDDING_MODEL=gemini/gemini-embedding-001  KEEL_EMBEDDING_DIM=1536
# or:  KEEL_EMBEDDING_PROVIDER=openai  KEEL_EMBEDDING_MODEL=openai/text-embedding-3-small
```
`dimensions` is requested from the provider (litellm maps it to Gemini's
`output_dimensionality`). After switching a live deployment from deterministic, re-embed
existing rows once so the vector space isn't mixed:
```
python -m keel.scripts.reembed
```

## Vertex AI / Gemma variant
Prefer Vertex (no API key; uses the service account):
```
KEEL_LLM_PROVIDER=vertex_ai  KEEL_LLM_MODEL=vertex_ai/gemini-2.0-flash
# (Gemma: vertex_ai/gemma-2-... where available)
# grant the Cloud Run service account roles/aiplatform.user; set VERTEXAI_PROJECT/LOCATION
```
`get_judge` skips the key check for `vertex_ai` (it authenticates via ADC).

## Verify
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST <URL>/mcp -d '{}'   # 401 = healthy
# record two contradictory decisions -> Gemini flags the conflict with evidence (see demo/DEMO.md)
```
Locally, validate the Gemini judge with the gated test:
```bash
GEMINI_API_KEY=... KEEL_TEST_DATABASE_URL=... python -m pytest tests/test_llm_live.py -q
# picks provider=gemini automatically; asserts contradiction + eval floor f1>=0.7
```

## Cost / scale notes
- `min-instances 0` (scale to zero) — cold starts ~a few seconds; set `min-instances 1` for the demo.
- `db-g1-small` is fine for a demo; size up for load.
- Gemini `2.0-flash` is cheap/fast and supports structured output (used for the Judgment schema).
