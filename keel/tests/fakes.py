from keel.conflict.judge import Judgment


class ScriptedJudge:
    """Returns contradicts (citing the candidate) when subject+candidate look like
    cursor/offset pagination; else consistent."""
    async def judge(self, subject_text, candidate):
        s, c = subject_text.lower(), candidate["statement"].lower()
        if ("offset" in s and "cursor" in c) or ("cursor" in s and "offset" in c):
            return Judgment(relation="contradicts", confidence=0.9,
                            explanation="pagination style differs", evidence=candidate["statement"])
        return Judgment(relation="consistent", confidence=0.1, explanation="ok", evidence="")


class ErroringJudge:
    async def judge(self, subject_text, candidate):
        raise RuntimeError("provider down")


class CountingJudge:
    def __init__(self): self.n = 0
    async def judge(self, subject_text, candidate):
        self.n += 1
        return Judgment(relation="contradicts", confidence=0.9, explanation="e",
                        evidence=candidate["statement"])
