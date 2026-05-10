from src.models import Coords, PlaceCandidates


def google_maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lng}"


def _escape_md(text: str) -> str:
    """避開 parse_mode='Markdown' 的特殊字元(_*[]`),不處理 V2。"""
    if not text:
        return ""
    out = text
    for ch in ("_", "*", "`", "[", "]"):
        out = out.replace(ch, f"\\{ch}")
    return out


def _location_line(place: PlaceCandidates) -> str:
    parts = [p for p in (place.country, place.region) if p]
    return " · ".join(parts)


def format_success(place: PlaceCandidates, coords: Coords) -> str:
    name = place.candidates[0] if place.candidates else (coords.canonical_name or "Unknown")
    loc_line = _location_line(place)
    url = google_maps_url(coords.lat, coords.lng)

    lines = [f"📍 *{_escape_md(name)}*"]
    if loc_line:
        lines.append(f"🌏 {_escape_md(loc_line)}")
    lines.append("")
    lines.append(f"🎯 座標:`{coords.lat:.6f}, {coords.lng:.6f}`")
    lines.append(f"🗺️ [Google Maps]({url})")
    if place.description:
        lines.append("")
        lines.append(f"📝 {_escape_md(place.description)}")
    lines.append(f"_資料來源:{coords.source} · 信心度:{place.confidence}_")
    return "\n".join(lines)


def format_no_coords(place: PlaceCandidates) -> str:
    name = place.candidates[0] if place.candidates else "Unknown"
    loc_line = _location_line(place)
    lines = [
        f"😢 識別到「{_escape_md(name)}」但找不到座標",
    ]
    if loc_line:
        lines.append(f"🌏 {_escape_md(loc_line)}")
    if place.description:
        lines.append(f"📝 {_escape_md(place.description)}")
    lines.append("")
    lines.append("可試試自行 Google 搜尋此名稱。")
    return "\n".join(lines)


def format_unknown() -> str:
    return (
        "🤔 無法識別這張圖中的地標\n"
        "請確認:\n"
        "・是 Pikmin Bloom 的菇點截圖\n"
        "・畫面中有清楚的地標名稱\n"
        "・圖片未過度裁切或模糊"
    )
