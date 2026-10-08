import pytest
from keel.scope import normalize_tag, normalize_tags, reconcile


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
