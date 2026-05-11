from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.models import Coords, PlaceCandidates


def google_maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lng}"


def google_search_url(name: str, country: str = "") -> str:
    q = name if not country else f"{name} {country}"
    return f"https://www.google.com/search?q={quote(q)}"


def _escape_md(text: str) -> str:
    """避開 parse_mode='Markdown' V1 的特殊字元。"""
    if not text:
        return ""
    out = text
    for ch in ("_", "*", "`", "[", "]"):
        out = out.replace(ch, f"\\{ch}")
    return out


def _location_line(place: PlaceCandidates) -> str:
    parts = [p for p in (place.country, place.region) if p]
    return " · ".join(parts)


def google_maps_keyboard(lat: float, lng: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🗺 在 Google Maps 開啟", url=google_maps_url(lat, lng))]]
    )


def google_search_keyboard(name: str, country: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔎 用此名稱 Google 搜尋", url=google_search_url(name, country))]]
    )


def format_success(place: PlaceCandidates, coords: Coords) -> str:
    name = place.candidates[0] if place.candidates else (coords.canonical_name or "Unknown")
    loc_line = _location_line(place)

    lines = [f"📍 *{_escape_md(name)}*"]
    if place.place_name_local and place.place_name_local != name:
        lines.append(_escape_md(place.place_name_local))
    if loc_line:
        lines.append(f"🌏 {_escape_md(loc_line)}")
    lines.append("")
    lines.append(f"🎯 `{coords.lat:.6f}, {coords.lng:.6f}`")
    if place.description:
        lines.append("")
        lines.append(f"📝 {_escape_md(place.description)}")
    lines.append("")
    lines.append(f"_資料來源:{coords.source} · 信心度:{place.confidence}_")
    return "\n".join(lines)


def format_no_coords(place: PlaceCandidates) -> str:
    name = place.candidates[0] if place.candidates else "Unknown"
    loc_line = _location_line(place)
    lines = [f"😢 *識別到「{_escape_md(name)}」但查不到精確座標*"]
    if loc_line:
        lines.append(f"🌏 {_escape_md(loc_line)}")
    if place.description:
        lines.append(f"📝 {_escape_md(place.description)}")
    return "\n".join(lines)


def format_unknown() -> str:
    return (
        "🤔 *看不出來這是哪個地標*\n\n"
        "試試:\n"
        "• 確認 TITLE 文字清楚可見(避免被裁切)\n"
        "• 上方距離欄、下方菇 3D 模型不算地標名\n"
        "• 換個更靠近地標的截圖"
    )


def format_vision_failed() -> str:
    return (
        "⚠️ *識別暫時失敗*\n\n"
        "可能原因:AI 服務忙線或網路不穩。\n"
        "請過幾秒重傳同一張即可。"
    )
