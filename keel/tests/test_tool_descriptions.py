from keel.server import mcp


async def test_all_tools_have_descriptions():
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == {"register_session", "get_context", "record_decision", "check_intent"}
    for name, t in tools.items():
        assert t.description and len(t.description.strip()) >= 20, f"{name} missing description"


async def test_descriptions_mention_core_behavior():
    tools = {t.name: t.description.lower() for t in await mcp.list_tools()}
    assert "scope" in tools["get_context"]
    assert "conflict" in tools["record_decision"]
    assert "session" in tools["register_session"]
    assert "planned" in tools["check_intent"] or "before you act" in tools["check_intent"]
