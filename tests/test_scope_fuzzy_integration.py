import hashlib
import pytest
from keel import repo
from keel.server import call_tool_for_test


async def _seed_principals(conn):
    pid = await repo.upsert_project(conn, "demo")
    await repo.upsert_person(
        conn, pid, "vasan", hashlib.sha256(b"dev-token").hexdigest()
    )
    await repo.upsert_person(
        conn, pid, "teammate", hashlib.sha256(b"teammate-token").hexdigest()
    )
    return pid


async def test_cross_session_fuzzy_reconcile_record_decision(conn, db_pool):
    """End-to-end integration test simulating two sessions:
    - Session A records a decision with scope 'api:order'
    - Session B records a decision with near-duplicate 'api:orders'
    - Verifies that Session B's tag is automatically reconciled to 'api:order'
    - Verifies that get_context across sessions retrieves both decisions
    """
    await _seed_principals(conn)

    # 1. Session A registers and records with canonical tag 'api:order'
    reg_a = await call_tool_for_test(
        "dev-token",
        "session-A",
        "register_session",
        {"harness": "cursor", "tier": "deep", "session_id": "session-A"},
    )
    assert "participant_id" in reg_a

    res_a = await call_tool_for_test(
        "dev-token",
        "session-A",
        "record_decision",
        {
            "statement": "Use cursor pagination for orders",
            "rationale": "Scales better than offset",
            "scope_tags": ["api:order"],
        },
    )
    assert res_a["status"] == "active"
    assert res_a["scope_tags"] == ["api:order"]

    # 2. Session B registers and records with near-duplicate 'api:orders'
    reg_b = await call_tool_for_test(
        "teammate-token",
        "session-B",
        "register_session",
        {"harness": "claude-code", "tier": "deep", "session_id": "session-B"},
    )
    assert "participant_id" in reg_b

    res_b = await call_tool_for_test(
        "teammate-token",
        "session-B",
        "record_decision",
        {
            "statement": "Order items limited to 100 per page",
            "rationale": "Limits payload size",
            "scope_tags": ["api:orders"],
        },
    )
    assert res_b["status"] == "active"
    # Near-duplicate 'api:orders' must be automatically reconciled to canonical 'api:order'
    assert res_b["scope_tags"] == ["api:order"]

    # 3. Session B fetches context for 'api:order' and gets both decisions
    ctx = await call_tool_for_test(
        "teammate-token",
        "session-B",
        "get_context",
        {"scope_tags": ["api:order"]},
    )
    decision_ids = {d["id"] for d in ctx["decisions"]}
    assert res_a["decision_id"] in decision_ids
    assert res_b["decision_id"] in decision_ids


async def test_cross_session_false_merge_prevention(conn, db_pool):
    """Verifies that distinct tags like 'api:user' and 'api:uses' are NOT merged."""
    await _seed_principals(conn)

    # Session A records 'api:user'
    await call_tool_for_test(
        "dev-token",
        "session-user",
        "register_session",
        {"harness": "cursor", "tier": "deep", "session_id": "session-user"},
    )
    res_user = await call_tool_for_test(
        "dev-token",
        "session-user",
        "record_decision",
        {
            "statement": "User identity model schema",
            "rationale": "Auth requirements",
            "scope_tags": ["api:user"],
        },
    )
    assert res_user["scope_tags"] == ["api:user"]

    # Session B records 'api:uses' (e.g. usage statistics)
    await call_tool_for_test(
        "teammate-token",
        "session-uses",
        "register_session",
        {"harness": "cursor", "tier": "deep", "session_id": "session-uses"},
    )
    res_uses = await call_tool_for_test(
        "teammate-token",
        "session-uses",
        "record_decision",
        {
            "statement": "API usage limits tracking",
            "rationale": "Quota management",
            "scope_tags": ["api:uses"],
        },
    )
    # Must NOT merge into api:user
    assert res_uses["scope_tags"] == ["api:uses"]
