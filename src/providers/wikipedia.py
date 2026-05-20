from typing import Optional

import httpx

from src.logger import get_logger
from src.models import Coords
from src.providers._geo import wiki_langs_for
from src.providers.base import (
    HTTP_TIMEOUT_SEC,
    USER_AGENT,
    GeocoderProvider,
    ProviderError,
    http_get_with_retry,
)

log = get_logger(__name__)

_DEFAULT_LANG = "en"


def _api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


class WikipediaProvider(GeocoderProvider):
    name = "wikipedia"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        langs = wiki_langs_for(hint_country, query) or [_DEFAULT_LANG]
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                for lang in langs:
                    coords = await self._try_lang(client, lang, query)
                    if coords:
                        return coords
                return None
        except httpx.HTTPError as e:
            raise ProviderError(f"wikipedia http: {type(e).__name__}: {e}") from e

    async def _try_lang(
        self, client: httpx.AsyncClient, lang: str, query: str
    ) -> Optional[Coords]:
        api = _api_url(lang)
        # 1) opensearch:標題前綴/精準匹配最快
        title = await self._opensearch(client, api, query)
        # 2) fallback:full-text srsearch(opensearch miss 時用)
        if not title:
            title = await self._srsearch(client, api, query)
        if not title:
            return None
        latlng = await self._fetch_coords(client, api, title)
        if not latlng:
            return None
        lat, lng = latlng
        return Coords(
            lat=lat,
            lng=lng,
            source=self.name,
            matched_query=query,
            canonical_name=title,
        )

    async def _opensearch(
        self, client: httpx.AsyncClient, api: str, query: str
    ) -> Optional[str]:
        params = {
            "action": "opensearch",
            "search": query,
            "limit": 3,
            "format": "json",
        }
        r = await http_get_with_retry(client, api, params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        titles = data[1] or []
        return titles[0] if titles else None

    async def _srsearch(
        self, client: httpx.AsyncClient, api: str, query: str
    ) -> Optional[str]:
        """全文搜尋,標題沒中時用內文比對找最相關文章。"""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 3,
            "format": "json",
        }
        r = await http_get_with_retry(client, api, params=params)
        r.raise_for_status()
        data = r.json()
        try:
            hits = data["query"]["search"]
            return hits[0]["title"] if hits else None
        except (KeyError, IndexError, TypeError):
            return None

    async def _fetch_coords(
        self, client: httpx.AsyncClient, api: str, title: str
    ) -> Optional[tuple[float, float]]:
        params = {
            "action": "query",
            "prop": "coordinates",
            "titles": title,
            "format": "json",
        }
        r = await http_get_with_retry(client, api, params=params)
        r.raise_for_status()
        data = r.json()
        try:
            pages = data["query"]["pages"]
            for _, page in pages.items():
                coords = page.get("coordinates") or []
                if coords:
                    c0 = coords[0]
                    return float(c0["lat"]), float(c0["lon"])
            return None
        except (KeyError, TypeError, ValueError):
            return None


wikipedia = WikipediaProvider()
