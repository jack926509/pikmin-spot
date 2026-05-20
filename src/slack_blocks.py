from typing import Optional
from urllib.parse import quote

from src.formatter import (
    format_no_coords,
    format_success,
    google_maps_url,
    google_search_url,
)
from src.models import Coords, PlaceCandidates


def text_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def _apple_maps_url(lat: float, lng: float) -> str:
    return f"https://maps.apple.com/?ll={lat},{lng}&q={lat},{lng}"


def _osm_url(lat: float, lng: float) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}"


def _wikipedia_search_url(name: str) -> str:
    return f"https://en.wikipedia.org/w/index.php?search={quote(name)}"


def success_blocks(
    place: PlaceCandidates,
    coords: Coords,
    mention_user: Optional[str] = None,
) -> list[dict]:
    """成功回覆 blocks。
    mention_user: 若提供且非空,在訊息頂端 @-mention 該使用者讓他收到推播通知。
                  DM 不需要(自然會通知),只在 channel 中使用。
    """
    body = format_success(place, coords)
    if mention_user:
        body = f"<@{mention_user}>\n{body}"

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🗺 Google Maps", "emoji": True},
                    "url": google_maps_url(coords.lat, coords.lng),
                    "action_id": "open_gmaps",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🍎 Apple Maps", "emoji": True},
                    "url": _apple_maps_url(coords.lat, coords.lng),
                    "action_id": "open_apple_maps",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🌐 OSM", "emoji": True},
                    "url": _osm_url(coords.lat, coords.lng),
                    "action_id": "open_osm",
                },
            ],
        },
    ]


def no_coords_blocks(
    place: PlaceCandidates,
    mention_user: Optional[str] = None,
) -> list[dict]:
    name = place.candidates[0] if place.candidates else "Unknown"
    body = format_no_coords(place)
    if mention_user:
        body = f"<@{mention_user}>\n{body}"

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔎 Google 搜尋", "emoji": True},
                    "url": google_search_url(name, place.country or ""),
                    "action_id": "open_search",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📚 Wikipedia 搜尋", "emoji": True},
                    "url": _wikipedia_search_url(name),
                    "action_id": "open_wiki",
                },
            ],
        },
    ]
