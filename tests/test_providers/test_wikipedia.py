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
