import pytest
from keel.conflict.judge import Judgment, LLMJudge, get_judge


def _c(s, r=""): return {"statement": s, "rationale": r}


def test_get_judge_none_when_provider_none(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "none")
    assert get_judge() is None


def test_get_judge_fail_loud_without_key(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_judge()


def test_get_judge_openrouter_key(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_judge()


def test_prompt_delimited_and_guarded():
    msgs = LLMJudge(create=lambda **k: None).build_messages("offset pagination", _c("cursor pagination"))
    joined = " ".join(m["content"] for m in msgs).lower()
    assert "data" in joined and "instruction" in joined
    assert "cursor pagination" in joined and "offset pagination" in joined


async def test_judge_maps_structured_response():
    exp = Judgment(relation="contradicts", confidence=0.8, explanation="e", evidence="cursor pagination")
    async def fake(**k): return exp
    out = await LLMJudge(create=fake).judge("offset", _c("cursor pagination"))
    assert out is exp


async def test_judge_timeout_raises():
    import asyncio
    async def slow(**k):
        await asyncio.sleep(1); return None
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await LLMJudge(timeout_s=0.05, create=slow).judge("x", _c("y"))
