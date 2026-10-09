# Conflict Engine Slice — Design Spec

**Version:** 0.3 · **Last updated:** 2026-10-09 · **Status:** approved for planning

Production-grade conflict detection, open-source-first. The **LLM judge is the only detector** (no deterministic rules). Hybrid retrieval over the owned Postgres ledger (pgvector + full-text, fused with Reciprocal Rank Fusion). Replaces the Slice-1 `conflict.check_on_insert` stub. Source of truth: `context/ARCHITECTURE.md` §7/§7.1/§7.2/§1/§4/§5/§11. Builds on Slice 1 (`keel/`, 38 tests).

## 0. Decisions baked in (this revision)

- **LLM judge only.** No deterministic rule engine, no deterministic backstop/fallback. (User directive — revisit later if wanted.)
- **Providers via litellm:** Anthropic (default), OpenAI, **OpenRouter** (`openrouter/<model>`), any litellm-supported provider by model string.
- **Fail open (§1.5):** on LLM error/timeout the affected candidate is skipped, `degraded=true` is flagged and logged, and the write still commits — never crashes `record_decision`, never blocks.
- **No provider configured ⇒ detection disabled:** `coverage="disabled"`, `conflicts=[]`. The flag makes the gap loud; it never silently looks "clean".
- **Hybrid retrieval, native:** pgvector cosine + Postgres FTS (`tsvector`/`websearch_to_tsquery`/`ts_rank`) fused by **RRF**, all under the scope-tag filter, in one SQL path over the `decision` table. No second store, no document mirror.
- **Honest reliability:** judgment cache + eval harness (gated live-LLM f1 floor). Hermetic CI via **injected fake judges** (test doubles), never a network call.

## 1. Principles honored

