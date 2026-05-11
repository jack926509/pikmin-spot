import asyncio
from typing import Optional

from src.logger import get_logger
from src.models import Coords, PlaceCandidates
from src.providers.base import GeocoderProvider, ProviderError
from src.providers.nominatim import nominatim
from src.providers.photon import photon
from src.providers.wikidata import wikidata
from src.providers.wikipedia import wikipedia

log = get_logger(__name__)

DEFAULT_PROVIDERS: list[GeocoderProvider] = [wikidata, wikipedia, nominatim, photon]
SLOW_PROVIDER_NAMES = {"nominatim"}  # 受 1 req/sec 限速;僅作為 fallback


def build_queries(place: PlaceCandidates) -> list[str]:
    """生 N 條查詢字串(已去重、保序)。"""
    cands = place.candidates or []
    country = (place.country or "").strip()
    region = (place.region or "").strip()
    local = (place.place_name_local or "").strip()
    hints = place.search_hints or []

    raw: list[str] = []
    if cands:
        if region and country:
            raw.append(f"{cands[0]}, {region}, {country}")
        if country:
            raw.append(f"{cands[0]}, {country}")
    if len(cands) > 1 and country:
        raw.append(f"{cands[1]}, {country}")
    if len(cands) > 2 and country:
        raw.append(f"{cands[2]}, {country}")
    if local and country:
        raw.append(f"{local}, {country}")
    if cands:
        raw.append(cands[0])
    if hints and country:
        raw.append(f"{hints[0]}, {country}")
    if local and not country:
        raw.append(local)

    seen: set[str] = set()
    out: list[str] = []
    for q in raw:
        q = q.strip().strip(",").strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


async def _safe_lookup(
    provider: GeocoderProvider, query: str, hint_country: str
) -> Optional[Coords]:
    """provider.lookup 的非拋出版本,錯誤吃掉並 log。"""
    try:
        return await provider.lookup(query, hint_country)
    except asyncio.CancelledError:
        raise
    except ProviderError as e:
        log.warning(
            "provider error", provider=provider.name, query=query, error=str(e)
        )
        return None
    except Exception as e:
        log.warning(
            "provider crash", provider=provider.name, query=query, error=str(e)
        )
        return None


async def _parallel_first_hit(
    providers: list[GeocoderProvider], query: str, hint_country: str
) -> Optional[Coords]:
    """同時 fire 一組 fast providers,依優先序回傳第一個 non-None。
    命中後取消剩餘 tasks 避免浪費 HTTP 工。"""
    if not providers:
        return None
    tasks = [
        asyncio.create_task(_safe_lookup(p, query, hint_country)) for p in providers
    ]
    try:
        for i, p in enumerate(providers):
            result = await tasks[i]
            if result:
                log.info(
                    "hit",
                    query=query,
                    provider=p.name,
                    lat=result.lat,
                    lng=result.lng,
                )
                return result
        return None
    finally:
        pending = [t for t in tasks if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def resolve(
    place: PlaceCandidates,
    providers: Optional[list[GeocoderProvider]] = None,
) -> Optional[Coords]:
    """對每個 query 平行查 fast providers,全 miss 才依序 fallback 到 slow。
    任一命中立即回傳,優先序由 providers 陣列順序決定。"""
    providers = providers if providers is not None else DEFAULT_PROVIDERS
    queries = build_queries(place)
    if not queries:
        log.warning("resolve: empty queries")
        return None

    fast = [p for p in providers if p.name not in SLOW_PROVIDER_NAMES]
    slow = [p for p in providers if p.name in SLOW_PROVIDER_NAMES]

    for q in queries:
        result = await _parallel_first_hit(fast, q, place.country)
        if result:
            return result
        for p in slow:
            r = await _safe_lookup(p, q, place.country)
            if r:
                log.info("hit", query=q, provider=p.name, lat=r.lat, lng=r.lng)
                return r

    log.info("resolve: no hit", n_queries=len(queries))
    return None
