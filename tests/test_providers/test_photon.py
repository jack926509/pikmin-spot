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
async def test_photon_sends_location_bias_when_hint_coords_provided():
    """傳 hint_coords 時,params 必須帶 lat/lon/location_bias_scale。"""
    route = respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(
            200,
            json={"features": [{
                "geometry": {"coordinates": [-75.46, 35.55]},
                "properties": {"name": "Farrow Footbridge"},
            }]},
        )
    )
    await photon.lookup(
        "Farrow",
        hint_country="USA",
        hint_coords=(35.55, -75.47, 1500),
    )
    assert route.called
    sent_params = dict(route.calls.last.request.url.params)
    assert sent_params.get("lat") == "35.55"
    assert sent_params.get("lon") == "-75.47"
    assert "location_bias_scale" in sent_params


@pytest.mark.asyncio
@respx.mock
async def test_photon_omits_location_bias_when_no_hint():
    """沒傳 hint_coords 時 params 不應出現 lat/lon(避免影響純名稱查詢)。"""
    route = respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(
            200,
            json={"features": [{
                "geometry": {"coordinates": [0.0, 0.0]},
                "properties": {"name": "X"},
            }]},
        )
    )
    await photon.lookup("X")
    sent_params = dict(route.calls.last.request.url.params)
    assert "lat" not in sent_params
    assert "lon" not in sent_params


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
