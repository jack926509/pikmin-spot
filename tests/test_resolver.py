from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from src import llm_rerank as llm_rerank_mod
from src import resolver as resolver_mod
from src.models import Coords, PlaceCandidates
from src.providers.base import GeocoderProvider, ProviderError
from src.resolver import build_queries, resolve


class _FakeProvider(GeocoderProvider):
    def __init__(self, name: str, behavior):
        self.name = name
        self._behavior = behavior
        self.calls: list[tuple[str, str]] = []

    async def lookup(
        self,
        query: str,
        hint_country: str = "",
        hint_coords: Optional[tuple[float, float, int]] = None,
    ) -> Optional[Coords]:
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
async def test_resolve_returns_highest_priority_when_multiple_hit():
    # 兩個 fast provider 同時命中,平行查仍應回傳優先序較高的 p1
    p1 = _FakeProvider("p1", _hit("p1"))
    p2 = _FakeProvider("p2", _hit("p2"))
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[p1, p2])
    assert coords is not None and coords.source == "p1"
    # 第一個 query 命中 → 不再推進到第二個 query
    assert len(p1.calls) == 1
    # 平行模式下 p2 可能會被叫到(端看 task scheduling),但至多 1 次
    assert len(p2.calls) <= 1


@pytest.mark.asyncio
async def test_resolve_returns_none_when_all_miss():
    p1 = _FakeProvider("p1", _miss)
    p2 = _FakeProvider("p2", _miss)
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[p1, p2])
    assert coords is None
    # 兩個 query (X, C / X) × 2 providers(平行) = 4 次
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


@pytest.mark.asyncio
async def test_resolve_nominatim_only_runs_when_fast_providers_miss():
    fast = _FakeProvider("fast", _miss)
    nom = _FakeProvider("nominatim", _hit("nominatim"))
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[fast, nom])
    assert coords is not None and coords.source == "nominatim"
    # fast 對每 query 跑一次後 miss,接著 nominatim 命中第一個 query → 早退
    assert len(fast.calls) == 1
    assert len(nom.calls) == 1


@pytest.mark.asyncio
async def test_resolve_skips_nominatim_when_fast_hits():
    fast = _FakeProvider("fast", _hit("fast"))
    nom = _FakeProvider("nominatim", _hit("nominatim"))
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = await resolve(place, providers=[fast, nom])
    assert coords is not None and coords.source == "fast"
    # fast 第一個 query 就命中,nominatim 不該被叫
    assert len(nom.calls) == 0


# ============================================================
# v3: Wayspot enhancement tests
# ============================================================


def test_build_queries_strips_leading_the():
    place = PlaceCandidates(
        candidates=["The Farrow Community Beach Footbridge"],
        country="USA",
    )
    qs = build_queries(place)
    assert any(
        q.startswith("Farrow Community Beach Footbridge") for q in qs
    ), f"沒有冠詞剝除版本: {qs}"


def test_build_queries_extracts_core_name_for_complex_wayspot():
    place = PlaceCandidates(
        candidates=["The Farrow Community Beach Footbridge"],
        country="USA", region="Salvo, NC",
    )
    qs = build_queries(place)
    assert any(
        q.startswith("Farrow,") or q == "Farrow" or "Farrow, Salvo" in q
        for q in qs
    ), f"沒有核心名抽取版本: {qs}"


def test_build_queries_includes_anchor_locations():
    place = PlaceCandidates(
        candidates=["X"], country="USA",
        anchor_locations=["Salvo, NC", "Outer Banks"],
    )
    qs = build_queries(place)
    assert "Salvo, NC, USA" in qs or "Salvo, NC" in qs
    assert "Outer Banks, USA" in qs or "Outer Banks" in qs


def test_build_queries_includes_region_fallback():
    place = PlaceCandidates(
        candidates=["X"], country="USA", region="Salvo, North Carolina",
    )
    qs = build_queries(place)
    assert any("Salvo, North Carolina" in q for q in qs)


@pytest.mark.asyncio
async def test_resolve_triggers_rerank_when_cascade_misses():
    """Cascade 全 miss → 應觸發 rerank → 取得 approximate 座標。"""
    miss_provider = _FakeProvider("miss", _miss)
    place = PlaceCandidates(candidates=["X"], country="USA", region="Salvo")

    async def fake_rerank(**kw):
        return Coords(
            lat=35.5, lng=-75.5, source="llm_rerank",
            matched_query="X", is_approximate=True, accuracy_m=1500,
        )

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=fake_rerank),
    ):
        coords = await resolve(place, providers=[miss_provider])

    assert coords is not None
    assert coords.source == "llm_rerank"
    assert coords.is_approximate is True
    assert coords.accuracy_m == 1500


@pytest.mark.asyncio
async def test_resolve_skips_rerank_when_disabled():
    miss_provider = _FakeProvider("miss", _miss)
    place = PlaceCandidates(candidates=["X"], country="USA")
    mock_rerank = AsyncMock()
    with patch.object(resolver_mod, "llm_final_reasoning", mock_rerank):
        coords = await resolve(
            place, providers=[miss_provider], enable_rerank=False
        )
    assert coords is None
    mock_rerank.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_anchor_collector_receives_secondary_hits():
    """平行查時,優先序較低 provider 的命中應蒐集為 anchor。"""
    p1 = _FakeProvider("p1", _hit("p1", lat=10.0, lng=20.0))
    p2 = _FakeProvider("p2", _hit("p2", lat=11.0, lng=21.0))
    place = PlaceCandidates(candidates=["X"], country="C")

    captured_anchors: list[Coords] = []

    async def fake_rerank(**kw):
        captured_anchors.extend(kw.get("anchor_coords") or [])
        return None

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=fake_rerank),
    ):
        coords = await resolve(place, providers=[p1, p2])

    # p1 命中即返回,不會觸發 rerank;此測試只驗證 p2 被叫過
    assert coords is not None and coords.source == "p1"
    # rerank 應該沒被呼叫(因為已 hit)
    assert captured_anchors == []


