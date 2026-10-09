# Conflict Engine Slice — Design Spec

**Version:** 0.2 · **Last updated:** 2026-10-09 · **Status:** approved for planning

Production-grade conflict detection, built open-source-first (not a hackathon stub). The **LLM judge is the primary detector from day one**; deterministic rules are a backstop, not the product. Replaces the Slice-1 `conflict.check_on_insert` stub. Source of truth: `context/ARCHITECTURE.md` §7 (pipeline), §7.1 (serialized insert), §7.2 (hot/cold path), §1 (principles), §4 (data model), §5 (tools). Builds on Slice 1 (`keel/`, 38 tests).

## 0. What "production from day one" means here

- The default detector is the **LLM judge** (latest Claude via litellm), not the deterministic rules.
- Deterministic rules run **alongside** the LLM as a backstop that guarantees known high-value conflicts fire even if the LLM misses them — never as the sole detector.
- **Fail open** (§1.5): if the LLM errors/times out, the call degrades to the deterministic result, flags `degraded=true`, logs loudly, and never crashes `record_decision`.
- **Honest reliability**: a judgment **cache**, an **eval harness** with a labelled set, and gated live-LLM tests — so precision/recall is measured, not asserted.
- Every detection response carries `coverage` (`full` | `deterministic-only`) and `degraded`, so a user never mistakes limited scanning for a clean bill.

## 1. Principles honored

- **Evidence or silence** (§1.4): emit a hard conflict only if `evidence` is a non-empty substring of the candidate's statement/rationale AND `confidence >= threshold`; else `unclear`/possible, dropped from hard conflicts.
- **Humans resolve; Keel flags** (§1.3): warn only; no block, no auto-overwrite.
- **Determinism where it is cheap** (§1): deterministic checks run first and backstop the probabilistic judge; identical (model, pair) inputs return a cached, identical judgment.
- **Decisions are data, never instructions** (§11): candidate/subject text in the LLM prompt is delimited and guarded as untrusted.
- **Serialized per scope** (§7.1): detection runs inside the existing per-scope-advisory-locked `record_decision` transaction; the new decision's embedding is computed **before** the transaction opens.
- **Fail open** (§1.5): the engine degrades, it does not fail the write.

## 2. Component overview

```
record_decision / check_intent
        │  embed(subject)            (Embedder: deterministic default | provider)
        ▼
   pipeline.detect ──► retrieval.candidates  (scope filter + keyword+vector rank)
        │                    │
        │                    ▼
        │              CompositeJudge.judge(subject, candidate)
        │                    ├─ DeterministicJudge  (rules backstop, always)
        │                    ├─ LLMJudge            (instructor+litellm, primary)
        │                    │     └─ select_model()  (router seam; one default model now)
        │                    ├─ merge (LLM primary, deterministic backstop floor)
        │                    └─ JudgmentCache (DB, per (model, pair) hash)
        ▼
   evidence gate + threshold ──► DetectionResult{conflicts, degraded, coverage}
        │
        └─ persist conflict rows + event (record_decision only)
```

## 3. Third-party libraries (reuse, not rebuild)

| Concern | Library | Notes |
|---|---|---|
| Multi-provider LLM (completions + embeddings) | **litellm** | async `acompletion`/`aembedding`; provider by model string (`anthropic/…`, `openai/…`, `openrouter/…`). Lazy-imported. |
| Structured judge output | **instructor** (`from_provider("litellm/<model>", async_client=True)`, `response_model=Judgment`) | validated Pydantic output + retry on schema failure. Lazy-imported. |
| Vector type + similarity | **pgvector** (`register_vector` in asyncpg pool `init`, `pgvector.Vector`, `<=>` cosine) | registered per connection. Core dependency. |

`litellm` + `instructor` live in the `[llm]` extra and are imported only inside provider/LLM classes. No memory-layer framework (Mem0/Zep/etc.) — OPEN_QUESTIONS #6.

