from typing import Optional

import httpx

from src.logger import get_logger
from src.models import Coords
from src.providers.base import (
    HTTP_TIMEOUT_SEC,
    USER_AGENT,
    GeocoderProvider,
    ProviderError,
    http_get_with_retry,
)

log = get_logger(__name__)

API_URL = "https://en.wikipedia.org/w/api.php"


class WikipediaProvider(GeocoderProvider):
    name = "wikipedia"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                title = await self._search(client, query)
                if not title:
                    return None
                latlng = await self._fetch_coords(client, title)
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
        except httpx.HTTPError as e:
            raise ProviderError(f"wikipedia http: {type(e).__name__}: {e}") from e

    async def _search(self, client: httpx.AsyncClient, query: str) -> Optional[str]:
        params = {
            "action": "opensearch",
            "search": query,
            "limit": 3,
            "format": "json",
        }
        r = await http_get_with_retry(client, API_URL, params=params)
        r.raise_for_status()
        data = r.json()
        # opensearch returns: [query, [titles], [descs], [urls]]
        if not isinstance(data, list) or len(data) < 2:
            return None
        titles = data[1] or []
        return titles[0] if titles else None

    async def _fetch_coords(
        self, client: httpx.AsyncClient, title: str
    ) -> Optional[tuple[float, float]]:
        params = {
            "action": "query",
            "prop": "coordinates",
            "titles": title,
            "format": "json",
        }
        r = await http_get_with_retry(client, API_URL, params=params)
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
