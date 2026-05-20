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

API_URL = "https://photon.komoot.io/api"


class PhotonProvider(GeocoderProvider):
    name = "photon"

    async def lookup(
        self,
        query: str,
        hint_country: str = "",
        hint_coords: Optional[tuple[float, float, int]] = None,
    ) -> Optional[Coords]:
        if not query.strip():
            return None
        params: dict = {"q": query, "limit": 5, "lang": "en"}
        cc = country_to_cc(hint_country)
        # 地理偏置 —— 若 vision 提供粗座標,Photon 大幅優先返回該區域結果。
        # location_bias_scale 0.1 偏強(範圍 0.1~10,越小偏置越強)。
        if hint_coords:
            lat, lng, _ = hint_coords
            params["lat"] = lat
            params["lon"] = lng
            params["location_bias_scale"] = 0.1
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                r = await http_get_with_retry(client, API_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"photon http: {type(e).__name__}: {e}") from e
        features = data.get("features") or []
        if not features:
            return None

        chosen = self._pick_best(features, cc)
        if not chosen:
            return None
        try:
            lng, lat = chosen["geometry"]["coordinates"][:2]
            lat = float(lat)
            lng = float(lng)
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        canonical = (chosen.get("properties") or {}).get("name")
        return Coords(
            lat=lat,
            lng=lng,
            source=self.name,
            matched_query=query,
            canonical_name=canonical,
        )

    def _pick_best(
        self, features: list[dict], expected_cc: Optional[str]
    ) -> Optional[dict]:
        if not features:
            return None
        if expected_cc:
            for f in features:
                props = f.get("properties") or {}
                fcc = (props.get("countrycode") or "").lower()
                if fcc == expected_cc:
                    return f
        return features[0]


photon = PhotonProvider()
