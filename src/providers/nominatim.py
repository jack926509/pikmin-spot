import asyncio
from typing import Optional

import httpx

from src.logger import get_logger
from src.models import Coords
from src.providers.base import (
    HTTP_TIMEOUT_SEC,
    USER_AGENT,
    GeocoderProvider,
    ProviderError,
)

log = get_logger(__name__)

API_URL = "https://nominatim.openstreetmap.org/search"

_rate_lock = asyncio.Lock()


class NominatimProvider(GeocoderProvider):
    name = "nominatim"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "addressdetails": 0,
        }
        async with _rate_lock:
            try:
                async with httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT_SEC,
                    headers={"User-Agent": USER_AGENT},
                ) as client:
                    r = await client.get(API_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
            except httpx.HTTPError as e:
                await asyncio.sleep(1.0)
                raise ProviderError(f"nominatim http: {type(e).__name__}: {e}") from e
            await asyncio.sleep(1.0)
        if not data:
            return None
        first = data[0]
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


nominatim = NominatimProvider()