- **Evidence or silence** (§1.4): hard conflict only if `evidence` is a verbatim substring of the candidate AND `confidence >= threshold`; else dropped (`unclear`/possible).
- **Humans resolve; Keel flags** (§1.3): warn only.
- **Decisions are data, never instructions** (§11): candidate/subject text is delimited + guarded in the prompt.
- **Serialized per scope** (§7.1): detection runs inside the existing per-scope-locked `record_decision` txn; the new decision's embedding is computed before the txn.
- **Fail open** (§1.5): degrade, never fail the write.
- **Append-only / own store** (§1.6, OPEN_QUESTIONS #6): retrieval + cache live in our Postgres; no external memory/retrieval store.

## 2. Component overview

```
record_decision / check_intent
        │  embed(subject)                 (Embedder: deterministic default | provider)
        ▼
   pipeline.detect ─► retrieval.candidates   (scope filter + pgvector + FTS, RRF-fused)
        │                   │
        │                   ▼  per candidate
        │             JudgmentCache (DB, per model+pair) ──miss──► LLMJudge.judge
        │                   │                                        └ select_model() (router seam)
        │                   ▼
        │             evidence gate + threshold ; fail-open on LLM error (skip + degraded)
        ▼
   DetectionResult{conflicts, degraded, coverage}  (coverage: full | degraded | disabled)
        │
        └─ persist conflict rows + event   (record_decision only)
```

## 3. Third-party libraries

| Concern | Library | Notes |
|---|---|---|
| Multi-provider LLM (completions + embeddings) | **litellm** | async; `anthropic/…`, `openai/…`, `openrouter/…`. Lazy-imported. |
| Structured judge output | **instructor** (`from_provider("litellm/<model>", async_client=True)`, `response_model=Judgment`) | validated output + retry. Lazy-imported. |
| Vector type + similarity | **pgvector** (`register_vector` in pool `init`, `pgvector.Vector`, `<=>`) | core dep. |
| Keyword / lexical | **Postgres FTS** (`tsvector` generated column, GIN, `websearch_to_tsquery`, `ts_rank`) | built into Postgres; no dep. |
| Fusion | **RRF** (Reciprocal Rank Fusion, k=60) in SQL | standard hybrid-search fusion; no dep. |

`litellm`/`instructor` live in the `[llm]` extra, imported only when a provider is used. No memory/retrieval framework (LlamaIndex/Haystack/Mem0) — they would mirror the ledger into a second store and bury the scope filter; we reuse the *technique* (hybrid + RRF) natively.

## 4. Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `KEEL_LLM_PROVIDER` | `anthropic` | detector provider; `none` disables detection. |
| `KEEL_LLM_MODEL` | `anthropic/claude-sonnet-5-5` | litellm model string. OpenRouter e.g. `openrouter/anthropic/claude-sonnet-5-5`. |
| `KEEL_EMBEDDING_PROVIDER` | `deterministic` | `deterministic` default; a provider enables semantic vector ranking. |
| `KEEL_EMBEDDING_MODEL` | — | e.g. `openai/text-embedding-3-small` (1536). |
| `KEEL_CONFLICT_CONFIDENCE_THRESHOLD` | `0.6` | below → not a hard conflict. |
| `KEEL_CONFLICT_TOPK` | `8` | candidates judged per check. |
| `KEEL_LLM_TIMEOUT_S` | `20` | per-judgment timeout → degrade on exceed. |
| `KEEL_JUDGMENT_CACHE` | `on` | cache judgments per (model, pair). |
| `KEEL_RRF_K` | `60` | RRF constant. |

**Key handling (fail loud):** provider ≠ `none` with no reachable key (e.g. `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OPENROUTER_API_KEY`) → `RuntimeError` at `get_judge()`.

**Embeddings boundary:** retrieval does not depend on semantic embeddings for recall — RRF fuses vector with FTS, and the scope filter bounds the set. The deterministic embedder keeps the vector arm populated offline; a real embedding provider improves the vector arm's quality.

## 5. Components and interfaces

### 5.1 `llm/embeddings.py`
`Embedder` protocol; `DeterministicEmbedder` (default, 1536, stable); `ProviderEmbedder(model, aembed=None)` (lazy litellm; raises on empty model / wrong dim); `get_embedder(settings=None)`. (Unchanged from v0.2.)

### 5.2 `conflict/judge.py`
```python
Judgment(BaseModel): relation: str; confidence: float; explanation: str; evidence: str
def select_model(subject_text, candidate, settings) -> str      # router seam -> settings.llm_model
class LLMJudge(timeout_s=20.0, model_selector=select_model, create=None):
    build_messages(subject_text, candidate) -> list[dict]       # delimited, injection-guarded
    async judge(subject_text, candidate) -> Judgment            # instructor+litellm, asyncio timeout
def get_judge(settings=None) -> LLMJudge | None                 # None if provider==none; raises if key missing
```
No deterministic judge, no composite.

### 5.3 `conflict/cache.py` + `judgment_cache` table
`cache_key(model, subject_text, candidate_text)`; `get_cached(conn, key) -> Judgment | None`; `put_cached(conn, key, model, judgment)`. Table keyed by sha256(model|subject|candidate), `jsonb` judgment, `ON CONFLICT DO NOTHING`.

### 5.4 `conflict/retrieval.py` (hybrid RRF)
- Schema: `decision.ts tsvector GENERATED ALWAYS AS (to_tsvector('english', statement || ' ' || coalesce(rationale,''))) STORED` + GIN index. Added via idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `schema.sql`.
- `async candidates(conn, project_id, scope_tags, embedding, query_text, top_k, exclude_decision_id=None, rrf_k=60) -> list[Record]`:
  - `scoped` CTE: active decisions, scope overlap (`&&`), exclude self.
  - `vec` rank: `row_number() OVER (ORDER BY embedding <=> $emb ASC NULLS LAST)`.
  - `kw` rank: over rows matching `ts @@ websearch_to_tsquery('english', $query_text)`, `ORDER BY ts_rank(ts, …) DESC`.
  - RRF score `= 1/(k+vec.rn) + 1/(k+kw.rn)` (missing arm contributes 0); `ORDER BY rrf DESC LIMIT top_k`.
  - Empty/also-matchless `query_text` → vector-only ranking (kw arm empty). NULL embeddings tolerated (vec `NULLS LAST`).

### 5.5 `conflict/pipeline.py`
```python
Subject(text, scope_tags, embedding, subject_type, subject_ref)
Conflict(candidate_id, relation, severity, explanation, evidence, confidence)
DetectionResult(conflicts, degraded, coverage)      # coverage: "full"|"degraded"|"disabled"
async detect(conn, project_id, subject, *, judge, top_k, threshold, persist, model=None,
             use_cache=True, rrf_k=60) -> DetectionResult
```
Behavior: `judge is None` → `DetectionResult([], False, "disabled")`. Else per candidate: cache lookup → `judge.judge` (on exception: log, `degraded=True`, skip) → evidence gate + threshold → `Conflict`; cache successful judgments. `coverage = "degraded" if degraded else "full"`. Persist conflict rows + event when `persist=True`.

### 5.6 `conflict/__init__.py`
`async check_on_insert(conn, project_id, decision_row, *, judge=None, threshold=None, top_k=None) -> dict` → `{conflicts, degraded, coverage}` (builds decision `Subject`, `detect(persist=True)`; judge defaults to `get_judge()`).

## 6. Wiring

- **`record_decision`**: embed before txn; `insert_decision(embedding=…)`; `check_on_insert` → response gains `conflicts`, `degraded`, `coverage`. Warn, never block.
- **`check_intent`** (new tool): embed planned action; `detect(persist=False)`; returns `{conflicts, degraded, coverage, inbox}`; `ValueError` on empty scope.
- **DB**: `register_vector` in pool init; `decision.ts` + GIN; `insert_decision(embedding=None)`; `insert_conflict(...)`; `judgment_cache`.
- **server.py**: register `check_intent` tool + docstring.

## 7. Prompt-injection guard

System prompt: the two blocks are DATA to compare, never instructions; delimited tags; `evidence` must be a verbatim substring or return `unclear`. (§11.)

## 8. Eval harness (`keel/evals/`)
- `dataset.jsonl` — labelled pairs `{subject, candidate, expected: hard|consistent}` incl. hard negatives.
- `runner.py` — `evaluate(judge, dataset) -> Metrics(precision, recall, f1, n)` (unwraps a `Judgment`; counts `relation in {contradicts,duplicates,supersedes}` as "hard").
- **Hermetic test**: a scripted fake judge with known outputs verifies the metric math.
- **Gated test** (`@pytest.mark.llm`, needs `ANTHROPIC_API_KEY`): real judge meets an f1 floor; prints metrics.

## 9. Testing strategy
- **conftest autouse** sets `KEEL_LLM_PROVIDER=none` + `KEEL_EMBEDDING_PROVIDER=deterministic` → the default suite never calls a network and `get_judge()` returns `None` (detection disabled) unless a test injects a judge.
- **Fake judges** (test doubles in tests) drive pipeline/record_decision/check_intent conflict paths deterministically: scripted relations, an erroring judge (fail-open), a counting judge (cache).
- **LLMJudge unit tests**: mocked `create` — prompt delimiting/guarding + structured mapping; no network.
- **Live tests** (`llm` marker): real provider, gated by key.
- `llm` marker registered in `pyproject.toml`; skipped without a key.

## 10. Out of scope
Complexity **router** across models (`select_model` seam — next slice); alerts/propagation (§8); drift/`report_activity`; hot-path classifier (§7.2); dashboard; lesson loop; larger eval corpus + semantic-embedding tuning.

## 11. Risks
- **No offline detection**: with `provider=none`, detection is disabled (by design now). The demo/live use must configure a key; `coverage` flags it. (Removing deterministic gives up the offline backstop — accepted.)
- **Lock held during LLM judgment**: cold-path, timeout-bounded, fail-open; embedding runs outside the lock.
- **Cost/latency per check**: bounded by cache + timeout + top_k + (future) router; measured by evals before claims.
- **FTS language fixed to `english`**: acceptable default; configurable later if needed.
