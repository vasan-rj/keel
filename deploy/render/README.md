# Deploy Keel on Render (container + managed Postgres)

Render runs the repo `Dockerfile` as-is and provisions a managed Postgres with
pgvector — no serverless port, no GCP billing. Good fit: Keel is a long-running
ASGI server with a persistent connection pool.

## One-time deploy (Blueprint)
1. Push `master` to GitHub (Render deploys from the connected repo).
2. Render Dashboard → **New → Blueprint** → pick this repo. Render reads
   `deploy/render/render.yaml`: a `web` service (Docker) + a free Postgres 16.
3. When prompted, set **`GEMINI_API_KEY`** (from https://aistudio.google.com/apikey).
   It's `sync:false`, so it lives only in Render, never in git.
4. Apply. First boot runs `ensure_schema`, which does `CREATE EXTENSION IF NOT
   EXISTS vector` and applies the schema.

The service listens on Render's `$PORT` (the Dockerfile/`keel.server` bind
`0.0.0.0:$PORT`). Health check: `/healthz`.

## After deploy
- **MCP endpoint:** `https://<service>.onrender.com/mcp`
- **Dashboard API:** `https://<service>.onrender.com/api/*` ; **connect page:** `/connect`
- **Seed a token** (Render DB — use the dashboard's PSQL command or the external URL):
  ```sql
  INSERT INTO project (name) VALUES ('demo') ON CONFLICT DO NOTHING;
  INSERT INTO person (project_id, display_name, token_hash)
  SELECT id, 'alice', encode(sha256('alice-token'), 'hex') FROM project WHERE name='demo';
  ```
- **Point an agent:** `python -m keel_connect` is for the device flow (needs Firebase);
  for a quick start use the seeded bearer token directly in `.mcp.json`.

## Notes / caveats
- **Free tier** sleeps on idle (cold start ~30s) and the free Postgres expires after
  ~90 days — fine for a demo; upgrade plans for anything real.
- **pgvector:** available on Render Postgres; `ensure_schema` creates the extension.
  If the role lacks permission, enable `vector` from the database's dashboard first.
- **`numInstances: 1`** is deliberate — the agent-connect one-shot token store is
  process-local (see ARCHITECTURE "Identity, tokens & agent onboarding"). Raising it
  needs a shared token store.
- **Connect/Google sign-in** needs Firebase env (`KEEL_FIREBASE_PROJECT_ID`,
  `KEEL_FIREBASE_AUDIENCE`, `KEEL_DEFAULT_PROJECT_ID`); unset → `/connect/approve`
  returns 503 and you seed tokens manually. Core product is unaffected.

## Railway / Fly.io
Both also run the `Dockerfile` directly: Railway auto-detects it + add a Postgres
plugin (set `DATABASE_URL`, enable `vector`); Fly uses `fly launch` + `fly pg create`
(`CREATE EXTENSION vector`). The env vars are the same as the Blueprint above.
