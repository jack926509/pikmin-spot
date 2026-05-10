from typing import Optional

import pytest

from src.models import Coords, PlaceCandidates
from src.providers.base import GeocoderProvider, ProviderError
from src.resolver import build_queries, resolve


class _FakeProvider(GeocoderProvider):
    def __init__(self, name: str, behavior):
        self.name = name
        self._behavior = behavior
        self.calls: list[tuple[str, str]] = []

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        self.calls.append((query, hint_country))
        return self._behavior(query, hint_country)


def _hit(name: str, lat: float = 1.0, lng: float = 2.0):
    def _b(q, h):
        return Coords(lat=lat, lng=lng, source=name, matched_query=q)
    return _b


def _miss(_q, _h):
    return None


def _crash(name: str):
    def _b(_q, _h):
        raise ProviderError(f"{name} broken")
    return _b


def test_build_queries_full_combo():
    place = PlaceCandidates(
        candidates=["A", "B", "C"],
        place_name_local="原文",
        country="X-Country",
        region="X-Region",
        search_hints=["hint1"],
    )
    qs = build_queries(place)
    assert qs[0] == "A, X-Region, X-Country"
    assert "A, X-Country" in qs
    assert "B, X-Country" in qs
    assert "C, X-Country" in qs
    assert "原文, X-Country" in qs
    assert "A" in qs
    assert "hint1, X-Country" in qs
    assert len(qs) == len(set(qs))  # no duplicates


def test_build_queries_minimal_returns_only_bare_name():
    place = PlaceCandidates(candidates=["Only"])
    assert build_queries(place) == ["Only"]


def test_build_queries_empty_returns_nothing():
    assert build_queries(PlaceCandidates(candidates=[])) == []


@pytest.mark.asyncio
async def test_resolve_short_circuits_on_first_hit():
    p1 = _FakeProvider("p1", _hit("p1"))
    p2 = _FakeProvider("p2", _hit("p2"))
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[p1, p2])
    assert coords is not None and coords.source == "p1"
    assert len(p1.calls) == 1
    assert len(p2.calls) == 0


@pytest.mark.asyncio
async def test_resolve_returns_none_when_all_miss():
    p1 = _FakeProvider("p1", _miss)
    p2 = _FakeProvider("p2", _miss)
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[p1, p2])
    assert coords is None
    # 兩個 query (X, C / X) × 2 providers = 4 次
    assert len(p1.calls) == 2
    assert len(p2.calls) == 2


@pytest.mark.asyncio
async def test_resolve_continues_after_provider_error():
    p1 = _FakeProvider("p1", _crash("p1"))
    p2 = _FakeProvider("p2", _hit("p2"))
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[p1, p2])
    assert coords is not None and coords.source == "p2"
    assert len(p1.calls) == 1
    assert len(p2.calls) == 1