## 4. Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `KEEL_LLM_PROVIDER` | `anthropic` | detector provider; `none` disables the LLM (deterministic-only, for offline/tests). |
| `KEEL_LLM_MODEL` | `anthropic/claude-sonnet-5-5` | litellm model string for the judge. |
| `KEEL_EMBEDDING_PROVIDER` | `deterministic` | `deterministic` default; a provider enables semantic ranking. |
| `KEEL_EMBEDDING_MODEL` | — | e.g. `openai/text-embedding-3-small` (1536 dims). |
| `KEEL_CONFLICT_CONFIDENCE_THRESHOLD` | `0.6` | below → not a hard conflict. |
| `KEEL_CONFLICT_TOPK` | `8` | candidates judged per check. |
| `KEEL_LLM_TIMEOUT_S` | `20` | per-judgment LLM timeout; on exceed → degrade. |
| `KEEL_JUDGMENT_CACHE` | `on` | cache judgments per (model, pair). |

**Key handling (fail loud):** when `KEEL_LLM_PROVIDER != none`, the required provider key (e.g. `ANTHROPIC_API_KEY`) must be present; `get_judge()` raises a clear `RuntimeError` at construction if a provider is configured with no reachable key — never a cryptic failure mid-transaction. Default model follows CLAUDE.md "default to the latest, most capable Claude".

**Embeddings boundary:** retrieval recall does **not** depend on semantic embeddings — `retrieval.candidates` ranks by **keyword overlap first, vector distance second**, and returns all scope-overlapping actives up to `top_k`. The deterministic embedder keeps the `vector` column populated and the query path exercised; a real embedding provider improves ranking only when a scope holds more than `top_k` actives. This is a deliberate boundary, not an omission.

## 5. Components and interfaces

New packages `keel/keel/llm/` and `keel/keel/conflict/` (the Slice-1 `conflict.py` becomes the package `conflict/`).

### 5.1 `llm/embeddings.py`
`Embedder` protocol (`dim`, `async embed(text) -> pgvector.Vector`); `DeterministicEmbedder` (default, sha256-seeded, 1536, stable); `ProviderEmbedder(model, aembed=None)` (lazy litellm; raises on empty model or wrong dim); `get_embedder(settings=None)`.

### 5.2 `conflict/judge.py`
```python
Judgment(BaseModel): relation: str; confidence: float; explanation: str; evidence: str
Judge(Protocol): async def judge(subject_text, candidate) -> Judgment
DeterministicJudge        # rules -> Judgment (backstop)
def select_model(subject_text, candidate, settings) -> str   # router seam; returns settings.llm_model now
LLMJudge(model_selector=select_model, create=None)
    build_messages(subject_text, candidate) -> list[dict]    # delimited, injection-guarded
    async judge(...) -> Judgment                              # instructor+litellm; timeout; retries via instructor
CompositeJudge(llm: LLMJudge | None, deterministic: DeterministicJudge, timeout_s)
    async judge(...) -> tuple[Judgment, bool]                 # (judgment, degraded)
        # run deterministic (always). if llm: try llm within timeout.
        #   - llm ok  -> primary = llm; if deterministic found a HARD relation the
        #     llm rated consistent/unclear, override with deterministic (backstop floor).
        #   - llm error/timeout -> primary = deterministic, degraded=True, log.
        # llm is None (provider none) -> primary = deterministic, degraded=False.
def get_judge(settings=None) -> CompositeJudge               # raises if provider set but no key
```

### 5.3 `conflict/deterministic.py`
`Hint(relation, confidence, key, evidence)`; `check(subject_text, candidate) -> Hint | None` (pagination style, page-size value, identical statement; extensible).

### 5.4 `conflict/cache.py` + `judgment_cache` table
```sql
CREATE TABLE IF NOT EXISTS judgment_cache (
    key         text PRIMARY KEY,              -- sha256(model | subject_text | candidate_text)
    model       text NOT NULL,
    judgment    jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
```
```python
def cache_key(model, subject_text, candidate_text) -> str
async def get_cached(conn, key) -> Judgment | None
async def put_cached(conn, key, model, judgment) -> None
```
Cache is consulted before judging a pair and written after; keyed per model so a model change invalidates naturally. Deterministic-only path uses `model="deterministic"`.

### 5.5 `conflict/retrieval.py`
`async candidates(conn, project_id, scope_tags, embedding, top_k, exclude_decision_id=None, subject_text="") -> list[Record]` — stage 1 scope overlap (exclude self), stage 2 rank by **keyword overlap desc, then vector distance asc (NULLS LAST)**, limit `top_k`.

