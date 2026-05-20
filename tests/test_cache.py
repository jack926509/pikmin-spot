from src.cache import InFlightSet, LRUResultCache
from src.models import Coords, PlaceCandidates


def _make(name: str = "X") -> tuple[PlaceCandidates, Coords]:
    return (
        PlaceCandidates(candidates=[name]),
        Coords(lat=1.0, lng=2.0, source="x", matched_query=name),
    )


def test_cache_basic_put_get():
    cache = LRUResultCache(max_entries=2)
    place, coords = _make()
    cache.put(b"image_a", place, coords)
    got = cache.get(b"image_a")
    assert got is not None
    p, c = got
    assert p.candidates == ["X"]
    assert c.lat == 1.0


def test_cache_miss_returns_none():
    cache = LRUResultCache()
    assert cache.get(b"unknown") is None


def test_cache_evicts_oldest_when_full():
    cache = LRUResultCache(max_entries=2)
    place, coords = _make()
    cache.put(b"a", place, coords)
    cache.put(b"b", place, coords)
    cache.put(b"c", place, coords)
    assert cache.get(b"a") is None  # evicted
    assert cache.get(b"b") is not None
    assert cache.get(b"c") is not None


def test_cache_lru_promotes_on_access():
    cache = LRUResultCache(max_entries=2)
    place, coords = _make()
    cache.put(b"a", place, coords)
    cache.put(b"b", place, coords)
    cache.get(b"a")  # promote a
    cache.put(b"c", place, coords)  # should evict b, not a
    assert cache.get(b"a") is not None
    assert cache.get(b"b") is None
    assert cache.get(b"c") is not None


def test_cache_keyed_by_content_hash():
    cache = LRUResultCache()
    place, coords = _make()
    cache.put(b"image_a", place, coords)
    # 內容相同的不同 bytes 物件應命中
    same_bytes = bytes(b"image_a")
    assert cache.get(same_bytes) is not None


def test_cache_overwrite_existing_key():
    cache = LRUResultCache()
    p1, c1 = _make("First")
    p2, c2 = _make("Second")
    cache.put(b"key", p1, c1)
    cache.put(b"key", p2, c2)
    assert len(cache) == 1
    got = cache.get(b"key")
    assert got is not None
    assert got[0].candidates == ["Second"]


def test_in_flight_acquire_then_release():
    s = InFlightSet()
    assert s.acquire("F1") is True
    assert "F1" in s
    # 第二次同 key 取得失敗(防重)
    assert s.acquire("F1") is False
    s.release("F1")
    assert "F1" not in s
    # 釋放後可再取得
    assert s.acquire("F1") is True


def test_in_flight_empty_key_rejected():
    s = InFlightSet()
    assert s.acquire("") is False
    assert len(s) == 0


def test_in_flight_release_unknown_is_noop():
    s = InFlightSet()
    s.release("never-acquired")  # should not raise
    assert len(s) == 0


def test_in_flight_ttl_auto_releases_stale_entry():
    """模擬 handler 崩潰未呼叫 release —— TTL 過後自動清理,允許再次 acquire。"""
    s = InFlightSet(ttl_sec=0.05)
    assert s.acquire("F1") is True
    assert s.acquire("F1") is False  # 仍 in-flight
    import time as _t
    _t.sleep(0.07)
    # TTL 過後應允許再 acquire(自動 GC)
    assert s.acquire("F1") is True


def test_in_flight_membership_check_triggers_gc():
    s = InFlightSet(ttl_sec=0.05)
    s.acquire("F1")
    assert "F1" in s
    import time as _t
    _t.sleep(0.07)
    assert "F1" not in s
    assert len(s) == 0
