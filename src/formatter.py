from urllib.parse import quote

from src.models import Coords, PlaceCandidates


def google_maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lng}"


def google_search_url(name: str, country: str = "") -> str:
    q = name if not country else f"{name} {country}"
    return f"https://www.google.com/search?q={quote(q)}"


def _escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn 僅 < > & 三個字元需要 HTML-escape。
    其餘 *, _, `, ~ 由我們自己控制成對使用,不需逃逸使用者欄位中的單一出現。"""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _location_line(place: PlaceCandidates) -> str:
    parts = [p for p in (place.country, place.region) if p]
    return " · ".join(parts)


def _accuracy_label(coords: Coords) -> str:
    """根據 is_approximate 與 accuracy_m 給人類可讀的精度標籤。"""
    if not coords.is_approximate:
        return "精確"
    acc = coords.accuracy_m or 2000
    if acc < 300:
        return f"高精度(±{acc}m)"
    if acc < 1500:
        return f"中精度(±{acc}m)"
    return f"區域估計(±{acc}m)"


def format_success(place: PlaceCandidates, coords: Coords) -> str:
    name = place.candidates[0] if place.candidates else (coords.canonical_name or "Unknown")
    loc_line = _location_line(place)

    lines = [f"📍 *{_escape_mrkdwn(name)}*"]
    if place.place_name_local and place.place_name_local != name:
        lines.append(_escape_mrkdwn(place.place_name_local))
    if loc_line:
        lines.append(f"🌏 {_escape_mrkdwn(loc_line)}")
    lines.append("")

    if coords.is_approximate:
        lines.append(f"🎯 `{coords.lat:.6f}, {coords.lng:.6f}` _(大致位置)_")
        lines.append(
            f"⚠️ 找不到此地標的精確登錄,以下為推估:_{_accuracy_label(coords)}_"
        )
    else:
        lines.append(f"🎯 `{coords.lat:.6f}, {coords.lng:.6f}`")

    if place.description:
        lines.append("")
        lines.append(f"📝 {_escape_mrkdwn(place.description)}")
    lines.append("")

    src_label = coords.source
    if coords.source == "llm_rerank":
        src_label = "AI 推理(線索整合)"
    lines.append(f"_資料來源:{src_label} · 信心度:{place.confidence}_")
    return "\n".join(lines)


def format_no_coords(place: PlaceCandidates) -> str:
    name = place.candidates[0] if place.candidates else "Unknown"
    loc_line = _location_line(place)
    lines = [f"😢 *識別到「{_escape_mrkdwn(name)}」但查不到精確座標*"]
    if loc_line:
        lines.append(f"🌏 {_escape_mrkdwn(loc_line)}")
    if place.description:
        lines.append(f"📝 {_escape_mrkdwn(place.description)}")
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
