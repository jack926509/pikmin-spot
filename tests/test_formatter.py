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


def test_format_success_marks_approximate_clearly():
    place = PlaceCandidates(candidates=["X"], country="USA")
    coords = Coords(
        lat=35.5, lng=-75.5, source="llm_rerank",
        matched_query="X", is_approximate=True, accuracy_m=1500,
    )
    out = format_success(place, coords)
    assert "大致位置" in out
    assert "區域估計" in out or "中精度" in out or "±1500m" in out


def test_format_success_translates_llm_rerank_source():
    place = PlaceCandidates(candidates=["X"], country="USA")
    coords = Coords(
        lat=35.5, lng=-75.5, source="llm_rerank",
        matched_query="X", is_approximate=True, accuracy_m=1500,
    )
    out = format_success(place, coords)
    assert "AI 推理" in out
    assert "llm_rerank" not in out


def test_format_success_omits_approximate_warning_when_exact():
    place = PlaceCandidates(candidates=["X"], country="USA")
    coords = Coords(
        lat=35.5, lng=-75.5, source="wikidata",
        matched_query="X", is_approximate=False,
    )
    out = format_success(place, coords)
    assert "大致位置" not in out
    assert "推估" not in out


def test_success_blocks_includes_apple_maps_button():
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = Coords(lat=1.0, lng=2.0, source="wikidata", matched_query="x")
    blocks = success_blocks(place, coords)
    actions = next(b for b in blocks if b["type"] == "actions")
    urls = [e["url"] for e in actions["elements"]]
    assert any("maps.apple.com" in u for u in urls)
    assert any("google.com/maps" in u for u in urls)
    assert any("openstreetmap.org" in u for u in urls)


def test_success_blocks_prepends_mention_when_user_provided():
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = Coords(lat=1.0, lng=2.0, source="x", matched_query="x")
    blocks = success_blocks(place, coords, mention_user="U123")
    body = blocks[0]["text"]["text"]
    assert body.startswith("<@U123>")


def test_success_blocks_omits_mention_when_user_none():
    place = PlaceCandidates(candidates=["X"], country="C")
    coords = Coords(lat=1.0, lng=2.0, source="x", matched_query="x")
    blocks = success_blocks(place, coords, mention_user=None)
    body = blocks[0]["text"]["text"]
    assert "<@" not in body


def test_no_coords_blocks_includes_wikipedia_button():
    place = PlaceCandidates(candidates=["Mystery"], country="Nowhere")
    blocks = no_coords_blocks(place)
    actions = next(b for b in blocks if b["type"] == "actions")
    urls = [e["url"] for e in actions["elements"]]
    assert any("wikipedia.org" in u for u in urls)
    assert any("google.com/search" in u for u in urls)
