import httpx
import pytest
import respx

from src.providers.base import ProviderError
from src.providers.wikipedia import wikipedia


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_returns_coords_for_known_landmark():
    respx.get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch"}).mock(
        return_value=httpx.Response(
            200,
            json=["Tokyo Tower", ["Tokyo Tower"], [""], ["https://en.wikipedia.org/wiki/Tokyo_Tower"]],
        )
    )
    respx.get("https://en.wikipedia.org/w/api.php", params={"action": "query"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "title": "Tokyo Tower",
                            "coordinates": [{"lat": 35.6586, "lon": 139.7454}],
                        }
                    }
                }
            },
        )
    )
    coords = await wikipedia.lookup("Tokyo Tower")
    assert coords is not None
    assert abs(coords.lat - 35.6586) < 0.01
    assert abs(coords.lng - 139.7454) < 0.01
    assert coords.source == "wikipedia"


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_returns_none_when_no_search_hit():
    respx.get("https://en.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(200, json=["q", [], [], []])
    )
    assert await wikipedia.lookup("zzz-no-such-place") is None


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_returns_none_when_page_has_no_coords():
    respx.get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch"}).mock(
        return_value=httpx.Response(200, json=["x", ["X"], [""], [""]])
    )
    respx.get("https://en.wikipedia.org/w/api.php", params={"action": "query"}).mock(
        return_value=httpx.Response(200, json={"query": {"pages": {"1": {"title": "X"}}}})
    )
    assert await wikipedia.lookup("X") is None


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_raises_provider_error_on_http_failure():
    respx.get("https://en.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(503, json={})
    )
    with pytest.raises(ProviderError):
        await wikipedia.lookup("X")


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_falls_back_to_japanese_wiki_for_japan():
    """英文 wiki 沒結果時,Japan hint 觸發日文 wiki 嘗試。"""
    # en wiki opensearch 沒結果
    respx.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "opensearch"},
    ).mock(return_value=httpx.Response(200, json=["q", [], [], []]))
    # en wiki srsearch 也沒結果
    respx.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query"},
    ).mock(return_value=httpx.Response(
        200, json={"query": {"search": [], "pages": {}}},
    ))
    # ja wiki opensearch 命中
    respx.get(
        "https://ja.wikipedia.org/w/api.php",
        params={"action": "opensearch"},
    ).mock(return_value=httpx.Response(
        200, json=["浅草寺", ["浅草寺"], [""], [""]],
    ))
    respx.get(
        "https://ja.wikipedia.org/w/api.php",
        params={"action": "query"},
    ).mock(return_value=httpx.Response(
        200,
        json={
            "query": {
                "pages": {
                    "1": {
                        "title": "浅草寺",
                        "coordinates": [{"lat": 35.7148, "lon": 139.7967}],
                    }
                }
            }
        },
    ))
    coords = await wikipedia.lookup("Sensoji", hint_country="Japan")
    assert coords is not None
    assert abs(coords.lat - 35.7148) < 0.01
    assert coords.canonical_name == "浅草寺"


@pytest.mark.asyncio
@respx.mock
async def test_wikipedia_uses_srsearch_when_opensearch_misses():
    """opensearch 沒命中時,srsearch 應接力。"""
    # opensearch 沒結果
    respx.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "opensearch"},
    ).mock(return_value=httpx.Response(200, json=["q", [], [], []]))
    # srsearch 找到一篇,接著取座標
    respx.route(
        method="GET",
        host="en.wikipedia.org",
    ).mock(side_effect=_srsearch_then_coords)

    coords = await wikipedia.lookup("Some Obscure Place")
    assert coords is not None


def _srsearch_then_coords(request):
    """根據 query params 模擬:srsearch 回一篇,query+coordinates 回座標。"""
    qs = dict(request.url.params)
    action = qs.get("action")
    if action == "opensearch":
        return httpx.Response(200, json=["q", [], [], []])
    if action == "query" and qs.get("list") == "search":
        return httpx.Response(
            200,
            json={"query": {"search": [{"title": "Some Place"}]}},
        )
    if action == "query":
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "title": "Some Place",
                            "coordinates": [{"lat": 10.0, "lon": 20.0}],
                        }
                    }
                }
            },
        )
    return httpx.Response(404)
