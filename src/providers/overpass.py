"""Overpass API provider:當主流 provider miss 時,在 vision 粗座標周邊精準搜尋 OSM。

設計重點:
- 必須有 hint_coords —— 否則就是全 DB 掃描,太貴且 Overpass 不允許。
- 用 vision 識別出的候選名抽 distinctive token,在 around:radius 內 OSM 搜尋。
- 第一輪用所有 token (AND 過濾,精確);無命中再退一輪用最具識別力的單一 token。
- 多個結果挑離 hint_coords 最近的(典型情境:vision 粗座標附近只有一個匹配)。

對「The Farrow Community Beach Footbridge」這類 Wayspot 特別有效 —— 即使
Wikidata/Wikipedia/Nominatim/Photon 的字串搜尋都 miss,OSM 仍可能登錄該
footway+bridge feature,而 Overpass 的 around-based 查詢能精確命中。
"""
import re
from typing import Optional

import httpx

from src.logger import get_logger
from src.models import Coords
from src.providers._geo import haversine_m
from src.providers.base import (
    USER_AGENT,
    GeocoderProvider,
    ProviderError,
)

log = get_logger(__name__)

API_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_SEC = 15.0
OVERPASS_QL_TIMEOUT_S = 10

# 抽 token 時要剝掉的通用詞 —— 對 OSM 搜尋沒識別力。
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "at", "on", "in", "to", "by", "for",
    "community", "neighborhood", "neighbourhood", "beach", "park",
    "garden", "trail", "trailhead", "memorial", "plaza", "square",
    "access", "marker", "sign", "monument", "statue", "footbridge", "bridge",
    "boardwalk", "walk", "walkway", "path", "playground", "fountain",
    "mural", "drive", "street", "road", "avenue", "lane", "way", "place",
    "north", "south", "east", "west", "central",
}


def _extract_tokens(query: str) -> list[str]:
    """從 query 抽出具識別力的詞 —— 去停用詞、長度 ≥ 3。
    依出現順序保留,通常第一個是最具特色的(專有名詞)。"""
    raw = re.findall(r"[A-Za-z一-鿿぀-ヿ]+", query)
    return [t for t in raw if t.lower() not in _STOPWORDS and len(t) >= 3]


def _build_ql(tokens: list[str], lat: float, lng: float, radius_m: int) -> str:
    """組 Overpass QL。多個 token 用同 tag 連續 filter = AND 語意。"""
    name_filters = "".join(f'["name"~"{re.escape(t)}",i]' for t in tokens)
    around = f"around:{radius_m},{lat},{lng}"
    return (
        f"[out:json][timeout:{OVERPASS_QL_TIMEOUT_S}];"
        f"("
        f"way{name_filters}({around});"
        f"node{name_filters}({around});"
        f"relation{name_filters}({around});"
        f");"
        f"out center 5;"
    )


def _element_coords(el: dict) -> tuple[Optional[float], Optional[float]]:
    """Overpass 元素取座標:node 直接 lat/lon,way/relation 用 out center 後的 center。"""
    if "lat" in el and "lon" in el:
        try:
            return float(el["lat"]), float(el["lon"])
        except (TypeError, ValueError):
            return None, None
    center = el.get("center") or {}
    if "lat" in center and "lon" in center:
        try:
            return float(center["lat"]), float(center["lon"])
        except (TypeError, ValueError):
            return None, None
    return None, None


class OverpassProvider(GeocoderProvider):
    name = "overpass"

    async def lookup(
        self,
        query: str,
        hint_country: str = "",
        hint_coords: Optional[tuple[float, float, int]] = None,
    ) -> Optional[Coords]:
        # 無粗座標就不跑 —— 全球掃描太貴,Overpass 不允許。
        if not hint_coords or not query.strip():
            return None
        tokens = _extract_tokens(query)
        if not tokens:
            return None
        tokens = tokens[:3]  # 上限 3 個 token,避免過嚴
        lat, lng, acc_m = hint_coords
        # 搜尋半徑:vision accuracy × 3,clamp 至 2-20km
        radius_m = max(2000, min(20000, acc_m * 3))

        # 第一輪:全 token AND(精確)
        result = await self._query(query, tokens, lat, lng, radius_m)
        if result:
            return result
        # 第二輪:只用首 token(放寬),前提是有多 token 可放寬
        if len(tokens) > 1:
            result = await self._query(query, tokens[:1], lat, lng, radius_m)
        return result

    async def _query(
        self,
        original_query: str,
        tokens: list[str],
        lat: float,
        lng: float,
        radius_m: int,
    ) -> Optional[Coords]:
        ql = _build_ql(tokens, lat, lng, radius_m)
        try:
            async with httpx.AsyncClient(
                timeout=OVERPASS_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                r = await client.post(
                    API_URL,
                    content=f"data={ql}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"overpass http: {type(e).__name__}: {e}") from e
        except ValueError as e:
            # JSON 解析錯誤
            raise ProviderError(f"overpass invalid json: {e}") from e

        elements = data.get("elements") or []
        if not elements:
            return None

        # 挑離 hint_coords 最近的元素
        best: Optional[tuple[float, float, dict, float]] = None
        for el in elements:
            el_lat, el_lng = _element_coords(el)
            if el_lat is None or el_lng is None:
                continue
            d = haversine_m(lat, lng, el_lat, el_lng)
            if best is None or d < best[3]:
                best = (el_lat, el_lng, el, d)
        if not best:
            return None
        b_lat, b_lng, b_el, _ = best
        name = (b_el.get("tags") or {}).get("name") or original_query
        log.info(
            "overpass hit",
            lat=b_lat, lng=b_lng,
            canonical=name,
            tokens=tokens,
            radius_m=radius_m,
        )
        return Coords(
            lat=b_lat,
            lng=b_lng,
            source=self.name,
            matched_query=original_query,
            canonical_name=name,
        )


overpass = OverpassProvider()
