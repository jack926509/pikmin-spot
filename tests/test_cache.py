from src.cache import LRUResultCache
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
