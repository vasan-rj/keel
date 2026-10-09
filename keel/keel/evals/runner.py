import json
from pathlib import Path
from dataclasses import dataclass

_DEFAULT = Path(__file__).parent / "dataset.jsonl"
_HARD = {"contradicts", "duplicates", "supersedes"}


@dataclass
class Metrics:
    precision: float; recall: float; f1: float; n: int


def load_dataset(path=None) -> list[dict]:
    p = Path(path) if path else _DEFAULT
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


async def evaluate(judge, dataset) -> Metrics:
    tp = fp = fn = 0
    for row in dataset:
        out = await judge.judge(row["subject"], {"statement": row["candidate"], "rationale": ""})
        if isinstance(out, tuple):
            out = out[0]
        pred, exp = out.relation in _HARD, row["expected"] == "hard"
        tp += pred and exp; fp += pred and not exp; fn += (not pred) and exp
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return Metrics(p, r, f1, len(dataset))
