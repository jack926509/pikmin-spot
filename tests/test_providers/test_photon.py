import httpx
import pytest
import respx

from src.providers.base import ProviderError
from src.providers.photon import photon


@pytest.mark.asyncio
@respx.mock
async def test_photon_returns_coords_for_known_place():
    respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {
                        "geometry": {"coordinates": [139.7454, 35.6586]},
                        "properties": {"name": "Tokyo Tower"},
                    }
                ]
            },
        )
    )
    coords = await photon.lookup("Tokyo Tower")
    assert coords is not None
    # 注意:GeoJSON 是 [lng, lat],provider 必須正確互換
    assert abs(coords.lat - 35.6586) < 0.01
    assert abs(coords.lng - 139.7454) < 0.01
    assert coords.source == "photon"


@pytest.mark.asyncio
@respx.mock
async def test_photon_returns_none_when_no_features():
    respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    assert await photon.lookup("zzz-no-such-place") is None


@pytest.mark.asyncio
@respx.mock
async def test_photon_raises_provider_error_on_http_failure():
    respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(500, json={})
    )
    with pytest.raises(ProviderError):
        await photon.lookup("X")


@pytest.mark.asyncio
@respx.mock
async def test_photon_picks_result_matching_country_code():
    respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {
                        "geometry": {"coordinates": [2.0, 48.0]},
                        "properties": {"name": "Wrong", "countrycode": "FR"},
                    },
                    {
                        "geometry": {"coordinates": [139.74, 35.65]},
                        "properties": {"name": "Right", "countrycode": "JP"},
                    },
                ]
            },
        )
    )
    coords = await photon.lookup("X", hint_country="Japan")
    assert coords is not None
    assert abs(coords.lat - 35.65) < 0.01
