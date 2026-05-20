"""共用地理工具:國家名→ISO 代碼、haversine 距離。"""
import math
import re
from typing import Optional


# 涵蓋 Pikmin Bloom 主流用戶國家。多種拼寫變體 → 同一 ISO-3166-1 alpha-2。
_COUNTRY_TO_CC: dict[str, str] = {
    # Asia
    "japan": "jp", "日本": "jp", "nippon": "jp",
    "china": "cn", "中国": "cn", "中國": "cn", "people's republic of china": "cn", "prc": "cn",
    "taiwan": "tw", "台灣": "tw", "台湾": "tw", "republic of china": "tw", "roc": "tw",
    "south korea": "kr", "republic of korea": "kr", "korea": "kr", "대한민국": "kr", "한국": "kr",
    "north korea": "kp", "dprk": "kp",
    "hong kong": "hk", "香港": "hk",
    "macau": "mo", "macao": "mo", "澳門": "mo", "澳门": "mo",
    "vietnam": "vn", "viet nam": "vn", "việt nam": "vn",
    "thailand": "th", "ประเทศไทย": "th",
    "indonesia": "id",
    "malaysia": "my",
    "singapore": "sg", "新加坡": "sg",
    "philippines": "ph",
    "india": "in",
    "bhutan": "bt",
    "nepal": "np",
    "sri lanka": "lk",
    "pakistan": "pk",
    "bangladesh": "bd",
    "cambodia": "kh",
    "laos": "la",
    "myanmar": "mm", "burma": "mm",
    "mongolia": "mn", "монгол": "mn",
    "kazakhstan": "kz",
    "uzbekistan": "uz",
    # Middle East
    "iran": "ir",
    "iraq": "iq",
    "israel": "il",
    "lebanon": "lb",
    "jordan": "jo",
    "saudi arabia": "sa",
    "uae": "ae", "united arab emirates": "ae",
    "qatar": "qa",
    "kuwait": "kw",
    "oman": "om",
    "turkey": "tr", "türkiye": "tr",
    # Europe
    "united kingdom": "gb", "uk": "gb", "england": "gb", "britain": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb",
    "ireland": "ie",
    "france": "fr",
    "germany": "de", "deutschland": "de",
    "italy": "it", "italia": "it",
    "spain": "es", "españa": "es",
    "portugal": "pt",
    "netherlands": "nl", "the netherlands": "nl", "holland": "nl",
    "belgium": "be",
    "switzerland": "ch",
    "austria": "at",
    "poland": "pl",
    "czech republic": "cz", "czechia": "cz",
    "slovakia": "sk",
    "hungary": "hu",
    "romania": "ro",
    "bulgaria": "bg",
    "greece": "gr",
    "sweden": "se",
    "norway": "no",
    "denmark": "dk",
    "finland": "fi",
    "iceland": "is",
    "russia": "ru", "russian federation": "ru",
    "ukraine": "ua",
    "belarus": "by",
    "estonia": "ee",
    "latvia": "lv",
    "lithuania": "lt",
    "croatia": "hr",
    "serbia": "rs",
    "slovenia": "si",
    # Americas
    "united states": "us", "usa": "us", "u.s.": "us", "u.s.a.": "us", "america": "us",
    "united states of america": "us",
    "canada": "ca",
    "mexico": "mx", "méxico": "mx",
    "brazil": "br", "brasil": "br",
    "argentina": "ar",
    "chile": "cl",
    "colombia": "co",
    "peru": "pe", "perú": "pe",
    "venezuela": "ve",
    "uruguay": "uy",
    "paraguay": "py",
    "ecuador": "ec",
    "bolivia": "bo",
    # Oceania
    "australia": "au",
    "new zealand": "nz",
    # Africa
    "egypt": "eg",
    "south africa": "za",
    "morocco": "ma",
    "kenya": "ke",
    "ethiopia": "et",
    "tanzania": "tz",
    "nigeria": "ng",
    "ghana": "gh",
    "tunisia": "tn",
    "algeria": "dz",
}

# 國家 → 該地區常見維基語言碼(僅作為輔助;英文一定先試)
_COUNTRY_TO_WIKILANGS: dict[str, list[str]] = {
    "jp": ["ja"],
    "cn": ["zh"],
    "tw": ["zh"],
    "hk": ["zh"],
    "mo": ["zh"],
    "kr": ["ko"],
    "th": ["th"],
    "vn": ["vi"],
    "id": ["id"],
    "fr": ["fr"],
    "de": ["de"],
    "it": ["it"],
    "es": ["es"],
    "pt": ["pt"],
    "nl": ["nl"],
    "pl": ["pl"],
    "ru": ["ru"],
    "ua": ["uk", "ru"],
    "tr": ["tr"],
    "ar": ["es"],
    "br": ["pt"],
    "mx": ["es"],
}


def country_to_cc(country: str) -> Optional[str]:
    """寬鬆把人類國家名 → ISO-3166-1 alpha-2。失敗回 None。
    僅取逗號前段(處理 'Salvo, North Carolina, USA' 之類)。"""
    if not country:
        return None
    name = country.strip().lower()
    # 拆逗號取最後一段(通常是國家),也試完整字串
    parts = [p.strip() for p in name.split(",") if p.strip()]
    candidates = parts + ([name] if name not in parts else [])
    # 反向也試 — 如 "Salvo, NC, USA",最後一段 "usa" 才是國家
    for c in reversed(candidates):
        c2 = c.strip(".").strip()
        if c2 in _COUNTRY_TO_CC:
            return _COUNTRY_TO_CC[c2]
    return None


def wiki_langs_for(country: str, query: str = "") -> list[str]:
    """回傳優先嘗試的維基語言碼列表(英文永遠優先)。
    依國家 + 字串內含的腳本字符判斷。"""
    out = ["en"]
    cc = country_to_cc(country)
    if cc and cc in _COUNTRY_TO_WIKILANGS:
        for lang in _COUNTRY_TO_WIKILANGS[cc]:
            if lang not in out:
                out.append(lang)
    if query:
        # 偵測腳本字符,加對應 wiki
        if re.search(r"[ぁ-ヿ]", query) and "ja" not in out:
            out.append("ja")
        if re.search(r"[一-鿿]", query) and "zh" not in out and "ja" not in out:
            out.append("zh")
        if re.search(r"[가-힣]", query) and "ko" not in out:
            out.append("ko")
    return out


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """兩點之間球面距離(公尺)。"""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
