async def test_schema_applies_and_core_tables_exist(conn):
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )
    names = {r["table_name"] for r in rows}
    assert {"project", "person", "participant", "decision", "event"} <= names


async def test_vector_extension_present(conn):
    row = await conn.fetchrow("SELECT 1 FROM pg_extension WHERE extname='vector'")
    assert row is not None
