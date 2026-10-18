from datetime import datetime, timedelta, timezone
from keel import repo


async def test_device_grant_roundtrip_and_update(conn, db_pool):
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    g = await repo.insert_device_grant(conn, device_code_hash="dch", user_code="ABCD-2345",
                                       harness="claude-code", label="laptop", expires_at=exp)
    assert g["status"] == "pending"
    assert (await repo.get_device_grant_by_user_code(conn, "ABCD-2345"))["id"] == g["id"]
    await repo.update_device_grant(conn, g["id"], status="denied")
    assert (await repo.get_device_grant_by_code_hash(conn, "dch"))["status"] == "denied"
