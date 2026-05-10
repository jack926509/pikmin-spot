import asyncio
import base64
import json
from typing import Any

from openai import AsyncOpenAI

from src.config import settings
from src.logger import get_logger
from src.models import PlaceCandidates

log = get_logger(__name__)

VISION_TIMEOUT_SEC = 30

PROMPT = """You are an expert at identifying real-world landmarks from Pikmin Bloom mushroom point screenshots.

ABOUT THE GAME UI:
Pikmin Bloom mushroom screenshots have this layout:
- TOP: Photo of the real-world landmark
- MIDDLE: Landmark name shown as a TITLE (often in multiple scripts like Latin/Tibetan/Japanese/Chinese)
- BELOW TITLE: A short English description ("The only temple in Bhutan...")
- "距離" or "Distance": followed by meters — THIS IS NOT PART OF THE NAME, IGNORE IT
- BOTTOM: 3D mushroom decorations — IGNORE THESE

Your job: identify the landmark from the TITLE and photo. Generate MULTIPLE candidate names because:
- OCR may produce minor errors
- Wikipedia titles often differ from displayed names
- Geocoders may need different spellings

OUTPUT (valid JSON only, no markdown, no code fence):
{
  "candidates": [
    "Primary English/official name (most likely Wikipedia title)",
    "Alternative spelling or common name",
    "Transliteration variant if applicable"
  ],
  "place_name_local": "Name in original script if visible, else null",
  "country": "Country name in English",
  "region": "City or province in English",
  "description": "One sentence factual description of what the landmark is",
  "search_hints": ["extra keyword 1", "extra keyword 2"],
  "confidence": "high" | "medium" | "low"
}

EXAMPLES:

Input: Screenshot showing "Jangtsa Dumtseg Lhakhang" with Bhutanese stupa-temple
Output:
{
  "candidates": ["Jangtsa Dumtseg Lhakhang", "Dumtseg Lhakhang", "Dungtse Lhakhang"],
  "place_name_local": "ཛྩུ་མ་བར་",
  "country": "Bhutan",
  "region": "Paro",
  "description": "The only temple in Bhutan in the form of a stupa",
  "search_hints": ["Paro chorten", "Thangtong Gyalpo temple"],
  "confidence": "high"
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
  "confidence": "high"
}

If you cannot identify any landmark at all:
{"candidates": [], "error": "explanation"}

CRITICAL:
- Generate 1-3 candidates, prefer English Wikipedia title format
- Distance text "距離: 3,207,181m" is NEVER the name
- Always include local-script name if visible
- Be confident on famous landmarks; mark "low" only when truly uncertain
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

    place = PlaceCandidates(
        candidates=candidates,
        place_name_local=data.get("place_name_local") or None,
        country=str(data.get("country") or ""),
        region=str(data.get("region") or ""),
        description=str(data.get("description") or ""),
        search_hints=hints,
        confidence=str(data.get("confidence") or "low"),
    )
    log.info(
        "vision result",
        n_candidates=len(place.candidates),
        country=place.country,
        confidence=place.confidence,
    )
    return place
