import re

_WS = re.compile(r"\s+")


def normalize_tag(tag: str) -> str:
    out = _WS.sub("", tag.strip().lower())
    if not out:
        raise ValueError("scope tag is empty after normalization")
    return out


def normalize_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tags or []:
        try:
            n = normalize_tag(t)
        except ValueError:
            continue
        if n not in seen:
            seen.append(n)
    if not seen:
        raise ValueError("at least one non-empty scope tag is required")
    return seen


async def reconcile(conn, project_id, tags: list[str]) -> list[str]:
    normalized = normalize_tags(tags)
    rows = await conn.fetch(
        "SELECT DISTINCT unnest(scope_tags) AS tag FROM decision WHERE project_id = $1",
        project_id,
    )
    existing = {r["tag"] for r in rows}
    # Slice 1: existing tags are already stored normalized, so an exact match
    # reuses the canonical tag (identity). The `existing` set is wired now so a
    # later slice can drop in fuzzy matching (edit distance) without changing
    # callers. `_` keeps the lookup live without an unused-variable lint.
    _ = existing
    return normalized
