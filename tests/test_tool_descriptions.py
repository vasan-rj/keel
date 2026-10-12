from keel.server import mcp


async def test_all_tools_have_descriptions():
    tools = {t.name: t for t in await mcp.list_tools()}
    expected = {"register_session", "get_context", "record_decision", "check_intent",
                "declare_dependency", "claim_scope", "release_scope", "list_alerts",
                "ack_alert", "resolve_conflict",
                "create_handoff", "accept_handoff", "decline_handoff",
                "report_activity", "record_outcome", "rate_alert", "request_decision",
                "record_lesson"}
    assert set(tools) == expected
    for name, t in tools.items():
        assert t.description and len(t.description.strip()) >= 20, f"{name} missing description"


async def test_descriptions_mention_core_behavior():
    tools = {t.name: t.description.lower() for t in await mcp.list_tools()}
    assert "scope" in tools["get_context"]
    assert "conflict" in tools["record_decision"]
    assert "session" in tools["register_session"]
    assert "planned" in tools["check_intent"] or "before you act" in tools["check_intent"]
