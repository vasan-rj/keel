# Conflict Engine Slice — Design Spec

**Version:** 0.1 · **Last updated:** 2026-10-09 · **Status:** approved for planning

Implements the real conflict-detection pipeline behind the Slice-1 `conflict.check_on_insert` stub. Source of truth: `context/ARCHITECTURE.md` §7 (pipeline), §7.1 (serialized insert), §7.2 (hot/cold path), §1 (principles), §4 (data model), §5 (tools). Builds on Slice 1 (`keel/`, 38 tests).

## 1. Goal

Detect contradictions between a new decision (or a planned action) and the active decisions on overlapping scope, cite evidence, persist conflict records, and surface them — warning, never blocking. Wire it into `record_decision` and a new `check_intent` tool.

## 2. Principles honored

- **Evidence or silence** (§1.4): a conflict is emitted only if its explanation cites the candidate decision's text. Low confidence → `unclear` ("possible conflict"), never a hard flag.
- **Humans resolve; Keel flags** (§1.3): warn only; no block, no auto-overwrite.
- **Determinism where it is cheap** (§1): deterministic checks run before the probabilistic judge and backstop it; the default judge/embedder are deterministic so the engine runs offline with reproducible output.
- **Decisions are data, never instructions** (§1): candidate decision text injected into a judge prompt is clearly delimited and treated as untrusted.
- **Serialized per scope** (§7.1): detection runs inside the same per-scope-advisory-locked transaction as the decision insert (Slice 1 already locks).

## 3. Third-party libraries (reuse, not rebuild)

| Concern | Library | Notes |
|---|---|---|
| Multi-provider LLM (completions + embeddings) | **litellm** | async `acompletion`/`aembedding`; provider chosen by model string (anthropic/openai/openrouter). Lazy-imported. |
| Structured judge output | **instructor** (`from_provider("litellm/<model>", async_client=True)`, `response_model=Judgment`) | validated Pydantic output + retry on schema failure. Lazy-imported. |
| Vector type + similarity | **pgvector** (`pgvector.asyncpg.register_vector`, `pgvector.Vector`, `<=>` cosine) | registered in the asyncpg pool `init` hook. Core dependency. |

`litellm` + `instructor` live in an optional `[llm]` extra and are imported **only** when a provider is configured. Default (`KEEL_LLM_PROVIDER=none`, `KEEL_EMBEDDING_PROVIDER=deterministic`) imports neither, so the core install and the whole test suite stay offline and hermetic. No memory-layer framework (Mem0/Zep/etc.) — OPEN_QUESTIONS #6 (own the store); such layers are possible later *adapters* for candidate ingestion / outcome analytics, never the core store.

## 4. Configuration (env, all optional)

| Var | Default | Meaning |
|---|---|---|
| `KEEL_LLM_PROVIDER` | `none` | `none` → DeterministicJudge; else litellm provider (`anthropic`/`openai`/`openrouter`). |
| `KEEL_LLM_MODEL` | — | litellm model string, e.g. `anthropic/claude-sonnet-...`. Required when provider ≠ none. |
| `KEEL_EMBEDDING_PROVIDER` | `deterministic` | `deterministic` → DeterministicEmbedder; else litellm. |
| `KEEL_EMBEDDING_MODEL` | — | e.g. `openai/text-embedding-3-small` (1536 dims, matches schema). |
| `KEEL_CONFLICT_CONFIDENCE_THRESHOLD` | `0.6` | below → `unclear`/possible, not a hard conflict. |
| `KEEL_CONFLICT_TOPK` | `5` | candidates retrieved for judgment. |

Provider API keys come from each provider's standard env var (litellm reads them). Settings extend `keel/config.py`.

## 5. Components and interfaces

