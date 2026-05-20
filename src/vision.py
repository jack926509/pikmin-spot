"""Vision 模組 v3:強化 prompt 對 Wayspot 類社區小景點的識別。

主要改動(相對 v2):
1. Prompt 明確告知「Pikmin Bloom Wayspot 多半不是 Wikipedia 級地標」
2. 新增 anchor_locations 欄位:附近的鎮/街/知名地標
3. 新增 approximate_coords_guess:對於 LLM 認得區域的 Wayspot,直接給粗座標作為 rerank 輔助
4. 新增 is_likely_wayspot_only 自我評估旗標
5. 加入 Farrow Footbridge 示範社區小景點的標準輸出
"""

import asyncio
import base64
import json
from typing import Any, Optional

from openai import AsyncOpenAI

from src.config import settings
from src.logger import get_logger
from src.models import PlaceCandidates

log = get_logger(__name__)

VISION_TIMEOUT_SEC = 30

PROMPT = """You are an expert at identifying real-world landmarks from Pikmin Bloom mushroom point screenshots.

==========================
ABOUT THE GAME UI
==========================
Pikmin Bloom mushroom screenshots have this layout:
- TOP: Photo of the real-world landmark
- MIDDLE: Landmark name shown as TITLE (often in multiple scripts)
- BELOW TITLE: Short English description ("The only temple in Bhutan...")
- "距離" or "Distance" line: meters from user — IGNORE
- BOTTOM: 3D mushroom decorations — IGNORE

==========================
IMPORTANT: WAYSPOTS ARE NOT ALWAYS FAMOUS LANDMARKS
==========================
Many points are community-level features that are NOT in Wikipedia:
- Community beach access bridges / boardwalks (e.g. "The Farrow Community Beach Footbridge")
- Neighborhood murals, sculptures, public art
- Small monuments, historical plaques, markers
- Park entrances, trailheads
- Small shrines, religious icons
- Decorative gates, named benches, fountains

For these, NO database will have a direct match. Your job becomes:
1. Extract the EXACT name as displayed (for downstream geo-search)
2. Identify NEARBY ANCHORS from the description (towns, streets, named landmarks)
3. If you recognize the area, provide an APPROXIMATE COORDINATE GUESS
4. Set is_likely_wayspot_only=true so downstream knows to use fallback reasoning

==========================
OUTPUT (valid JSON only, no markdown, no code fence)
==========================
{
  "candidates": [
    "Primary English/official name (most likely DB title)",
    "Alternative spelling or common name",
    "Transliteration variant if applicable"
  ],
  "place_name_local": "Name in original script if visible, else null",
  "country": "Country name in English",
  "region": "City or province in English",
  "description": "One sentence factual description",
  "search_hints": ["extra keyword 1", "extra keyword 2"],
  "confidence": "high" | "medium" | "low",

  "anchor_locations": [
    "Nearby city/town name",
    "Street name if mentioned",
    "Famous nearby landmark"
  ],
  "is_likely_wayspot_only": true | false,
  "approximate_coords_guess": {
    "lat": 35.5475,
    "lng": -75.4665,
    "accuracy_m": 1000
  }
}

Set approximate_coords_guess to null if you have no idea where the area is.

==========================
EXAMPLES
==========================

Input: Screenshot showing "Jangtsa Dumtseg Lhakhang" with Bhutanese stupa-temple
Output:
{
  "candidates": ["Jangtsa Dumtseg Lhakhang", "Dumtseg Lhakhang", "Dungtse Lhakhang"],
  "place_name_local": "ཛྩུ་མ་བར་",
  "country": "Bhutan",
  "region": "Paro",
  "description": "The only temple in Bhutan in the form of a stupa",
  "search_hints": ["Paro chorten", "Thangtong Gyalpo temple"],
  "confidence": "high",
  "anchor_locations": ["Paro Valley", "Paro Dzong"],
  "is_likely_wayspot_only": false,
  "approximate_coords_guess": {"lat": 27.43, "lng": 89.41, "accuracy_m": 5000}
}

Input: Screenshot showing "東京タワー | Tokyo Tower"
Output:
{
  "candidates": ["Tokyo Tower", "東京タワー"],
  "place_name_local": "東京タワー",
  "country": "Japan",
  "region": "Tokyo",
  "description": "Communications and observation tower in Minato, Tokyo",
  "search_hints": ["Minato tower Japan"],
  "confidence": "high",
  "anchor_locations": ["Minato, Tokyo", "Shiba Park"],
  "is_likely_wayspot_only": false,
  "approximate_coords_guess": {"lat": 35.6586, "lng": 139.7454, "accuracy_m": 200}
}

Input: Screenshot showing "The Farrow Community Beach Footbridge"
Description: "This wooden footbridge was installed by the Town of Salvo NC..."
Output:
{
  "candidates": ["The Farrow Community Beach Footbridge", "Farrow Beach Footbridge", "Farrow Community Beach Access"],
  "place_name_local": null,
  "country": "United States",
  "region": "Salvo, North Carolina",
  "description": "Wooden community footbridge providing beach access without disturbing sand dunes",
  "search_hints": ["Farrow Drive Salvo NC", "Salvo NC beach access"],
  "confidence": "medium",
  "anchor_locations": ["Salvo, NC", "Outer Banks, North Carolina", "Farrow Drive"],
  "is_likely_wayspot_only": true,
  "approximate_coords_guess": {"lat": 35.5475, "lng": -75.466, "accuracy_m": 1500}
}

==========================
CRITICAL RULES
==========================
- Generate 1-3 candidates, prefer English Wikipedia-title format
- Distance line "距離: 3,207,181m" is NEVER part of the name
- Always include local-script name if visible
- For famous landmarks: confidence=high, is_likely_wayspot_only=false
- For community features: confidence=medium/low, is_likely_wayspot_only=true
- approximate_coords_guess: ONLY if you recognize the area. Better to be null than to guess wildly.
- If you cannot identify ANY landmark: {"candidates": [], "error": "explanation"}
"""


