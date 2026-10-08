from keel.principal import Principal
from keel.inbox import build_inbox


async def test_inbox_stable_empty_shape(conn):
    p = Principal(project_id="p", person_id="u", session_id="s")
    box = await build_inbox(conn, p)
    assert box == {"alerts": [], "handoffs": [], "new_lessons": []}
