import httpx
import pytest
import respx

from src.providers.base import ProviderError
from src.providers.nominatim import nominatim


@pytest.mark.asyncio
@respx.mock
async def test_nominatim_returns_coords_for_known_place():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "lat": "48.8582599",
                    "lon": "2.2945006",
                    "display_name": "Tour Eiffel, Paris",
                }
            ],
        )
    )
    coords = await nominatim.lookup("Eiffel Tower")
    assert coords is not None
    assert abs(coords.lat - 48.858) < 0.01
    assert abs(coords.lng - 2.294) < 0.01
    assert coords.source == "nominatim"


@pytest.mark.asyncio
@respx.mock
async def test_nominatim_returns_none_when_no_results():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert await nominatim.lookup("zzz-no-such-place") is None


@pytest.mark.asyncio
@respx.mock
async def test_nominatim_raises_provider_error_on_http_failure():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(429, json={})
    )
    with pytest.raises(ProviderError):
        await nominatim.lookup("X")


@pytest.mark.asyncio
@respx.mock
async def test_nominatim_picks_result_matching_country_code():
    """有多筆結果時,挑 country_code 符合 hint 的那筆。"""
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "lat": "48.0", "lon": "2.0",
                    "display_name": "Eiffel Tower (replica), France",
                    "address": {"country_code": "fr"},
                },
                {
                    "lat": "35.65", "lon": "139.74",
                    "display_name": "Eiffel Tower replica, Tokyo, Japan",
                    "address": {"country_code": "jp"},
                },
            ],
        )
    )
    coords = await nominatim.lookup("Eiffel Tower", hint_country="Japan")
    assert coords is not None
    assert abs(coords.lat - 35.65) < 0.01
    assert abs(coords.lng - 139.74) < 0.01


@pytest.mark.asyncio
@respx.mock
async def test_nominatim_falls_back_to_first_when_no_country_match():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "lat": "1.0", "lon": "2.0",
                    "display_name": "X",
                    "address": {"country_code": "fr"},
                },
            ],
        )
    )
    coords = await nominatim.lookup("X", hint_country="Japan")
    # 沒符合的就回第一筆(不過濾就無結果太苛刻)
    assert coords is not None
    assert coords.lat == 1.0
