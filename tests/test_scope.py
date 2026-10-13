import pytest
from keel.scope import (
    normalize_tag,
    normalize_tags,
    reconcile,
    levenshtein_distance,
    tag_similarity_with_dist,
    find_canonical_tag,
)


def test_levenshtein_distance():
    assert levenshtein_distance("order", "order") == 0
    assert levenshtein_distance("order", "orders") == 1
    assert levenshtein_distance("orders", "order") == 1
    assert levenshtein_distance("user", "uses") == 1
    assert levenshtein_distance("checkout", "checkut") == 1
    assert levenshtein_distance("", "test") == 4
    assert levenshtein_distance("test", "") == 4


def test_tag_similarity_with_dist():
    # Exact match
    sim, dist = tag_similarity_with_dist("api:orders", "api:orders")
    assert sim == 1.0 and dist == 0

    # Near-duplicates (order vs orders)
    sim, dist = tag_similarity_with_dist("api:order", "api:orders")
    assert sim > 0.8 and dist == 1

    # False merge prevention (user vs uses)
    sim, dist = tag_similarity_with_dist("api:user", "api:uses")
    assert sim == 0.75 and dist == 1

    # Cross domain
    sim, _ = tag_similarity_with_dist("api:order", "db:order")
    assert sim == 0.0


def test_find_canonical_tag():
    existing = {"api:order", "db:user"}
    assert find_canonical_tag("api:orders", existing) == "api:order"
    assert find_canonical_tag("api:order", existing) == "api:order"
    assert find_canonical_tag("api:uses", existing) == "api:uses"
    assert find_canonical_tag("db:users", existing) == "db:user"
    assert find_canonical_tag("ui:checkout", existing) == "ui:checkout"


def test_normalize_collapses_case_and_space():
    assert normalize_tag("API: Orders") == "api:orders"
    assert normalize_tag("  Schema:User ") == "schema:user"


def test_normalize_empty_raises():
    with pytest.raises(ValueError):
        normalize_tag("   ")


def test_normalize_tags_dedupes_preserving_order():
    assert normalize_tags(["api:orders", "API: Orders", "ui:checkout"]) == ["api:orders", "ui:checkout"]


def test_normalize_tags_all_blank_raises():
    with pytest.raises(ValueError):
        normalize_tags(["  ", ""])


async def test_reconcile_reuses_existing_normalized(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:orders"],
    )
    assert await reconcile(conn, pid, ["API: Orders"]) == ["api:orders"]


async def test_reconcile_merges_near_duplicate_plural(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_fuzzy1') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:order"],
    )
    # api:orders should automatically merge to canonical api:order
    assert await reconcile(conn, pid, ["api:orders"]) == ["api:order"]


async def test_reconcile_merges_near_duplicate_singular(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_fuzzy2') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:orders"],
    )
    # api:order should automatically merge to canonical api:orders
    assert await reconcile(conn, pid, ["api:order"]) == ["api:orders"]


async def test_reconcile_no_false_merge_user_and_uses(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_false_merge') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:user"],
    )
    # api:uses must NOT be falsely merged into api:user
    assert await reconcile(conn, pid, ["api:uses"]) == ["api:uses"]


async def test_reconcile_preserves_distinct_existing_tags(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_distinct') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d1',$2)",
        pid, ["api:user"],
    )
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d2',$2)",
        pid, ["api:uses"],
    )
    # When both exist, exact matches should preserve both as distinct
    assert await reconcile(conn, pid, ["api:user"]) == ["api:user"]
    assert await reconcile(conn, pid, ["api:uses"]) == ["api:uses"]


async def test_reconcile_configurable_threshold_strict(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_strict') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:order"],
    )
    # With threshold=1.0 (strict), api:orders does NOT merge into api:order
    assert await reconcile(conn, pid, ["api:orders"], threshold=1.0) == ["api:orders"]
    # With default threshold, it DOES merge
    assert await reconcile(conn, pid, ["api:orders"]) == ["api:order"]


async def test_reconcile_configurable_threshold_permissive(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_permissive') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:user"],
    )
    # With threshold=0.7 (permissive), api:uses merges to api:user
    assert await reconcile(conn, pid, ["api:uses"], threshold=0.7) == ["api:user"]
    # With default threshold=0.8, it does NOT merge
    assert await reconcile(conn, pid, ["api:uses"]) == ["api:uses"]


async def test_reconcile_env_var_configurable_threshold(conn, monkeypatch):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_env') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:order"],
    )
    monkeypatch.setenv("KEEL_SCOPE_FUZZY_THRESHOLD", "1.0")
    assert await reconcile(conn, pid, ["api:orders"]) == ["api:orders"]

    monkeypatch.setenv("KEEL_SCOPE_FUZZY_THRESHOLD", "0.8")
    assert await reconcile(conn, pid, ["api:orders"]) == ["api:order"]


async def test_reconcile_cross_domain_never_merges(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_cross_domain') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:order"],
    )
    # db:order has the same entity name but different domain prefix -> must NOT merge
    assert await reconcile(conn, pid, ["db:order"]) == ["db:order"]


async def test_reconcile_typo_correction(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_typo') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:checkout"],
    )
    # Missing 'o' in checkout should merge into existing api:checkout
    assert await reconcile(conn, pid, ["api:checkut"]) == ["api:checkout"]


async def test_reconcile_dedupes_collapsed_tags(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p_dedupe') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:order"],
    )
    # Multiple near-duplicates in single input collapse to single canonical tag
    assert await reconcile(conn, pid, ["api:order", "api:orders"]) == ["api:order"]
