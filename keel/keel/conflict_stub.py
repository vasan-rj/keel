async def check_on_insert(conn, project_id, decision_row) -> list:
    # Slice 1 stub. The conflict-engine slice implements:
    #   scope filter -> vector+keyword retrieval -> deterministic checks
    #   -> per-candidate LLM judgment -> evidence check (ARCHITECTURE §7).
    # Returning [] keeps the locked-transaction insertion point real so the
    # engine drops in without changing record_decision.
    return []