class VisionError(Exception):
    pass


_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item:
            continue
        key = item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _parse_coords_guess(raw: Any) -> Optional[tuple[float, float, int]]:
    """從 LLM 回傳的 approximate_coords_guess 解出 (lat, lng, accuracy_m)。
    任何格式錯誤都回 None,不拋。"""
    if not isinstance(raw, dict):
        return None
    try:
        lat = float(raw.get("lat"))
        lng = float(raw.get("lng"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    try:
        acc = int(raw.get("accuracy_m") or 2000)
    except (TypeError, ValueError):
        acc = 2000
    return (lat, lng, max(50, min(acc, 50000)))


async def identify_place(image_bytes: bytes) -> PlaceCandidates:
    """回傳候選名陣列。完全無法識別時回 candidates=[]。
    LLM 呼叫失敗或 JSON 解析失敗拋 VisionError。"""
    client = _get_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}"
                                },
                            },
                        ],
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            ),
            timeout=VISION_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        raise VisionError(f"OpenAI timeout after {VISION_TIMEOUT_SEC}s") from e
    except Exception as e:
        raise VisionError(f"OpenAI call failed: {type(e).__name__}") from e

    raw = (response.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("vision json parse failed", raw_preview=raw[:200])
        raise VisionError(f"JSON parse failed: {e}") from e

    if not isinstance(data, dict):
        raise VisionError("LLM did not return a JSON object")

    candidates_raw = data.get("candidates") or []
    if not isinstance(candidates_raw, list):
        candidates_raw = []
    candidates = _dedup_preserve_order([str(c) for c in candidates_raw])

    hints_raw = data.get("search_hints") or []
    if not isinstance(hints_raw, list):
        hints_raw = []
    hints = _dedup_preserve_order([str(h) for h in hints_raw])

    # v3 新增欄位
    anchors_raw = data.get("anchor_locations") or []
    if not isinstance(anchors_raw, list):
        anchors_raw = []
    anchors = _dedup_preserve_order([str(a) for a in anchors_raw])

    coords_guess = _parse_coords_guess(data.get("approximate_coords_guess"))

    place = PlaceCandidates(
        candidates=candidates,
        place_name_local=data.get("place_name_local") or None,
        country=str(data.get("country") or ""),
        region=str(data.get("region") or ""),
        description=str(data.get("description") or ""),
        search_hints=hints,
        confidence=str(data.get("confidence") or "low"),
        anchor_locations=anchors,
        is_likely_wayspot_only=bool(data.get("is_likely_wayspot_only", False)),
        approximate_coords_guess=coords_guess,
    )
    log.info(
        "vision result",
        n_candidates=len(place.candidates),
        country=place.country,
        confidence=place.confidence,
        is_wayspot=place.is_likely_wayspot_only,
        has_coords_guess=coords_guess is not None,
        n_anchors=len(anchors),
    )
    return place
