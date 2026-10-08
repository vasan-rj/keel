from keel.principal import Principal


async def build_inbox(conn, principal: Principal) -> dict:
    # Slice 1: stable shape, no sources yet. Propagation slice fills alerts/handoffs;
    # lessons slice fills new_lessons.
    return {"alerts": [], "handoffs": [], "new_lessons": []}
