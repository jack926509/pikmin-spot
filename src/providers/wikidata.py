import re
from typing import Any, Optional

import httpx

from src.logger import get_logger
from src.models import Coords
from src.providers._geo import country_to_cc
from src.providers.base import (
    HTTP_TIMEOUT_SEC,
    USER_AGENT,
    GeocoderProvider,
    ProviderError,
    http_get_with_retry,
)

log = get_logger(__name__)

SEARCH_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL_TMPL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

GEO_KEYWORDS = (
    "temple", "tower", "mountain", "lake", "museum", "station", "palace",
    "monument", "park", "building", "church", "mosque", "shrine", "castle",
    "bridge", "cathedral", "monastery", "stupa", "pagoda", "fortress",
    "garden", "square", "plaza", "tomb", "river", "island", "waterfall",
    "valley", "hill", "peak", "village", "town", "city", "district",
    "harbour", "harbor", "port", "beach", "cape", "memorial", "statue",
    "lighthouse", "stadium", "arena", "library", "gallery",
    "chorten", "lhakhang", "dzong",
    # 擴充:Wayspot 常見類型
    "footbridge", "boardwalk", "trail", "trailhead", "playground",
    "fountain", "sculpture", "mural", "art installation", "gate",
    "historic", "historical marker", "plaque", "viewpoint", "lookout",
    "neighborhood", "neighbourhood", "community", "school", "university",
    "tourist attraction", "point of interest", "heritage",
    "公園", "神社", "寺", "塔", "橋", "城", "宮", "館", "院", "亭",
    "山", "湖", "川", "河", "島", "海岸",
)


def _is_geo_entity(description: str) -> bool:
    if not description:
        return False
    desc_low = description.lower()
    return any(kw in desc_low for kw in GEO_KEYWORDS)


def _has_cjk(s: str) -> bool:
    return bool(re.search(r"[ぁ-ヿ一-鿿가-힣]", s or ""))


class WikidataProvider(GeocoderProvider):
    name = "wikidata"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        # wbsearchentities is an entity-name search; address-style strings
        # like "Name, Region, Country" hurt recall. Use the leading name part.
        search_term = query.split(",", 1)[0].strip() or query

        # 搜尋語言:有 CJK 字串時加跑該語言;國家提示也加。英文永遠先試。
        languages = ["en"]
        cc = country_to_cc(hint_country)
        if _has_cjk(search_term):
            if re.search(r"[ぁ-ヿ]", search_term):
                languages.append("ja")
            elif re.search(r"[가-힣]", search_term):
                languages.append("ko")
            elif re.search(r"[一-鿿]", search_term):
                languages.append("zh")
        elif cc in ("jp",):
            languages.append("ja")
        elif cc in ("cn", "tw", "hk", "mo"):
            languages.append("zh")
        elif cc == "kr":
            languages.append("ko")
        # dedupe preserve order
        languages = list(dict.fromkeys(languages))

        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                hits: list[dict[str, Any]] = []
                for lang in languages:
                    found = await self._search(client, search_term, lang)
                    hits.extend(found)
                    if found:
                        # 已找到就先用,不一定要再跑下個語言
                        break
                if not hits:
                    return None
                hit = self._pick_best(hits, hint_country)
                if not hit:
                    return None
                qid = hit.get("id")
                label = hit.get("label") or hit.get("display", {}).get("label", {}).get("value")
                if not qid:
                    return None
                coords = await self._fetch_coords(client, qid)
                if not coords:
                    return None
                lat, lng = coords
                return Coords(
                    lat=lat,
                    lng=lng,
                    source=self.name,
                    matched_query=query,
                    canonical_name=label,
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"wikidata http: {type(e).__name__}: {e}") from e

    async def _search(
        self, client: httpx.AsyncClient, query: str, language: str = "en"
    ) -> list[dict[str, Any]]:
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": language,
            "format": "json",
            "type": "item",
            "limit": 7,
        }
        r = await http_get_with_retry(client, SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("search") or []

    def _pick_best(
        self, hits: list[dict[str, Any]], hint_country: str
    ) -> Optional[dict[str, Any]]:
        country_low = hint_country.lower().strip()
        geo_hits = [h for h in hits if _is_geo_entity(h.get("description", ""))]
        if country_low and geo_hits:
            for h in geo_hits:
                if country_low in (h.get("description", "") or "").lower():
                    return h
        if geo_hits:
            return geo_hits[0]
        return hits[0] if hits else None

    async def _fetch_coords(
        self, client: httpx.AsyncClient, qid: str
    ) -> Optional[tuple[float, float]]:
        url = ENTITY_URL_TMPL.format(qid=qid)
        r = await http_get_with_retry(client, url)
        r.raise_for_status()
        data = r.json()
        try:
            entity = data["entities"][qid]
            claim = entity["claims"]["P625"][0]
            value = claim["mainsnak"]["datavalue"]["value"]
            return float(value["latitude"]), float(value["longitude"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None


wikidata = WikidataProvider()
