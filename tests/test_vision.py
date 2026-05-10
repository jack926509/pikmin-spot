import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import vision


def _mock_response(payload: dict | str) -> MagicMock:
    r = MagicMock()
    msg = MagicMock()
    msg.content = payload if isinstance(payload, str) else json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    r.choices = [choice]
    return r


def _fake_client(response: MagicMock | None = None, side_effect=None) -> MagicMock:
    fake = MagicMock()
    if side_effect is not None:
        fake.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        fake.chat.completions.create = AsyncMock(return_value=response)
    return fake


@pytest.mark.asyncio
async def test_identify_place_parses_valid_json():
    resp = _mock_response({
        "candidates": ["Tokyo Tower", "tokyo tower", "東京タワー"],
        "place_name_local": "東京タワー",
        "country": "Japan",
        "region": "Tokyo",
        "description": "Communications tower",
        "search_hints": ["Minato"],
        "confidence": "high",
    })
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")

    # case-insensitive dedup
    assert place.candidates == ["Tokyo Tower", "東京タワー"]
    assert place.country == "Japan"
    assert place.confidence == "high"


@pytest.mark.asyncio
async def test_identify_place_handles_empty_candidates():
    resp = _mock_response({"candidates": [], "error": "no landmark"})
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")
    assert place.candidates == []


@pytest.mark.asyncio
async def test_identify_place_strips_markdown_codefence():
    resp = _mock_response('```json\n{"candidates": ["A"], "country": "C"}\n```')
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")
    assert place.candidates == ["A"]
    assert place.country == "C"


@pytest.mark.asyncio
async def test_identify_place_raises_on_invalid_json():
    resp = _mock_response("not-json")
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        with pytest.raises(vision.VisionError):
            await vision.identify_place(b"img")


@pytest.mark.asyncio
async def test_identify_place_raises_on_llm_failure():
    fake = _fake_client(side_effect=RuntimeError("boom"))
    with patch.object(vision, "_get_client", return_value=fake):
        with pytest.raises(vision.VisionError):
            await vision.identify_place(b"img")
