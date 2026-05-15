from src.formatter import (
    format_no_coords,
    format_success,
    google_maps_url,
    google_search_url,
)
from src.models import Coords, PlaceCandidates


def text_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def success_blocks(place: PlaceCandidates, coords: Coords) -> list[dict]:
    maps_url = google_maps_url(coords.lat, coords.lng)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": format_success(place, coords)}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🗺 在 Google Maps 開啟", "emoji": True},
                    "url": maps_url,
                    "action_id": "open_gmaps",
                }
            ],
        },
    ]


def no_coords_blocks(place: PlaceCandidates) -> list[dict]:
    name = place.candidates[0] if place.candidates else "Unknown"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": format_no_coords(place)}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔎 用此名稱 Google 搜尋", "emoji": True},
                    "url": google_search_url(name, place.country or ""),
                    "action_id": "open_search",
                }
            ],
        },
    ]
