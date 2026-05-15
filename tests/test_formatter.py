from src.formatter import (
    _escape_mrkdwn,
    format_no_coords,
    format_success,
    format_unknown,
    format_vision_failed,
    google_maps_url,
    google_search_url,
)
from src.models import Coords, PlaceCandidates
from src.slack_blocks import no_coords_blocks, success_blocks, text_blocks


def test_google_maps_url_basic():
    assert google_maps_url(35.6586, 139.7454) == "https://www.google.com/maps?q=35.6586,139.7454"


def test_google_search_url_url_encodes_spaces_and_unicode():
    url = google_search_url("Tokyo Tower", "Japan")
    assert url.startswith("https://www.google.com/search?q=")
    assert "Tokyo%20Tower%20Japan" in url

    url2 = google_search_url("東京タワー", "")
    assert "%E6%9D%B1%E4%BA%AC" in url2  # 東京 URL-encoded


def test_escape_mrkdwn_handles_html_specials():
    assert _escape_mrkdwn("A & B <c> d") == "A &amp; B &lt;c&gt; d"
    assert _escape_mrkdwn("") == ""
    assert _escape_mrkdwn("plain") == "plain"
    # 不額外逃逸 *, _, `, ~ — 由呼叫端決定。
    assert _escape_mrkdwn("a_b*c`d~e") == "a_b*c`d~e"


def test_success_blocks_structure():
    place = PlaceCandidates(candidates=["Tokyo Tower"], country="Japan")
    coords = Coords(lat=1.0, lng=2.0, source="wikidata", matched_query="x")
    blocks = success_blocks(place, coords)
    types = [b["type"] for b in blocks]
    assert "section" in types and "actions" in types
    btn = next(b for b in blocks if b["type"] == "actions")["elements"][0]
    assert btn["url"] == "https://www.google.com/maps?q=1.0,2.0"
    assert btn["type"] == "button"


def test_no_coords_blocks_has_search_button():
    place = PlaceCandidates(candidates=["Mystery"], country="Nowhere")
    blocks = no_coords_blocks(place)
    btn = next(b for b in blocks if b["type"] == "actions")["elements"][0]
    assert btn["url"].startswith("https://www.google.com/search?q=")
    assert "Mystery" in btn["url"]
    assert "Nowhere" in btn["url"]


def test_text_blocks_simple():
    blocks = text_blocks("hello")
    assert blocks == [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]


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


def test_format_success_skips_local_when_same_as_primary():
    place = PlaceCandidates(
        candidates=["Tokyo Tower"],
        place_name_local="Tokyo Tower",
        country="Japan",
    )
    coords = Coords(lat=0, lng=0, source="x", matched_query="x")
    out = format_success(place, coords)
    assert out.count("Tokyo Tower") == 1


def test_format_success_escapes_html_specials_in_name():
    place = PlaceCandidates(candidates=["A&B <Spot>"], country="X")
    coords = Coords(lat=0, lng=0, source="x", matched_query="x")
    out = format_success(place, coords)
    assert "A&amp;B &lt;Spot&gt;" in out
    assert "<Spot>" not in out


def test_format_no_coords_includes_name_and_loc():
    place = PlaceCandidates(candidates=["Mystery Spot"], country="Nowhere")
    out = format_no_coords(place)
    assert "Mystery Spot" in out
    assert "Nowhere" in out


def test_format_unknown_and_vision_failed_are_non_empty():
    assert format_unknown().strip()
    assert format_vision_failed().strip()
