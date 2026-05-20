"""LLM Final Reasoning 推理層。

當四層級聯全 miss 時,把 Vision 結果 + 各 provider 留下的「最接近線索」+
(可選) Web search snippets 一起餵給 LLM,讓它做最終的地理推理。

這正是 Farrow Community Beach Footbridge 案例中,人工查詢能成功而 bot 失敗的關鍵差異。
"""

import asyncio
import json
from typing import Optional

from openai import AsyncOpenAI

from src.config import settings
from src.logger import get_logger
from src.models import Coords, PlaceCandidates

log = get_logger(__name__)

RERANK_TIMEOUT_SEC = 12

REASONING_PROMPT = """You are a geographic reasoning expert helping a Pikmin Bloom bot find GPS coordinates of a Wayspot (a small community-level point of interest that may not be in Wikipedia).

The cascade of databases (Wikidata, Wikipedia, OSM via Nominatim/Photon) all failed for the *exact* name. Your job: reason from clues to produce the most accurate GPS guess possible.

INPUTS YOU WILL RECEIVE:
1. Vision identification (name, country, region, description, anchor locations)
2. "Anchor coordinates" — known coordinates of nearby places/towns/streets that DID resolve
3. (Optional) Vision's own coordinate guess from training data
4. (Optional) Web search snippets

OUTPUT (valid JSON only, no markdown):
{
  "lat": 35.5475,
  "lng": -75.4665,
  "accuracy_m": 500,
  "is_approximate": true,
  "reasoning": "Short one-paragraph explanation",
  "confidence": "high" | "medium" | "low"
}

If you genuinely cannot guess even an approximate location:
{"lat": null, "lng": null, "reasoning": "explanation", "confidence": "low"}

REASONING GUIDELINES:
- If the description mentions a town/street/landmark whose coordinates you know, anchor your guess there
- For "beach footbridge in Salvo NC" → anchor at Salvo town center, offset toward the ocean
- For "shrine near Asakusa station, Tokyo" → anchor at Asakusa station, offset by described direction
- Always set is_approximate=true unless you have very high confidence
- accuracy_m: realistic radius of uncertainty. Town-level fallback ≈ 2000m. Street-level ≈ 500m. Exact ≈ 100m.
- Use anchor coordinates provided as PRIMARY signal. Use your own world knowledge as SECONDARY signal.

CRITICAL:
- Do NOT invent coordinates with high confidence based on the name alone
- Do NOT confuse same-named places in different countries (the country field is authoritative)
- Better to return null than to guess wildly
"""


class RerankError(Exception):
    pass


_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _build_user_message(
    place: PlaceCandidates,
    anchor_coords: list[Coords],
    web_snippets: Optional[list[str]] = None,
    vision_coords_guess: Optional[tuple[float, float, int]] = None,
) -> str:
    """組裝給 LLM 的 user message,把所有線索結構化呈現。"""
    parts: list[str] = []

    parts.append("=== VISION IDENTIFICATION ===")
    parts.append(f"Primary name: {place.candidates[0] if place.candidates else '(unknown)'}")
    if len(place.candidates) > 1:
        parts.append(f"Other candidate names: {', '.join(place.candidates[1:])}")
    if place.place_name_local:
        parts.append(f"Local-script name: {place.place_name_local}")
    if place.country:
        parts.append(f"Country: {place.country}")
    if place.region:
        parts.append(f"Region: {place.region}")
    if place.description:
        parts.append(f"Description: {place.description}")
    if place.search_hints:
        parts.append(f"Search hints: {', '.join(place.search_hints)}")
    parts.append(f"Vision confidence: {place.confidence}")
    parts.append("")

    if vision_coords_guess:
        lat, lng, acc = vision_coords_guess
        parts.append("=== VISION'S OWN COORDINATE GUESS ===")
        parts.append(f"  {lat:.6f}, {lng:.6f} (±{acc}m)")
        parts.append("  (LLM's own rough estimate from training data; use as one signal)")
        parts.append("")

    if anchor_coords:
        parts.append("=== ANCHOR COORDINATES (places that DID resolve) ===")
        for c in anchor_coords:
            label = c.canonical_name or c.matched_query
            parts.append(
                f"  {label}: ({c.lat:.6f}, {c.lng:.6f}) [source: {c.source}]"
            )
        parts.append("")

    if web_snippets:
        parts.append("=== WEB SEARCH SNIPPETS ===")
        for i, sn in enumerate(web_snippets[:5], 1):
            parts.append(f"[{i}] {sn[:400]}")
        parts.append("")

    parts.append("Reason carefully and output JSON.")
    return "\n".join(parts)


async def llm_final_reasoning(
    place: PlaceCandidates,
    anchor_coords: list[Coords],
    web_snippets: Optional[list[str]] = None,
    vision_coords_guess: Optional[tuple[float, float, int]] = None,
) -> Optional[Coords]:
    """終極推理層。所有 provider miss 後最後一搏。

    Returns:
        Coords with is_approximate=True if successful,
        None if LLM also gives up.

    Raises:
        RerankError on infrastructure failure (timeout, parse error).
    """
    if not place.candidates and not place.region and not place.country:
        return None

    client = _get_client()
    user_msg = _build_user_message(
        place, anchor_coords, web_snippets, vision_coords_guess
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": REASONING_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            ),
            timeout=RERANK_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        log.warning("rerank timeout", timeout=RERANK_TIMEOUT_SEC)
        raise RerankError(f"rerank timeout after {RERANK_TIMEOUT_SEC}s") from e
    except Exception as e:
        log.warning("rerank api failed", error=str(e))
        raise RerankError(f"rerank api failed: {type(e).__name__}") from e

    raw = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("rerank json parse failed", raw_preview=raw[:200])
        raise RerankError(f"json parse failed: {e}") from e

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        log.info(
            "rerank: llm gave up",
            reasoning=str(data.get("reasoning", ""))[:200],
        )
        return None

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        log.warning("rerank: out-of-range coords", lat=lat_f, lng=lng_f)
        return None

    try:
        accuracy_m = int(data.get("accuracy_m") or 2000)
    except (TypeError, ValueError):
        accuracy_m = 2000
    accuracy_m = max(50, min(accuracy_m, 50000))

    reasoning = str(data.get("reasoning", ""))[:500]
    confidence = str(data.get("confidence", "low"))

    log.info(
        "rerank: hit",
        lat=lat_f,
        lng=lng_f,
        accuracy_m=accuracy_m,
        confidence=confidence,
        reasoning_preview=reasoning[:120],
    )

    return Coords(
        lat=lat_f,
        lng=lng_f,
        source="llm_rerank",
        matched_query=place.candidates[0] if place.candidates else "",
        canonical_name=place.candidates[0] if place.candidates else None,
        is_approximate=True,
        accuracy_m=accuracy_m,
    )
