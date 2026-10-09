from keel.conflict.cache import cache_key, get_cached, put_cached
from keel.conflict.judge import Judgment


def test_cache_key_model_scoped():
    assert cache_key("m1", "s", "c") == cache_key("m1", "s", "c")
    assert cache_key("m1", "s", "c") != cache_key("m2", "s", "c")


async def test_cache_roundtrip(conn):
    k = cache_key("m1", "s", "c")
    assert await get_cached(conn, k) is None
    await put_cached(conn, k, "m1", Judgment(relation="contradicts", confidence=0.9,
                                             explanation="e", evidence="c"))
    got = await get_cached(conn, k)
    assert got.relation == "contradicts" and got.evidence == "c"
