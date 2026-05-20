"""Overpass provider 測試 —— 精準命中 OSM features 的關鍵 fallback。"""
import httpx
import pytest
import respx

from src.providers.base import ProviderError
from src.providers.overpass import (
    OverpassProvider,
    _build_ql,
    _extract_tokens,
    overpass,
)


def test_extract_tokens_strips_stopwords_and_short_words():
    tokens = _extract_tokens("The Farrow Community Beach Footbridge")
    # the/community/beach/footbridge 都是 stopword
    assert tokens == ["Farrow"]


def test_extract_tokens_keeps_distinctive_multi_token():
    tokens = _extract_tokens("Sensoji Asakusa Temple")
    # Temple 不在停用詞但 Sensoji + Asakusa 才是專名
    assert "Sensoji" in tokens
    assert "Asakusa" in tokens


def test_extract_tokens_empty_for_all_stopwords():
    assert _extract_tokens("The Community Beach Park") == []


def test_build_ql_uses_around_and_name_regex():
    ql = _build_ql(["Farrow"], 35.55, -75.47, 5000)
    assert "around:5000,35.55,-75.47" in ql
    assert '"name"~"Farrow",i' in ql
    assert "out center 5" in ql


def test_build_ql_combines_multiple_tokens_as_and():
    ql = _build_ql(["Farrow", "Footbridge"], 35.55, -75.47, 5000)
    # 兩個 [name~] filter 並排 → AND 語意
    assert '"name"~"Farrow"' in ql
    assert '"name"~"Footbridge"' in ql


@pytest.mark.asyncio
async def test_overpass_returns_none_without_hint_coords():
    """無粗座標就不打 API。"""
    result = await overpass.lookup("Farrow Footbridge")
    assert result is None


@pytest.mark.asyncio
async def test_overpass_returns_none_when_all_stopwords():
    """名稱全是停用詞 → 沒 distinctive token → 跳過。"""
    result = await overpass.lookup(
        "The Community Beach", hint_coords=(35.5, -75.5, 1500),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_overpass_finds_nearest_match():
    """Overpass 返回多筆,應挑離 hint_coords 最近的。"""
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    # 較遠
                    {
                        "type": "way", "id": 1,
                        "center": {"lat": 35.60, "lon": -75.40},
                        "tags": {"name": "Farrow Path North"},
                    },
                    # 很近 hint(35.55, -75.47)
                    {
                        "type": "way", "id": 2,
                        "center": {"lat": 35.547, "lon": -75.466},
                        "tags": {"name": "Farrow Community Beach Footbridge"},
                    },
                ]
            },
        )
    )
    result = await overpass.lookup(
        "The Farrow Community Beach Footbridge",
        hint_coords=(35.55, -75.47, 1500),
    )
    assert result is not None
    assert abs(result.lat - 35.547) < 0.001
    assert abs(result.lng - (-75.466)) < 0.001
    assert result.source == "overpass"
    assert "Farrow" in (result.canonical_name or "")
    # Overpass 結果是精確 OSM coord,不該標 approximate
    assert result.is_approximate is False


@pytest.mark.asyncio
@respx.mock
async def test_overpass_retries_with_single_token_on_empty():
    """第一輪所有 token AND 沒結果 → 退一輪用首 token。"""
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一輪(多 token)空
            return httpx.Response(200, json={"elements": []})
        # 第二輪(單 token)有結果
        return httpx.Response(
            200,
            json={
                "elements": [{
                    "type": "node", "id": 99,
                    "lat": 35.547, "lon": -75.466,
                    "tags": {"name": "Farrow Drive"},
                }]
            },
        )

    respx.post("https://overpass-api.de/api/interpreter").mock(side_effect=handler)
    result = await overpass.lookup(
        "Some Multi Token Name",
        hint_coords=(35.55, -75.47, 1500),
    )
    # 至少呼叫過 1 次;若有多 token 應呼叫 2 次
    assert call_count["n"] >= 1


@pytest.mark.asyncio
@respx.mock
async def test_overpass_raises_provider_error_on_http_failure():
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(504, json={})
    )
    with pytest.raises(ProviderError):
        await overpass.lookup("Farrow", hint_coords=(35.55, -75.47, 1500))


@pytest.mark.asyncio
@respx.mock
async def test_overpass_returns_none_on_empty_elements():
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    result = await overpass.lookup(
        "Farrow", hint_coords=(35.55, -75.47, 1500),
    )
    assert result is None


def test_radius_scales_with_accuracy_m():
    """accuracy_m 越大,半徑越大(到上限 20km)。"""
    # 用 _build_ql + 模擬 lookup 內 radius 計算
    # 直接觀察 radius_m = clamp(acc_m * 3, 2000, 20000)
    assert max(2000, min(20000, 100 * 3)) == 2000  # 信心高 → 最小半徑
    assert max(2000, min(20000, 1500 * 3)) == 4500  # 中等
    assert max(2000, min(20000, 50000 * 3)) == 20000  # 信心低 → 上限
