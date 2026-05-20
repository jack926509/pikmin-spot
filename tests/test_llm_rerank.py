"""LLM Rerank 推理層測試。

關鍵 case:
1. LLM 成功給出座標 → 回 Coords(is_approximate=True)
2. LLM 回 lat=null(承認沒辦法) → 回 None
3. LLM 回非法座標(超出地球範圍) → 回 None
4. JSON parse 失敗 → 拋 RerankError
5. Timeout → 拋 RerankError
6. 空輸入(沒有任何 candidates/region/country) → 不呼叫 LLM,直接 None
7. _build_user_message 包含所有信號(anchor / snippets / vision guess)
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import llm_rerank
from src.models import Coords, PlaceCandidates


def _mock_response(payload):
    r = MagicMock()
    msg = MagicMock()
    msg.content = payload if isinstance(payload, str) else json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    r.choices = [choice]
    return r


def _fake_client(response=None, side_effect=None):
    fake = MagicMock()
    if side_effect is not None:
        fake.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        fake.chat.completions.create = AsyncMock(return_value=response)
    return fake


@pytest.mark.asyncio
async def test_rerank_returns_approximate_coords_on_success():
    resp = _mock_response({
        "lat": 35.5475, "lng": -75.4665, "accuracy_m": 1500,
        "is_approximate": True,
        "reasoning": "Salvo NC + Farrow Drive end + ocean side",
        "confidence": "medium",
    })
    place = PlaceCandidates(
        candidates=["The Farrow Community Beach Footbridge"],
        country="United States", region="Salvo, North Carolina",
    )
    anchor = Coords(
        lat=35.548, lng=-75.469, source="nominatim",
        matched_query="Salvo, NC", canonical_name="Salvo, NC, USA",
    )
    with patch.object(llm_rerank, "_get_client", return_value=_fake_client(resp)):
        result = await llm_rerank.llm_final_reasoning(place, [anchor])
    assert result is not None
    assert abs(result.lat - 35.5475) < 0.001
    assert abs(result.lng - (-75.4665)) < 0.001
    assert result.source == "llm_rerank"
    assert result.is_approximate is True
    assert result.accuracy_m == 1500


@pytest.mark.asyncio
async def test_rerank_returns_none_when_llm_gives_up():
    resp = _mock_response({
        "lat": None, "lng": None,
        "reasoning": "no idea", "confidence": "low",
    })
    place = PlaceCandidates(candidates=["???"], country="Atlantis")
    with patch.object(llm_rerank, "_get_client", return_value=_fake_client(resp)):
        result = await llm_rerank.llm_final_reasoning(place, [])
    assert result is None


@pytest.mark.asyncio
async def test_rerank_rejects_out_of_range_coords():
    resp = _mock_response({
        "lat": 200.0, "lng": -75.0,
        "accuracy_m": 1000, "confidence": "low",
    })
    place = PlaceCandidates(candidates=["X"], country="US")
    with patch.object(llm_rerank, "_get_client", return_value=_fake_client(resp)):
        result = await llm_rerank.llm_final_reasoning(place, [])
    assert result is None


@pytest.mark.asyncio
async def test_rerank_raises_on_invalid_json():
    resp = _mock_response("not-json-at-all")
    place = PlaceCandidates(candidates=["X"], country="US")
    with patch.object(llm_rerank, "_get_client", return_value=_fake_client(resp)):
        with pytest.raises(llm_rerank.RerankError):
            await llm_rerank.llm_final_reasoning(place, [])


@pytest.mark.asyncio
async def test_rerank_raises_on_timeout():
    async def _slow(*a, **kw):
        await asyncio.sleep(100)

    fake = _fake_client(side_effect=_slow)
    place = PlaceCandidates(candidates=["X"], country="US")
    with patch.object(llm_rerank, "_get_client", return_value=fake):
        with patch.object(llm_rerank, "RERANK_TIMEOUT_SEC", 0.1):
            with pytest.raises(llm_rerank.RerankError):
                await llm_rerank.llm_final_reasoning(place, [])


@pytest.mark.asyncio
async def test_rerank_skips_with_no_useful_input():
    place = PlaceCandidates(candidates=[], country="", region="")
    fake = _fake_client(_mock_response({"lat": 1, "lng": 1}))
    with patch.object(llm_rerank, "_get_client", return_value=fake):
        result = await llm_rerank.llm_final_reasoning(place, [])
    assert result is None
    fake.chat.completions.create.assert_not_called()


def test_build_user_message_includes_all_signals():
    place = PlaceCandidates(
        candidates=["The Farrow Community Beach Footbridge"],
        country="USA", region="Salvo, NC",
        description="Wooden community footbridge",
        anchor_locations=["Salvo, NC", "Outer Banks"],
    )
    anchor = Coords(
        lat=35.548, lng=-75.469, source="nominatim",
        matched_query="Salvo, NC", canonical_name="Salvo town",
    )
    msg = llm_rerank._build_user_message(
        place,
        anchor_coords=[anchor],
        web_snippets=["Farrow Drive ends at the ocean..."],
        vision_coords_guess=(35.547, -75.466, 1500),
    )
    assert "Farrow" in msg
    assert "Salvo town" in msg
    assert "35.548" in msg
    assert "Farrow Drive ends" in msg
    assert "35.547" in msg
