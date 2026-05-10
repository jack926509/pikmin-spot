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
