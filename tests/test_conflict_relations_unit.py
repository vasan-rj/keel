from unittest.mock import AsyncMock

import pytest

from keel.conflict import pipeline
from keel.conflict.judge import Judgment


@pytest.mark.parametrize("relation,expected", [("duplicates", 0), ("contradicts", 1), ("supersedes", 1)])
async def test_only_actionable_relations_are_returned(monkeypatch, relation, expected):
    candidate = {"id": "existing", "statement": "use cursor pagination", "rationale": "scales"}
    monkeypatch.setattr(pipeline, "candidates", AsyncMock(return_value=[candidate]))
    judge = AsyncMock()
    judge.judge.return_value = Judgment(
        relation=relation, confidence=0.99, explanation="comparison", evidence=candidate["statement"])
    result = await pipeline.detect(
        None, "project", pipeline.Subject("use cursor pagination", ["api:orders"], None,
                                         "planned_action", "planned"),
        judge=judge, top_k=8, threshold=0.6, persist=False, use_cache=False)
    assert len(result.conflicts) == expected
