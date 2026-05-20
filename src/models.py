from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlaceCandidates:
    """Vision 識別結果"""
    candidates: list[str]
    place_name_local: Optional[str] = None
    country: str = ""
    region: str = ""
    description: str = ""
    search_hints: list[str] = field(default_factory=list)
    confidence: str = "low"

    # v3 新增
    anchor_locations: list[str] = field(default_factory=list)
    """附近錨點(城市、街道、知名地標),用於 fallback 查詢與 rerank。"""

    is_likely_wayspot_only: bool = False
    """Vision 自評:此地標可能不在權威 DB,提早觸發 rerank。"""

    approximate_coords_guess: Optional[tuple[float, float, int]] = None
    """(lat, lng, accuracy_m) — Vision 直接猜測的粗座標,僅作為 rerank 輔助。"""


@dataclass
class Coords:
    lat: float
    lng: float
    source: str
    matched_query: str
    canonical_name: Optional[str] = None

    # v3 新增
    is_approximate: bool = False
    """True 表示這是 fallback 推算座標,可能誤差 100~2000m。"""

    accuracy_m: Optional[int] = None
    """估計誤差半徑(公尺)。"""
