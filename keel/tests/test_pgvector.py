from pgvector import Vector


async def test_vector_roundtrip_and_distance(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p') RETURNING id")
    v = Vector([0.0] * 1535 + [1.0])
    await conn.execute("INSERT INTO decision (project_id, statement, scope_tags, embedding) "
                       "VALUES ($1,'d',$2,$3)", pid, ["s"], v)
    dist = await conn.fetchval("SELECT embedding <=> $1 FROM decision WHERE project_id=$2", v, pid)
    assert dist is not None and abs(dist) < 1e-6