New package `keel/keel/conflict/` (replaces the `conflict.py` stub; `__init__` re-exports `check_on_insert` so `record_decision`'s import is unchanged) and `keel/keel/llm/`.

### 5.1 `keel/llm/embeddings.py`
```python
class Embedder(Protocol):
    dim: int
    async def embed(self, text: str) -> "pgvector.Vector": ...

class DeterministicEmbedder:          # default; dim=1536
    # sha256(text)-seeded RNG -> 1536 floats in [-1,1], L2-normalized.
    # Stable: same text -> same vector (distance 0); not semantic.

class ProviderEmbedder:               # litellm aembedding; lazy import
    # dim from model (default 1536)

def get_embedder() -> Embedder        # from config
```

### 5.2 `keel/conflict/judge.py`
```python
RELATIONS = ("contradicts", "duplicates", "supersedes", "consistent", "unclear")

class Judgment(BaseModel):
    relation: Literal[RELATIONS]
    confidence: float                 # 0..1
    explanation: str
    evidence: str                     # must quote candidate text (evidence gate)

class Judge(Protocol):
    async def judge(self, subject: "Subject", candidate: dict) -> Judgment: ...

class DeterministicJudge:             # default
    # consumes deterministic-check hints + simple heuristics -> Judgment with
    # explanation prose and evidence = the candidate statement substring it keys on.

class LLMJudge:                       # instructor+litellm; lazy import
    # delimited, injection-guarded prompt; response_model=Judgment.

def get_judge() -> Judge              # from config
```

### 5.3 `keel/conflict/deterministic.py`
```python
@dataclass
class Hint:
    relation: str        # contradicts | duplicates | consistent
    confidence: float
    key: str             # what matched, e.g. "pagination-style"
    evidence: str        # candidate substring

def check(subject_text: str, candidate: dict) -> Hint | None
# Rules (ordered): pagination style cursor vs offset; page-size value mismatch
# on a shared key; near-identical statement -> duplicates. Returns None if no rule fires.
```

### 5.4 `keel/conflict/retrieval.py`
```python
async def candidates(conn, project_id, scope_tags: list[str],
                     embedding: "pgvector.Vector", top_k: int,
                     exclude_decision_id=None) -> list[asyncpg.Record]
# Stage 1: active decisions with overlapping scope_tags (&&), exclude self.
# Stage 2: ORDER BY combined rank = vector distance (embedding <=> $) blended
#          with keyword overlap; LIMIT top_k.
```

### 5.5 `keel/conflict/pipeline.py`
```python
@dataclass
class Subject:
    text: str                        # statement + rationale
    scope_tags: list[str]
    embedding: "pgvector.Vector"
    subject_type: str                # "decision" | "planned_action"
    subject_ref: str                 # decision id, or a synthetic ref for planned

@dataclass
class Conflict:
    candidate_id: str; relation: str; severity: str
    explanation: str; evidence: str; confidence: float

async def detect(conn, project_id, subject: Subject, *, persist: bool,
                 judge: Judge, top_k: int, threshold: float) -> list[Conflict]
# 1 scope filter + 2 retrieval (retrieval.candidates)
# 3 deterministic.check -> hint per candidate
# 4 judge.judge per candidate (hint passed in for the deterministic judge)
# 5 evidence gate: keep only relation in {contradicts,duplicates,supersedes}
#   AND confidence >= threshold AND evidence is a non-empty substring of the
#   candidate statement/rationale. Below threshold -> relation downgraded to
#   "unclear" and DROPPED from hard conflicts (returned as possible only).
# severity: deterministic high-confidence hint -> "high"; else map confidence.
# persist=True: INSERT conflict rows (decision_a_id=candidate, subject_type,
#   subject_ref, relation, severity, explanation, status='open') + append event.
```

### 5.6 `keel/conflict/__init__.py`
```python
async def check_on_insert(conn, project_id, decision_row) -> list[dict]
# builds a Subject from decision_row (embedding already stored), calls detect(
# persist=True), returns conflicts as dicts for record_decision's response.
```

## 6. Wiring

### 6.1 `record_decision` (modify `keel/keel/tools/record_decision.py`)
- Compute `embedding = await get_embedder().embed(statement + "\n" + rationale)` **before** opening the transaction (an embedding provider call must not run under the scope lock; the deterministic embedder is instant anyway).
- Pass `embedding` to `repo.insert_decision` (new param → stored in `decision.embedding`).
- `check_on_insert` now returns real conflicts (persisted in-txn). Response `conflicts` carries them. Still warns; status/flow unchanged.

### 6.2 `check_intent` (new `keel/keel/tools/check_intent.py` + register in `server.py`)
```python
async def check_intent(pool, principal, *, planned_action: str,
                       scope_tags: list[str]) -> dict
# normalize scope, embed planned_action, run detect(persist=False) in a read
# transaction, return {"conflicts": [...], "inbox": {...}}. No decision row,
# no conflict rows, never blocks.
```
MCP tool wrapper + docstring in `server.py`; principal from the auth contextvar.

### 6.3 DB
- Register pgvector on every pooled connection: add `init=register_vector` to `asyncpg.create_pool` in `keel/keel/db/pool.py`.
- `repo.insert_decision` gains `embedding` param (`decision.embedding` column already exists).
- New `repo.insert_conflict(...)`.

## 7. Prompt-injection guard (LLMJudge)

Candidate and subject text are wrapped in clearly delimited blocks labelled untrusted data; the system prompt states the text is data to compare, never instructions to follow, and that the judge must return only the `Judgment` schema. (ARCHITECTURE §11.)

## 8. Testing (TDD, deterministic path, hermetic)

- Deterministic embedder: same text → distance 0; different text → >0; dim 1536; stored + round-tripped via pgvector.
- Retrieval: scope filter excludes non-overlapping scopes and self; top_k respected; ordering returns the overlapping candidate.
- Deterministic checks: `cursor` vs `offset` → contradicts hint with evidence; page-size 20 vs 50 on shared key → contradicts; identical statement → duplicates; unrelated → None.
- Evidence gate: a judgment whose `evidence` is not a substring of the candidate is dropped; low confidence → not a hard conflict.
- `record_decision`: cursor-then-offset in `api:orders` → one persisted conflict (`contradicts`) with evidence citing the first decision; `conflicts` returned; event chain still valid; serialized insert still holds; embedding persisted.
- `check_intent`: planned offset action vs active cursor decision → conflict returned, **no** decision row, **no** conflict row persisted; unrelated scope → empty.
- LLMJudge: with provider configured + litellm/instructor **mocked**, builds the delimited prompt and maps a mocked structured response to `Judgment`. No network in tests.
- Config: defaults select DeterministicJudge + DeterministicEmbedder; provider set selects LLM/provider variants (construction only, mocked).

## 9. Out of scope (named follow-ups)

Alerts/propagation (§8) and the `alert` rows; drift / `report_activity` edit-hook path (§7.1 sources); hot-path local classifier (§7.2); complexity router across models (Q7) — the `[llm]` layer is the seam for it; dashboard; lesson loop (§9.1); real embedding/LLM provider tuning + the labelled eval set (§7).

## 10. Risks

- **Lock held during judgment:** with an LLM judge, the per-scope advisory lock is held through the (cold-path) LLM call — this is the intended serialization (§7.1), acceptable because `record_decision` is rare. The embedding call is moved outside the lock. Documented, not mitigated further this slice.
- **Deterministic embedder is non-semantic:** vector retrieval is structurally exercised but semantic quality needs a real embedder; scope + keyword carry the signal offline and in the demo.
- **litellm/instructor are optional + lazy:** a misconfigured provider (missing model/key) must raise a clear error at judge/embedder construction, not at call time mid-transaction.
