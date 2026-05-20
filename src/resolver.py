"""級聯解析器 v3。

主要改進(相對 v2):
1. 全 miss 時,呼叫 llm_rerank.llm_final_reasoning 做最後推理
2. 平行查詢時,蒐集「次優命中」作為 anchor_coords 餵給 rerank
3. build_queries 加入冠詞剝除、行政區 fallback、核心名抽取
4. Vision 直接給的 approximate_coords_guess 也視為 rerank 輔助線索
"""

import asyncio
import re
from typing import Optional

from src.llm_rerank import RerankError, llm_final_reasoning
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

# 通用詞 stopword:抽核心名時要剝掉
_GENERIC_TOKENS = {
    "the", "community", "neighborhood", "neighbourhood",
    "beach", "park", "trail", "trailhead", "garden",
    "memorial", "plaza", "square", "footbridge", "bridge",
    "boardwalk", "walk", "walkway", "path", "access",
    "marker", "sign", "monument", "statue", "sculpture",
    "mural", "fountain", "playground",
    "of", "and", "at", "on", "in",
}

_LEADING_THE = re.compile(r"^\s*the\s+", re.IGNORECASE)


def _strip_leading_the(s: str) -> str:
    return _LEADING_THE.sub("", s).strip()


def _extract_core_name(name: str) -> str:
    """從 'The Farrow Community Beach Footbridge' 抽出 'Farrow'。
    保留首個非通用詞作為核心名。若無法抽,回原字串。"""
    tokens = re.findall(r"[A-Za-z一-鿿぀-ヿ]+", name)
    if not tokens:
        return name
    core = [t for t in tokens if t.lower() not in _GENERIC_TOKENS]
    if not core:
        return name
    return core[0]


def build_queries(place: PlaceCandidates) -> list[str]:
    """生 N 條查詢字串(已去重、保序)。"""
    cands = place.candidates or []
    country = (place.country or "").strip()
    region = (place.region or "").strip()
    local = (place.place_name_local or "").strip()
    hints = place.search_hints or []
    anchors = place.anchor_locations or []

    raw: list[str] = []

    # === 原有四輪:完整候選名 × 地理上下文 ===
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

    # === v3 新輪 1:冠詞剝除 ===
    for c in cands[:2]:
        stripped = _strip_leading_the(c)
        if stripped and stripped.lower() != c.lower():
            if country:
                raw.append(f"{stripped}, {country}")
            raw.append(stripped)

    # === v3 新輪 2:核心名抽取 ===
    for c in cands[:2]:
        core = _extract_core_name(c)
        if core and core.lower() != c.lower() and len(core) >= 3:
            if region and country:
                raw.append(f"{core}, {region}, {country}")
            if region:
                raw.append(f"{core}, {region}")

    # === v3 新輪 3:anchor_locations 直查 ===
    for a in anchors[:3]:
        if country:
            raw.append(f"{a}, {country}")
        raw.append(a)

    # === v3 新輪 4:純行政區 fallback ===
    if region and country:
        raw.append(f"{region}, {country}")
    elif region:
        raw.append(region)

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
    providers: list[GeocoderProvider],
    query: str,
    hint_country: str,
    anchor_collector: Optional[list[Coords]] = None,
) -> Optional[Coords]:
    """同時 fire 一組 fast providers,依優先序回傳第一個 non-None。
    新增:把次優結果也蒐集進 anchor_collector(若提供),供 rerank 用。"""
    if not providers:
        return None
    tasks = [
        asyncio.create_task(_safe_lookup(p, query, hint_country)) for p in providers
    ]
    hit: Optional[Coords] = None
    try:
        for i, p in enumerate(providers):
            result = await tasks[i]
            if result and hit is None:
                log.info(
                    "hit",
                    query=query,
                    provider=p.name,
                    lat=result.lat,
                    lng=result.lng,
                )
                hit = result
            elif result and anchor_collector is not None:
                anchor_collector.append(result)
        return hit
    finally:
        pending = [t for t in tasks if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def resolve(
    place: PlaceCandidates,
    providers: Optional[list[GeocoderProvider]] = None,
    enable_rerank: bool = True,
) -> Optional[Coords]:
    """新版 resolve:cascade 全 miss 時觸發 LLM rerank 推理。

    Args:
        place: Vision 識別結果
        providers: 自訂 provider 清單(測試用)
        enable_rerank: 是否啟用 LLM rerank fallback(預設 True)
    """
    providers = providers if providers is not None else DEFAULT_PROVIDERS
    queries = build_queries(place)
    if not queries:
        log.warning("resolve: empty queries")
        if enable_rerank and place.approximate_coords_guess:
            return await _try_rerank(place, [])
        return None

    fast = [p for p in providers if p.name not in SLOW_PROVIDER_NAMES]
    slow = [p for p in providers if p.name in SLOW_PROVIDER_NAMES]

    anchor_coords: list[Coords] = []

    for q in queries:
        result = await _parallel_first_hit(
            fast, q, place.country, anchor_collector=anchor_coords
        )
        if result:
            return result
        for p in slow:
            r = await _safe_lookup(p, q, place.country)
            if r:
                log.info("hit", query=q, provider=p.name, lat=r.lat, lng=r.lng)
                return r

    log.info(
        "resolve: cascade miss",
        n_queries=len(queries),
        n_anchors=len(anchor_coords),
    )

    if enable_rerank:
        return await _try_rerank(place, anchor_coords)

    return None


async def _try_rerank(
    place: PlaceCandidates, anchor_coords: list[Coords]
) -> Optional[Coords]:
    """LLM rerank fallback,捕捉所有錯誤防止把整個流程拖垮。"""
    try:
        result = await llm_final_reasoning(
            place=place,
            anchor_coords=anchor_coords,
            vision_coords_guess=place.approximate_coords_guess,
        )
        if result:
            log.info(
                "rerank: returned",
                lat=result.lat,
                lng=result.lng,
                accuracy_m=result.accuracy_m,
            )
        return result
    except RerankError as e:
        log.warning("rerank failed", error=str(e))
        return None
    except Exception as e:
        log.exception("rerank crash", error=str(e))
        return None