@pytest.mark.asyncio
async def test_resolve_passes_anchors_to_rerank():
    """主查 miss 但 anchor query 對某 provider 命中時,該結果應進 anchor_collector
    並傳給 rerank。"""
    # provider 對 "X, C" 與 "X" miss,但對 "Salvo, C" / "Salvo" 命中
    def behavior(q, h):
        if "Salvo" in q:
            return Coords(lat=35.5, lng=-75.5, source="p1", matched_query=q)
        return None

    p1 = _FakeProvider("p1", behavior)
    place = PlaceCandidates(
        candidates=["X"], country="C", anchor_locations=["Salvo"],
    )

    captured_anchors: list[Coords] = []

    async def fake_rerank(**kw):
        captured_anchors.extend(kw.get("anchor_coords") or [])
        return None

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=fake_rerank),
    ):
        coords = await resolve(place, providers=[p1])

    # "Salvo, C" 是 anchor query,但 cascade 仍視為 hit → 直接回傳
    # 不會走到 rerank(因為命中算成功)
    assert coords is not None
    assert coords.source == "p1"


@pytest.mark.asyncio
async def test_resolve_rejects_far_hit_when_vision_has_coords_guess():
    """若 vision 提供粗座標,離譜遠的命中應被視為錯誤匹配(同名地點),
    保留為 anchor 並觸發 rerank。"""
    # provider 回東京座標,但 vision 認為地標在美國 Salvo NC
    far_provider = _FakeProvider("far", _hit("far", lat=35.65, lng=139.74))
    place = PlaceCandidates(
        candidates=["Some Bridge"], country="USA",
        approximate_coords_guess=(35.55, -75.47, 1500),
    )

    captured_anchors: list[Coords] = []

    async def fake_rerank(**kw):
        captured_anchors.extend(kw.get("anchor_coords") or [])
        return None

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=fake_rerank),
    ):
        coords = await resolve(place, providers=[far_provider])

    # 直接回 None(rerank 也回 None),但東京命中應留在 anchor
    assert coords is None
    assert len(captured_anchors) >= 1
    assert any(c.source == "far" for c in captured_anchors)


@pytest.mark.asyncio
async def test_resolve_accepts_near_hit_when_vision_has_coords_guess():
    """若命中座標離 vision guess 在合理範圍,正常返回。"""
    # vision 認為在 Salvo NC,provider 回 NC 內某點(距離 < 50km)
    near_provider = _FakeProvider("near", _hit("near", lat=35.60, lng=-75.50))
    place = PlaceCandidates(
        candidates=["X"], country="USA",
        approximate_coords_guess=(35.55, -75.47, 1500),
    )

    coords = await resolve(place, providers=[near_provider], enable_rerank=False)
    assert coords is not None
    assert coords.source == "near"


@pytest.mark.asyncio
async def test_resolve_rejects_farrow_footbridge_regression():
    """還原 PR#6 後實測 case:Farrow Footbridge (NC) 不該幾到 NH/ME 海岸。

    Vision 給 (35.547, -75.466) ±1500m,Photon 返回 (43.262, -70.588) =
    距離 ~920km。1500m × 100 = 150km threshold → 應拒絕並轉 anchor。
    """
    bad_photon = _FakeProvider(
        "photon",
        _hit("photon", lat=43.262806, lng=-70.588705),
    )
    place = PlaceCandidates(
        candidates=["The Farrow Community Beach Footbridge"],
        country="United States",
        region="Salvo, North Carolina",
        approximate_coords_guess=(35.5475, -75.466, 1500),
    )

    captured_anchors: list[Coords] = []

    async def fake_rerank(**kw):
        captured_anchors.extend(kw.get("anchor_coords") or [])
        return None

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=fake_rerank),
    ):
        coords = await resolve(place, providers=[bad_photon])

    # 不該返回離 920km 的錯誤結果
    assert coords is None
    # 錯誤命中應保留為 anchor 給 rerank
    assert any(c.source == "photon" for c in captured_anchors)


def test_sanity_threshold_scales_with_accuracy():
    """Vision 越有信心(accuracy_m 越小),距離門檻越嚴。"""
    from src.resolver import _sanity_threshold_m
    # 街級信心 → 100m × 100 = 10km,但底線是 50km
    assert _sanity_threshold_m(100) == 50_000
    # 鎮級信心 → 2000m × 100 = 200km
    assert _sanity_threshold_m(2000) == 200_000
    # 不確定 → 上限 1500km
    assert _sanity_threshold_m(100_000) == 1_500_000


@pytest.mark.asyncio
async def test_resolve_rerank_failure_does_not_crash():
    """rerank 拋例外時,resolve 應吞掉並回 None。"""
    miss_provider = _FakeProvider("miss", _miss)
    place = PlaceCandidates(candidates=["X"], country="USA")

    async def boom(**kw):
        raise llm_rerank_mod.RerankError("boom")

    with patch.object(
        resolver_mod, "llm_final_reasoning",
        AsyncMock(side_effect=boom),
    ):
        coords = await resolve(place, providers=[miss_provider])
    assert coords is None
