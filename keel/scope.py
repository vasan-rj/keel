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


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute the Levenshtein (edit) distance between two strings."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row
    return prev_row[-1]


def tag_similarity_with_dist(tag1: str, tag2: str) -> tuple[float, int]:
    """Calculate the normalized similarity score [0.0, 1.0] and edit distance.

    If both tags have a namespace prefix (`domain:entity`), the domain must match
    exactly, and similarity is evaluated on the entity portion. Cross-domain
    comparisons always return 0.0 similarity.
    """
    if tag1 == tag2:
        return 1.0, 0

    has_colon1 = ":" in tag1
    has_colon2 = ":" in tag2
    if has_colon1 != has_colon2:
        return 0.0, levenshtein_distance(tag1, tag2)

    if has_colon1:
        prefix1, _, entity1 = tag1.partition(":")
        prefix2, _, entity2 = tag2.partition(":")
        if prefix1 != prefix2:
            return 0.0, levenshtein_distance(tag1, tag2)
    else:
        entity1, entity2 = tag1, tag2

    if entity1 == entity2:
        return 1.0, 0

    dist = levenshtein_distance(entity1, entity2)
    max_len = max(len(entity1), len(entity2))
    if max_len == 0:
        return 1.0, 0

    similarity = 1.0 - (dist / max_len)
    return max(0.0, similarity), dist


def find_canonical_tag(
    tag: str,
    existing_tags: set[str] | list[str],
    threshold: float = 0.8,
    max_distance: int | None = None,
) -> str:
    """Find the best matching canonical tag from existing_tags.

    Returns the matching tag from existing_tags if similarity >= threshold and
    edit distance <= max_distance (if specified). Otherwise returns the tag itself.
    Exact matches return immediately.
    """
    if tag in existing_tags:
        return tag

    best_match = None
    best_sim = -1.0
    best_dist = float("inf")

    for candidate in existing_tags:
        sim, dist = tag_similarity_with_dist(tag, candidate)
        if max_distance is not None and dist > max_distance:
            continue
        if sim >= threshold:
            if (
                (sim > best_sim)
                or (sim == best_sim and dist < best_dist)
                or (
                    sim == best_sim
                    and dist == best_dist
                    and (best_match is None or candidate < best_match)
                )
            ):
                best_sim = sim
                best_dist = dist
                best_match = candidate

    return best_match if best_match is not None else tag


async def reconcile(
    conn,
    project_id,
    tags: list[str],
    *,
    threshold: float | None = None,
    max_distance: int | None = None,
) -> list[str]:
    normalized = normalize_tags(tags)
    rows = await conn.fetch(
        "SELECT DISTINCT unnest(scope_tags) AS tag FROM decision WHERE project_id = $1",
        project_id,
    )
    existing = {r["tag"] for r in rows}

    if threshold is None:
        try:
            from keel.config import get_settings
            threshold = get_settings().scope_fuzzy_threshold
        except Exception:
            threshold = 0.8

    reconciled: list[str] = []
    pool = set(existing)

    for tag in normalized:
        canonical = find_canonical_tag(
            tag, pool, threshold=threshold, max_distance=max_distance
        )
        if canonical not in reconciled:
            reconciled.append(canonical)
        pool.add(canonical)

    return reconciled
