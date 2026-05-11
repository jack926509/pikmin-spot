from src.formatter import (
    _escape_md,
    format_no_coords,
    format_success,
    format_unknown,
    format_vision_failed,
    google_maps_keyboard,
    google_maps_url,
    google_search_keyboard,
    google_search_url,
)
from src.models import Coords, PlaceCandidates


def test_google_maps_url_basic():
    assert google_maps_url(35.6586, 139.7454) == "https://www.google.com/maps?q=35.6586,139.7454"


def test_google_search_url_url_encodes_spaces_and_unicode():
    url = google_search_url("Tokyo Tower", "Japan")
    assert url.startswith("https://www.google.com/search?q=")
    assert "Tokyo%20Tower%20Japan" in url

    url2 = google_search_url("東京タワー", "")
    assert "%E6%9D%B1%E4%BA%AC" in url2  # 東京 URL-encoded


def test_escape_md_handles_special_chars():
    assert _escape_md("a_b*c[d]`e") == "a\\_b\\*c\\[d\\]\\`e"
    assert _escape_md("") == ""
    assert _escape_md("plain") == "plain"


def test_google_maps_keyboard_structure():
    kb = google_maps_keyboard(1.0, 2.0)
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert btn.url == "https://www.google.com/maps?q=1.0,2.0"
    assert "Google Maps" in btn.text


def test_google_search_keyboard_structure():
    kb = google_search_keyboard("Tokyo Tower", "Japan")
    btn = kb.inline_keyboard[0][0]
    assert btn.url.startswith("https://www.google.com/search?q=")
    assert "Google" in btn.text


def test_format_success_renders_all_fields():
    place = PlaceCandidates(
        candidates=["Tokyo Tower"],
        place_name_local="東京タワー",
        country="Japan",
        region="Tokyo",
        description="Communications tower",
        confidence="high",
    )
    coords = Coords(lat=35.6586, lng=139.7454, source="wikidata", matched_query="x")
    out = format_success(place, coords)
    assert "*Tokyo Tower*" in out
    assert "東京タワー" in out
    assert "Japan · Tokyo" in out
    assert "35.658600, 139.745400" in out
    assert "wikidata" in out
    # 新版不再內嵌 Google Maps 文字連結(改用 inline keyboard)
    assert "[Google Maps]" not in out


def test_format_success_skips_local_when_same_as_primary():
    place = PlaceCandidates(
        candidates=["Tokyo Tower"],
        place_name_local="Tokyo Tower",
        country="Japan",
    )
    coords = Coords(lat=0, lng=0, source="x", matched_query="x")
    out = format_success(place, coords)
    # 應只出現一次
    assert out.count("Tokyo Tower") == 1


def test_format_no_coords_includes_name_and_loc():
    place = PlaceCandidates(
        candidates=["Mystery Spot"],
        country="Nowhere",
    )
    out = format_no_coords(place)
    assert "Mystery Spot" in out
    assert "Nowhere" in out


def test_format_unknown_and_vision_failed_are_non_empty():
    assert format_unknown().strip()
    assert format_vision_failed().strip()
