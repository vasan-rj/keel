from keel.evals.runner import load_dataset, evaluate, Metrics
from keel.conflict.judge import Judgment


class PerfectJudge:
    def __init__(self, ds): self.exp = {(r["subject"], r["candidate"]): r["expected"] for r in ds}
    async def judge(self, subject_text, candidate):
        hard = self.exp[(subject_text, candidate["statement"])] == "hard"
        return Judgment(relation="contradicts" if hard else "consistent",
                        confidence=0.9, explanation="e",
                        evidence=candidate["statement"] if hard else "")


async def test_dataset_loads():
    ds = load_dataset()
    assert len(ds) >= 8 and {"subject", "candidate", "expected"} <= set(ds[0])


async def test_runner_metrics_perfect():
    ds = load_dataset()
    m = await evaluate(PerfectJudge(ds), ds)
    assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0 and m.n == len(ds)
