import asyncio
from typing import Optional

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

API_URL = "https://nominatim.openstreetmap.org/search"

_rate_lock = asyncio.Lock()


class NominatimProvider(GeocoderProvider):
    name = "nominatim"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        params: dict = {
            "q": query,
            "format": "json",
            "limit": 5,
            "addressdetails": 1,
        }
        cc = country_to_cc(hint_country)
        if cc:
            params["countrycodes"] = cc
        # accept-language 影響 display_name 的語言,有助 canonical 標示
        if cc in ("jp",):
            params["accept-language"] = "ja,en"
        elif cc in ("cn", "tw", "hk", "mo"):
            params["accept-language"] = "zh,en"
        elif cc == "kr":
            params["accept-language"] = "ko,en"
        else:
            params["accept-language"] = "en"

        async with _rate_lock:
            try:
                async with httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT_SEC,
                    headers={"User-Agent": USER_AGENT},
                ) as client:
                    r = await http_get_with_retry(client, API_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
            except httpx.HTTPError as e:
                await asyncio.sleep(1.0)
                raise ProviderError(f"nominatim http: {type(e).__name__}: {e}") from e
            await asyncio.sleep(1.0)
        if not data:
            return None

        first = self._pick_best(data, cc)
        if not first:
            return None
        try:
            lat = float(first["lat"])
            lon = float(first["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        return Coords(
            lat=lat,
            lng=lon,
            source=self.name,
            matched_query=query,
            canonical_name=first.get("display_name"),
        )

    def _pick_best(
        self, results: list[dict], expected_cc: Optional[str]
    ) -> Optional[dict]:
        """從多筆候選挑最佳:優先匹配國家碼,再退而求其次。"""
        if not results:
            return None
        if expected_cc:
            for r in results:
                addr = r.get("address") or {}
                rcc = (addr.get("country_code") or "").lower()
                if rcc == expected_cc:
                    return r
        return results[0]


nominatim = NominatimProvider()
