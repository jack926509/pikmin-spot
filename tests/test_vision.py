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


@pytest.mark.asyncio
async def test_identify_place_parses_v3_fields():
    resp = _mock_response({
        "candidates": ["X"],
        "country": "C", "region": "R",
        "anchor_locations": ["A1", "A2"],
        "is_likely_wayspot_only": True,
        "approximate_coords_guess": {"lat": 1.5, "lng": 2.5, "accuracy_m": 500},
    })
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")
    assert place.anchor_locations == ["A1", "A2"]
    assert place.is_likely_wayspot_only is True
    assert place.approximate_coords_guess == (1.5, 2.5, 500)


@pytest.mark.asyncio
async def test_identify_place_rejects_out_of_range_coords_guess():
    resp = _mock_response({
        "candidates": ["X"],
        "approximate_coords_guess": {"lat": 200, "lng": 0, "accuracy_m": 100},
    })
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")
    assert place.approximate_coords_guess is None


@pytest.mark.asyncio
async def test_identify_place_retries_once_on_transient_error():
    """第一次失敗,第二次成功 —— 應回正確結果而非拋例外。"""
    good = _mock_response({"candidates": ["X"], "country": "C"})
    side_effects = [RuntimeError("transient blip"), good]
    fake = _fake_client(side_effect=side_effects)
    with patch.object(vision, "_get_client", return_value=fake):
        with patch.object(vision, "VISION_RETRY_BACKOFF_SEC", 0):
            place = await vision.identify_place(b"img")
    assert place.candidates == ["X"]
    assert fake.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_identify_place_raises_after_all_retries_exhausted():
    """兩次都失敗 —— 應拋 VisionError。"""
    fake = _fake_client(side_effect=RuntimeError("persistent"))
    with patch.object(vision, "_get_client", return_value=fake):
        with patch.object(vision, "VISION_RETRY_BACKOFF_SEC", 0):
            with pytest.raises(vision.VisionError):
                await vision.identify_place(b"img")
    assert fake.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_identify_place_backward_compatible_old_schema():
    """v2 格式(沒有 anchor/is_wayspot/coords_guess)應正常解析。"""
    resp = _mock_response({
        "candidates": ["X"],
        "country": "C",
    })
    with patch.object(vision, "_get_client", return_value=_fake_client(resp)):
        place = await vision.identify_place(b"img")
    assert place.candidates == ["X"]
    assert place.anchor_locations == []
    assert place.is_likely_wayspot_only is False
    assert place.approximate_coords_guess is None
