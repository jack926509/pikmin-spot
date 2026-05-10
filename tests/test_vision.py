import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import vision


def _mock_response(payload: dict | str) -> MagicMock:
    r = MagicMock()
    r.text = payload if isinstance(payload, str) else json.dumps(payload)
    return r


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
    fake = MagicMock()
    fake.generate_content_async = AsyncMock(return_value=resp)
    with patch.object(vision, "_get_model", return_value=fake):
        place = await vision.identify_place(b"img")

    # case-insensitive dedup
    assert place.candidates == ["Tokyo Tower", "東京タワー"]
    assert place.country == "Japan"
    assert place.confidence == "high"


@pytest.mark.asyncio
async def test_identify_place_handles_empty_candidates():
    resp = _mock_response({"candidates": [], "error": "no landmark"})
    fake = MagicMock()
    fake.generate_content_async = AsyncMock(return_value=resp)
    with patch.object(vision, "_get_model", return_value=fake):
        place = await vision.identify_place(b"img")
    assert place.candidates == []


@pytest.mark.asyncio
async def test_identify_place_strips_markdown_codefence():
    resp = _mock_response('```json\n{"candidates": ["A"], "country": "C"}\n```')
    fake = MagicMock()
    fake.generate_content_async = AsyncMock(return_value=resp)
    with patch.object(vision, "_get_model", return_value=fake):
        place = await vision.identify_place(b"img")
    assert place.candidates == ["A"]
    assert place.country == "C"


@pytest.mark.asyncio
async def test_identify_place_raises_on_invalid_json():
    resp = _mock_response("not-json")
    fake = MagicMock()
    fake.generate_content_async = AsyncMock(return_value=resp)
    with patch.object(vision, "_get_model", return_value=fake):
        with pytest.raises(vision.VisionError):
            await vision.identify_place(b"img")


@pytest.mark.asyncio
async def test_identify_place_raises_on_llm_failure():
    fake = MagicMock()
    fake.generate_content_async = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(vision, "_get_model", return_value=fake):
        with pytest.raises(vision.VisionError):
            await vision.identify_place(b"img")
