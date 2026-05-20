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

    async def lookup(
        self,
        query: str,
        hint_country: str = "",
        hint_coords: Optional[tuple[float, float, int]] = None,
    ) -> Optional[Coords]:
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
        # 地理偏置 —— 若有粗座標,給一個 viewbox 軟性偏好(bounded=0)。
        # 半徑取 max(50km, accuracy_m × 50) 換算成緯度/經度度數。
        if hint_coords:
            lat, lng, acc_m = hint_coords
            radius_m = max(50_000, acc_m * 50)
            lat_delta = radius_m / 111_000.0
            # 經度每度長度 = 111 km × cos(緯度)
            import math
            cos_lat = max(0.1, math.cos(math.radians(lat)))
            lng_delta = radius_m / (111_000.0 * cos_lat)
            # viewbox 順序:left,top,right,bottom (即 west,north,east,south)
            params["viewbox"] = (
                f"{lng - lng_delta},{lat + lat_delta},"
                f"{lng + lng_delta},{lat - lat_delta}"
            )
            params["bounded"] = 0  # soft bias,不強制限制

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
