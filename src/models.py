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


@dataclass
class Coords:
    lat: float
    lng: float
    source: str
    matched_query: str
    canonical_name: Optional[str] = None
