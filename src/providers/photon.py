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

API_URL = "https://photon.komoot.io/api"


class PhotonProvider(GeocoderProvider):
    name = "photon"

    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        if not query.strip():
            return None
        params = {"q": query, "limit": 1, "lang": "en"}
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                r = await client.get(API_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"photon http: {type(e).__name__}: {e}") from e
        features = data.get("features") or []
        if not features:
            return None
        feat = features[0]
        try:
            lng, lat = feat["geometry"]["coordinates"][:2]
            lat = float(lat)
            lng = float(lng)
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        canonical = (feat.get("properties") or {}).get("name")
        return Coords(
            lat=lat,
            lng=lng,
            source=self.name,
            matched_query=query,
            canonical_name=canonical,
        )


photon = PhotonProvider()