### 5.6 `conflict/pipeline.py`
```python
Subject(text, scope_tags, embedding, subject_type, subject_ref)
Conflict(candidate_id, relation, severity, explanation, evidence, confidence)
DetectionResult(conflicts: list[Conflict], degraded: bool, coverage: str)   # coverage: "full"|"deterministic-only"
async detect(conn, project_id, subject, *, judge, top_k, threshold, persist) -> DetectionResult
    # per candidate: cache lookup -> judge -> cache store; evidence gate + threshold;
    # severity from confidence/backstop; persist conflict rows + event when persist=True.
    # coverage = "deterministic-only" if judge has no llm OR any candidate degraded; else "full".
```

### 5.7 `conflict/__init__.py`
`async check_on_insert(conn, project_id, decision_row, *, judge=None, threshold=None, top_k=None) -> dict` → `{"conflicts": [...], "degraded": bool, "coverage": str}` (builds a decision `Subject`, `detect(persist=True)`).

## 6. Wiring

- **`record_decision`**: compute embedding before the txn; store via `repo.insert_decision(embedding=...)`; `check_on_insert` returns real conflicts; response gains `conflicts`, `degraded`, `coverage`. Warn, never block.
- **`check_intent`** (new tool): embed planned action; `detect(persist=False)`; returns `{conflicts, degraded, coverage, inbox}`; raises `ValueError` on empty scope; no persistence; never blocks.
- **DB**: `register_vector` in pool `init`; `insert_decision(embedding=None)`; `insert_conflict(...)`; `judgment_cache` table + `cache.py`.
- **server.py**: register `check_intent` MCP tool with docstring.

## 7. Prompt-injection guard (LLMJudge)

System prompt states the two blocks are DATA to compare, never instructions; candidate/subject wrapped in delimited tags; `evidence` must be a verbatim substring or the model must return `unclear`. (§11.)

## 8. Eval harness (`keel/evals/`)

- `dataset.jsonl` — labelled pairs `{subject, candidate, expected_relation}` across pagination/schema/contract/policy/naming, including hard negatives (consistent-but-similar) to measure precision.
- `runner.py` — `async evaluate(judge, dataset) -> Metrics(precision, recall, f1, n)` over the hard relations.
- **Hermetic test**: deterministic judge meets a documented floor on the set (no network).
- **Gated test** (`@pytest.mark.llm`, skipped without `ANTHROPIC_API_KEY`): the real LLM judge meets a higher floor; prints metrics. This is how reliability claims are earned.

## 9. Testing strategy (honest + hermetic)

- **conftest**: an autouse fixture sets `KEEL_LLM_PROVIDER=none` for the default suite, so unit/integration tests run on the deterministic judge — fast, free, offline. Pipeline tests inject fake judges to exercise merge/fail-open/evidence-gate paths deterministically.
- **LLMJudge unit tests**: mocked `create` — verify delimited/guarded prompt and structured-response mapping; no network.
- **Fail-open test**: a judge whose LLM raises → `degraded=True`, deterministic result used, no exception.
- **Backstop test**: LLM says `consistent` but deterministic finds `contradicts` → conflict still emitted.
- **Cache test**: second identical judgment served from cache (judge called once).
- **Live tests** (`llm` marker): real provider, gated by key — construction, one real judgment, and the eval floor.
- Marker registered in `pyproject.toml`; `pytest` skips `llm` tests without a key.

## 10. Out of scope (named follow-ups)

Complexity **router** across multiple models (the `select_model` seam is the hook — next slice); alerts/propagation (§8); drift / `report_activity` (§7.1 sources); hot-path local classifier (§7.2); dashboard; lesson loop (§9.1); semantic-embedding provider tuning + a larger eval corpus.

## 11. Risks

- **Lock held during LLM judgment**: the per-scope advisory lock is held through the cold-path LLM call (intended serialization, §7.1); `record_decision` is rare, timeout bounds it, and fail-open prevents a stuck write. Embedding runs outside the lock.
- **Deterministic embedder is non-semantic**: mitigated by keyword-first retrieval ranking and judging all scope actives up to `top_k`; semantic provider improves large scopes.
- **LLM cost/latency per check**: bounded by cache + timeout + `top_k`; the router slice adds model tiering. Measured by the eval harness before any external claim.
- **Provider misconfig**: fail loud at construction (missing key/model), never mid-transaction.
