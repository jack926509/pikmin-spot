import json

import httpx
import pytest
import respx

from src.providers.base import ProviderError
from src.providers.wikidata import wikidata


@pytest.mark.asyncio
@respx.mock
async def test_wikidata_returns_coords_for_known_landmark():
    search_payload = {
        "search": [
            {
                "id": "Q6154126",
                "label": "Jangtsa Dumtseg Lhakhang",
                "description": "temple in Bhutan",
            }
        ]
    }
    entity_payload = {
        "entities": {
            "Q6154126": {
                "claims": {
                    "P625": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "latitude": 27.435083,
                                        "longitude": 89.413611,
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    respx.get("https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(200, json=search_payload)
    )
    respx.get(
        "https://www.wikidata.org/wiki/Special:EntityData/Q6154126.json"
    ).mock(return_value=httpx.Response(200, json=entity_payload))

    coords = await wikidata.lookup("Jangtsa Dumtseg Lhakhang", "Bhutan")
    assert coords is not None
    assert abs(coords.lat - 27.435) < 0.01
    assert abs(coords.lng - 89.413) < 0.01
    assert coords.source == "wikidata"


@pytest.mark.asyncio
@respx.mock
async def test_wikidata_returns_none_for_no_results():
    respx.get("https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(200, json={"search": []})
    )
    assert await wikidata.lookup("zzz-not-a-place-zzz") is None


@pytest.mark.asyncio
@respx.mock
async def test_wikidata_returns_none_when_entity_has_no_p625():
    respx.get("https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={"search": [{"id": "Q1", "label": "X", "description": "city"}]},
        )
    )
    respx.get(
        "https://www.wikidata.org/wiki/Special:EntityData/Q1.json"
    ).mock(return_value=httpx.Response(200, json={"entities": {"Q1": {"claims": {}}}}))
    assert await wikidata.lookup("anything") is None


@pytest.mark.asyncio
@respx.mock
async def test_wikidata_raises_provider_error_on_http_failure():
    respx.get("https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(500, json={})
    )
    with pytest.raises(ProviderError):
        await wikidata.lookup("anything")
