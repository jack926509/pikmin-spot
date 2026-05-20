from src.providers._geo import country_to_cc, haversine_m, wiki_langs_for


def test_country_to_cc_basic():
    assert country_to_cc("Japan") == "jp"
    assert country_to_cc("United States") == "us"
    assert country_to_cc("USA") == "us"
    assert country_to_cc("United Kingdom") == "gb"
    assert country_to_cc("Bhutan") == "bt"


def test_country_to_cc_handles_cjk_names():
    assert country_to_cc("日本") == "jp"
    assert country_to_cc("台灣") == "tw"
    assert country_to_cc("中国") == "cn"


def test_country_to_cc_strips_region_prefix():
    # 'Salvo, North Carolina, USA' 取最後段 USA → us
    assert country_to_cc("Salvo, North Carolina, USA") == "us"
    assert country_to_cc("Paro, Bhutan") == "bt"


def test_country_to_cc_unknown_returns_none():
    assert country_to_cc("Atlantis") is None
    assert country_to_cc("") is None


def test_wiki_langs_for_country_only():
    # Japan 國家 → ja
    langs = wiki_langs_for("Japan")
    assert langs[0] == "en"
    assert "ja" in langs


def test_wiki_langs_for_detects_script():
    # CJK 字串自動加對應 wiki
    langs = wiki_langs_for("", "東京タワー")
    assert "ja" in langs
    langs = wiki_langs_for("", "故宮")
    # 中文字也偵測為 zh(無國家 hint 時)
    assert "zh" in langs


def test_wiki_langs_for_korean():
    langs = wiki_langs_for("South Korea", "경복궁")
    assert "ko" in langs


def test_haversine_m_zero_distance():
    assert haversine_m(35.0, 139.0, 35.0, 139.0) == 0.0


def test_haversine_m_known_distance():
    # Tokyo Tower → Osaka Castle ≈ 400 km
    d = haversine_m(35.6586, 139.7454, 34.6873, 135.5262)
    assert 390_000 < d < 410_000


def test_haversine_m_far_apart():
    # NY → Tokyo ≈ 10,800 km
    d = haversine_m(40.7128, -74.0060, 35.6762, 139.6503)
    assert 10_000_000 < d < 11_500_000
