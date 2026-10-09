import os
import pytest
from keel.conflict.judge import LLMJudge
from keel.evals.runner import load_dataset, evaluate

pytestmark = [pytest.mark.llm,
              pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                                 reason="ANTHROPIC_API_KEY not set")]


async def test_real_contradiction(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "anthropic")
    out = await LLMJudge().judge(
        "orders API should use offset pagination",
        {"statement": "orders API uses cursor-based pagination", "rationale": ""})
    assert out.relation in {"contradicts", "supersedes"}
    assert out.evidence and out.evidence in "orders API uses cursor-based pagination"


async def test_eval_floor(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "anthropic")
    m = await evaluate(LLMJudge(), load_dataset())
    print(f"LLM eval precision={m.precision:.2f} recall={m.recall:.2f} f1={m.f1:.2f} n={m.n}")
    assert m.f1 >= 0.7
