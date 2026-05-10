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


async def resolve(
    place: PlaceCandidates,
    providers: Optional[list[GeocoderProvider]] = None,
) -> Optional[Coords]:
    """對每個 query × 每個 provider 級聯查詢。任一命中立即回傳。全失敗回 None。"""
    providers = providers if providers is not None else DEFAULT_PROVIDERS
    queries = build_queries(place)
    if not queries:
        log.warning("resolve: empty queries")
        return None

    for q in queries:
        for p in providers:
            try:
                result = await p.lookup(q, place.country)
            except ProviderError as e:
                log.warning("provider error", provider=p.name, query=q, error=str(e))
                continue
            except Exception as e:
                log.warning("provider crash", provider=p.name, query=q, error=str(e))
                continue
            if result:
                log.info("hit", query=q, provider=p.name,
                         lat=result.lat, lng=result.lng)
                return result
    log.info("resolve: no hit", n_queries=len(queries))
    return None
