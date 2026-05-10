# Pikmin Bloom 菇點座標識別 Bot — 開發規格書 v2

> **給 Claude Code 的說明**:這份是完整開發規格,**識別率為首要目標**。請依「§7 開發階段」順序實作,每個 Phase 跑完驗收條件再進下一步。所有檔名、函式簽章、env var 名稱都是唯一真實來源,不要擅自修改。

---

## 1. 專案目標與 KPI

開發一個 Telegram Bot,使用者傳 Pikmin Bloom 菇點截圖後回傳 GPS 座標。

**首要 KPI:識別成功率 ≥ 90%**(對於可被 Wikipedia 收錄的地標)

次要目標:
- 月成本 < USD $1
- 單次回應 < 12 秒
- 三個必填 env var,皆免費取得

---

## 2. 識別率優化策略(本版核心)

過去的弱點與本版對策:

| 弱點 | 解法 |
|---|---|
| LLM OCR 誤讀(如把 `Jangtsa` 讀成 `Jangtso`) | LLM 一次回**多個候選名**,逐一嘗試 |
| 單一 Geocoder 對冷門地標漏接 | **4 層級聯**:Wikidata → Wikipedia → Nominatim → Photon |
| Geocoder 對名稱拼寫敏感 | 同時用候選名 × 原文(中/日/藏文)交叉查詢 |
| LLM 不熟 Pikmin Bloom UI | Prompt 內明確說明 UI 版位 + 兩個 few-shot 範例 |
| 知名地標查到錯誤同名地點 | 優先 Wikidata(語意網,絕不混淆) |

**為什麼 Wikidata 是 Game Changer**:
- Wikidata 對每個地標儲存 **P625 座標屬性**,精確且權威
- 支援多語言搜尋,藏文/日文/中文名也能搜
- 完全免費、無 key、無流量限制
- 對於 Pikmin Bloom 主打的觀光地標,覆蓋率極高(估 >85%)

---

## 3. 功能需求

| ID | 描述 | 優先度 |
|---|---|---|
| F1 | 接收 Telegram 圖片 | P0 |
| F2 | LLM Vision 多候選地標識別 | P0 |
| F3 | Wikidata/Wikipedia/Nominatim/Photon 級聯解析 | P0 |
| F4 | 回傳座標純文字 + Google Maps URL | P0 |
| F5 | Telegram 原生 `sendLocation`(互動式地圖) | P0 |
| F6 | 完整錯誤處理(LLM 失敗、解析失敗、未知圖片) | P1 |
| F7 | `/start`、`/help` 指令 | P1 |
| F8 | 結構化日誌記錄識別過程 | P2 |

---

## 4. 技術選型

### 4.1 LLM:Gemini 2.5 Flash

| 模型 | 輸入價(per 1M token) | 圖片價 | 為何選它 |
|---|---|---|---|
| **Gemini 2.5 Flash** ✅ | ~$0.075 | ~$0.0003/圖 | 最便宜 + Vision 能力夠 |
| Gemini 2.0 Flash | ~$0.10 | 略高 | 備援 |
| Claude Haiku 4.5 | ~$1.00 | 高 10× | 太貴 |

### 4.2 全部使用的 API(全部免費,只 2 個需 key)

| API | 用途 | 是否需 key | 速率限制 |
|---|---|---|---|
| **Telegram Bot API** | 收發訊息 | ✅ 從 @BotFather 免費取得 | 寬鬆 |
| **Gemini API** | Vision 識別 | ✅ 從 AI Studio 免費取得 | 免費層 1500 RPD |
| **Wikidata API** | 主要 geocoder | ❌ 無 | 寬鬆 |
| **Wikipedia API** | 第二 geocoder | ❌ 無 | 寬鬆 |
| **Nominatim** | 第三 geocoder(OSM) | ❌ 無(需 User-Agent) | 1 req/sec |
| **Photon** | 第四 geocoder(OSM) | ❌ 無 | 寬鬆 |

### 4.3 Python 套件

```
python-telegram-bot>=21.6
google-generativeai>=0.8.0
httpx>=0.27.0
python-dotenv>=1.0.1
pydantic>=2.0
pydantic-settings>=2.0
```

---

## 5. 系統架構

```
┌──────────┐  photo  ┌───────────┐  base64  ┌──────────────┐
│ Telegram │ ──────► │ Bot       │ ───────► │ Gemini Flash │
│ User     │         │ (Zeabur)  │          │ (multi-cand) │
└──────────┘         └─────┬─────┘          └──────┬───────┘
     ▲                     │  candidates[]         │
     │ msg + map           ▼                       │
     │           ┌─────────────────────┐           │
     │           │ Resolver (Cascade)  │           │
     │           │                     │           │
     │           │ ① Wikidata API ─────┼──► coords?
     │           │     ↓ (miss)        │           │
     │           │ ② Wikipedia API ────┼──► coords?
     │           │     ↓ (miss)        │           │
     │           │ ③ Nominatim ────────┼──► coords?
     │           │     ↓ (miss)        │           │
     │           │ ④ Photon ───────────┼──► coords?
     │           └─────────────────────┘           │
     │                     │                       │
     └─────────────────────┘                       │
        formatted reply                            │
```

**處理流程**:

1. 收圖 → 立刻 reply「🔍 識別中…」
2. Gemini 識別 → 拿到 N 個候選名 + 國家/地區
3. **解析器級聯**:
   - 對每個候選名,依序試 4 個來源
   - 任一成功就回傳座標,**短路後續查詢**
   - 4 層全失敗才回「找不到座標」
4. 編輯訊息為:座標 + Google Maps URL
5. 額外發送 `sendLocation` 原生地圖

---

## 6. 專案結構

```
pikmin-coord-bot/
├── src/
│   ├── __init__.py
│   ├── main.py              # 入口
│   ├── bot.py               # Telegram handlers
│   ├── vision.py            # Gemini 多候選識別
│   ├── resolver.py          # 級聯解析(取代原 geocoding.py)
│   ├── providers/           # 4 個解析來源
│   │   ├── __init__.py
│   │   ├── base.py          # GeocoderProvider 抽象介面
│   │   ├── wikidata.py
│   │   ├── wikipedia.py
│   │   ├── nominatim.py
│   │   └── photon.py
│   ├── formatter.py         # 訊息格式化
│   ├── config.py            # env vars
│   ├── models.py            # PlaceCandidates、Coords 等 dataclass
│   └── logger.py
├── tests/
│   ├── __init__.py
│   ├── test_vision.py
│   ├── test_resolver.py
│   ├── test_providers/
│   │   ├── test_wikidata.py
│   │   ├── test_wikipedia.py
│   │   ├── test_nominatim.py
│   │   └── test_photon.py
│   └── fixtures/
│       └── jangtsa.jpg
├── requirements.txt
├── Procfile
├── zeabur.json
├── .env.example
├── .gitignore
└── README.md
```

---

## 7. 開發階段

### Phase 1:基礎建設

- [ ] 建立目錄結構
- [ ] `requirements.txt`(版本依 §4.3)
- [ ] `.gitignore`(`.env`、`__pycache__/`、`*.pyc`、`.venv/`、`*.log`)
- [ ] `.env.example`(依 §9)
- [ ] `src/config.py`:用 `pydantic-settings` 讀 env,啟動時驗證 3 個必填
- [ ] `src/logger.py`:結構化日誌,等級依 `LOG_LEVEL`
- [ ] `src/models.py`:見下方 dataclass

**`src/models.py` 內容**:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PlaceCandidates:
    """Vision 識別結果"""
    candidates: list[str]                    # 1~3 個英文候選名
    place_name_local: Optional[str] = None   # 原文(藏/日/中)
    country: str = ""
    region: str = ""
    description: str = ""
    search_hints: list[str] = field(default_factory=list)
    confidence: str = "low"                  # high|medium|low

@dataclass
class Coords:
    lat: float
    lng: float
    source: str                              # "wikidata"|"wikipedia"|"nominatim"|"photon"
    matched_query: str                       # 實際命中的查詢字串
    canonical_name: Optional[str] = None     # 來源回傳的標準名
```

**驗收**:`python -c "from src.config import settings; from src.models import *"` 無錯誤。

---

### Phase 2:Vision 模組

**檔案**:`src/vision.py`

**函式簽章**:

```python
async def identify_place(image_bytes: bytes) -> PlaceCandidates:
    """
    回傳候選名陣列。完全無法識別時回 candidates=[]。
    LLM 呼叫失敗或 JSON 解析失敗拋 VisionError。
    """

class VisionError(Exception): ...
```

**Prompt**(寫在模組常數):

```
You are an expert at identifying real-world landmarks from Pikmin Bloom mushroom point screenshots.

ABOUT THE GAME UI:
Pikmin Bloom mushroom screenshots have this layout:
- TOP: Photo of the real-world landmark
- MIDDLE: Landmark name shown as a TITLE (often in multiple scripts like Latin/Tibetan/Japanese/Chinese)
- BELOW TITLE: A short English description ("The only temple in Bhutan...")
- "距離" or "Distance": followed by meters — THIS IS NOT PART OF THE NAME, IGNORE IT
- BOTTOM: 3D mushroom decorations — IGNORE THESE

Your job: identify the landmark from the TITLE and photo. Generate MULTIPLE candidate names because:
- OCR may produce minor errors
- Wikipedia titles often differ from displayed names
- Geocoders may need different spellings

OUTPUT (valid JSON only, no markdown, no code fence):
{
  "candidates": [
    "Primary English/official name (most likely Wikipedia title)",
    "Alternative spelling or common name",
    "Transliteration variant if applicable"
  ],
  "place_name_local": "Name in original script if visible, else null",
  "country": "Country name in English",
  "region": "City or province in English",
  "description": "One sentence factual description of what the landmark is",
  "search_hints": ["extra keyword 1", "extra keyword 2"],
  "confidence": "high" | "medium" | "low"
}

EXAMPLES:

Input: Screenshot showing "Jangtsa Dumtseg Lhakhang" with Bhutanese stupa-temple
Output:
{
  "candidates": ["Jangtsa Dumtseg Lhakhang", "Dumtseg Lhakhang", "Dungtse Lhakhang"],
  "place_name_local": "ཛྩུ་མ་བར་",
  "country": "Bhutan",
  "region": "Paro",
  "description": "The only temple in Bhutan in the form of a stupa",
  "search_hints": ["Paro chorten", "Thangtong Gyalpo temple"],
  "confidence": "high"
}

Input: Screenshot showing "東京タワー | Tokyo Tower"
Output:
{
  "candidates": ["Tokyo Tower", "東京タワー"],
  "place_name_local": "東京タワー",
  "country": "Japan",
  "region": "Tokyo",
  "description": "Communications and observation tower in Minato, Tokyo",
  "search_hints": ["Minato tower Japan"],
  "confidence": "high"
}

If you cannot identify any landmark at all:
{"candidates": [], "error": "explanation"}

CRITICAL:
- Generate 1-3 candidates, prefer English Wikipedia title format
- Distance text "距離: 3,207,181m" is NEVER the name
- Always include local-script name if visible
- Be confident on famous landmarks; mark "low" only when truly uncertain
```

**實作要點**:
- `genai.GenerativeModel("gemini-2.5-flash", generation_config={"response_mime_type": "application/json", "temperature": 0.1})`
- 用 `generate_content_async`
- JSON parse 用 `try/except`,失敗拋 `VisionError`
- 候選清單去重(case-insensitive)

**驗收**:對 `fixtures/jangtsa.jpg` 識別,`candidates[0]` 含「Jangtsa」與「Dumtseg」字串。

---

### Phase 3:Provider 抽象與 Wikidata

**檔案**:`src/providers/base.py`

```python
from abc import ABC, abstractmethod
from typing import Optional
from src.models import Coords

class GeocoderProvider(ABC):
    name: str                                # "wikidata" 等

    @abstractmethod
    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        """單次查詢。找不到回 None,網路錯誤拋 ProviderError。"""

class ProviderError(Exception): ...
```

**檔案**:`src/providers/wikidata.py`

**邏輯**:
1. **Step 1 — Search**:
   ```
   GET https://www.wikidata.org/w/api.php
       ?action=wbsearchentities
       &search={query}
       &language=en
       &format=json
       &type=item
       &limit=5
   ```
   取 `search[]` 陣列。
2. **Step 2 — Filter**:篩選 `description` 含地理關鍵字(temple, tower, mountain, lake, museum, station, palace, monument, park, building, church, mosque, shrine, castle, bridge...)的條目。可選:用 `hint_country` 過濾 description 包含國家名的條目。
3. **Step 3 — Get entity**:對首筆結果發:
   ```
   GET https://www.wikidata.org/wiki/Special:EntityData/{Q-id}.json
   ```
   解析 `entities.{Q-id}.claims.P625[0].mainsnak.datavalue.value.{latitude, longitude}`。
4. 回傳 `Coords(lat, lng, source="wikidata", matched_query=query, canonical_name=label)`。

**注意**:
- 沒 P625(座標屬性)的 entity 視為 miss
- HTTP timeout 設 8 秒
- User-Agent: `PikminCoordBot/1.0 ({CONTACT_EMAIL})`

**驗收**:`await wikidata.lookup("Jangtsa Dumtseg Lhakhang")` 回傳座標約 `(27.435, 89.413)`。

---

### Phase 4:Wikipedia Provider

**檔案**:`src/providers/wikipedia.py`

**邏輯**:
1. **Search**:
   ```
   GET https://en.wikipedia.org/w/api.php
       ?action=opensearch
       &search={query}
       &limit=3
       &format=json
   ```
   取首筆頁面標題。
2. **Get coords**:
   ```
   GET https://en.wikipedia.org/w/api.php
       ?action=query
       &prop=coordinates
       &titles={page_title}
       &format=json
   ```
   解析 `query.pages.*.coordinates[0].{lat, lon}`。
3. 沒 coordinates 視為 miss。

**驗收**:對 "Tokyo Tower" 回傳座標約 `(35.6586, 139.7454)`。

---

### Phase 5:Nominatim Provider

**檔案**:`src/providers/nominatim.py`

```
GET https://nominatim.openstreetmap.org/search
    ?q={query}
    &format=json
    &limit=1
    &addressdetails=0
```

**注意**:
- **必設** User-Agent:`PikminCoordBot/1.0 ({CONTACT_EMAIL})`
- 速率限制 1 req/sec → 用 module-level `asyncio.Lock` + `await asyncio.sleep(1)` 在每次呼叫後
- 解析 `[0].{lat, lon}`,值是字串要轉 float

---

### Phase 6:Photon Provider

**檔案**:`src/providers/photon.py`

```
GET https://photon.komoot.io/api
    ?q={query}
    &limit=1
    &lang=en
```

回傳 GeoJSON,解析 `features[0].geometry.coordinates`(注意是 `[lng, lat]` 不是 `[lat, lng]`)。

---

### Phase 7:級聯解析器

**檔案**:`src/resolver.py`

```python
async def resolve(place: PlaceCandidates) -> Optional[Coords]:
    """
    對每個 candidate × 每個 provider 級聯查詢。
    任一命中立即回傳。
    全失敗回 None。
    """
```

**查詢順序**(行優先,即同一 query 先試 4 個 provider 再換下一 query):

```
queries = build_queries(place)   # 生 N 條查詢字串
providers = [Wikidata, Wikipedia, Nominatim, Photon]

for q in queries:
    for p in providers:
        try:
            result = await p.lookup(q, place.country)
            if result:
                logger.info("hit", query=q, provider=p.name)
                return result
        except ProviderError as e:
            logger.warning("provider error", provider=p.name, error=str(e))
            continue
return None
```

**`build_queries(place)` 生成順序**(去重):

```
1. f"{candidates[0]}, {region}, {country}"
2. f"{candidates[0]}, {country}"
3. f"{candidates[1]}, {country}"  # 若有
4. f"{candidates[2]}, {country}"  # 若有
5. f"{place_name_local}, {country}"  # 若有原文
6. f"{candidates[0]}"  # 純名字
7. f"{search_hints[0]}, {country}"  # 若有
```

**驗收**:對 `PlaceCandidates(candidates=["Jangtsa Dumtseg Lhakhang"], country="Bhutan", region="Paro")` 必須回傳座標(來源預期是 wikidata)。

---

### Phase 8:Formatter

**檔案**:`src/formatter.py`

```python
def format_success(place: PlaceCandidates, coords: Coords) -> str: ...
def format_no_coords(place: PlaceCandidates) -> str: ...
def format_unknown() -> str: ...
def google_maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lng}"
```

**成功訊息範本(Markdown)**:

```
📍 *Jangtsa Dumtseg Lhakhang*
🌏 Bhutan · Paro

🎯 座標:`27.435125, 89.413636`
🗺️ [Google Maps](https://www.google.com/maps?q=27.435125,89.413636)

📝 The only temple in Bhutan in the form of a stupa
_資料來源:wikidata · 信心度:high_
```

**注意**:用 `parse_mode="Markdown"`(不是 V2),避開跳脫地獄。`disable_web_page_preview=True` 防止連結預覽撐高訊息。

---

### Phase 9:Telegram Bot

**檔案**:`src/bot.py`

```python
async def cmd_start(update, context): ...
async def handle_photo(update, context): ...
async def handle_non_photo(update, context): ...
```

**`handle_photo` 流程**:

```python
async def handle_photo(update, context):
    chat_id = update.effective_chat.id
    status = await update.message.reply_text("🔍 識別中…")
    
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        
        place = await identify_place(bio.getvalue())
        if not place.candidates:
            await status.edit_text(format_unknown())
            return
        
        await status.edit_text(f"🔎 識別到「{place.candidates[0]}」,查詢座標中…")
        
        coords = await resolve(place)
        if not coords:
            await status.edit_text(format_no_coords(place), parse_mode="Markdown")
            return
        
        await status.edit_text(
            format_success(place, coords),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await context.bot.send_location(
            chat_id=chat_id, latitude=coords.lat, longitude=coords.lng,
        )
    except Exception:
        log.exception("handle_photo failed", user_id=update.effective_user.id)
        await status.edit_text("⚠️ 處理失敗,請稍後重試")
```

---

### Phase 10:入口

**檔案**:`src/main.py`

```python
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from src.config import settings
from src.bot import cmd_start, handle_photo, handle_non_photo
from src.logger import get_logger

log = get_logger(__name__)

def main():
    log.info("Bot starting", model=settings.LLM_MODEL)
    app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_non_photo))
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
```

---

### Phase 11:測試

每個 provider 寫一個測試,至少:
- 知名地標回傳合理座標(誤差 < 1 km)
- 不存在地名回 `None`
- mock httpx 測試異常處理

`tests/test_resolver.py` 測級聯邏輯:
- 第一個 provider 命中 → 後續不被呼叫
- 全部 miss → 回 `None`
- 中間有 provider 拋 error → 繼續下一個

---

### Phase 12:Zeabur 部署

**`Procfile`**:
```
worker: python -m src.main
```

**`zeabur.json`**(可選):
```json
{
  "name": "pikmin-coord-bot",
  "build": { "buildCommand": "pip install -r requirements.txt" },
  "start": { "startCommand": "python -m src.main" }
}
```

詳細部署流程見 §10。

---

## 8. 詳細 API 範例

### 8.1 Wikidata Search

```bash
curl 'https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Jangtsa+Dumtseg+Lhakhang&language=en&format=json&type=item&limit=5'
```

預期回傳含 `Q3162338`(Dumtseg Lhakhang)。

### 8.2 Wikidata Entity

```bash
curl 'https://www.wikidata.org/wiki/Special:EntityData/Q3162338.json' | jq '.entities.Q3162338.claims.P625[0].mainsnak.datavalue.value'
```

預期:`{"latitude": 27.4351..., "longitude": 89.4136..., ...}`

### 8.3 Photon

```bash
curl 'https://photon.komoot.io/api?q=Tokyo+Tower&limit=1'
```

注意 `coordinates: [lng, lat]` 順序。

---

## 9. 環境變數(Zeabur 設定)

**只有 3 個必填,全部免費取得**:

| 變數 | 必填 | 範例 | 取得方式 |
|---|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | `7891234567:AAH...` | Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` |
| `GEMINI_API_KEY` | ✅ | `AIzaSyB...` | [Google AI Studio](https://aistudio.google.com/app/apikey) → Create API Key |
| `CONTACT_EMAIL` | ✅ | `you@example.com` | 你的信箱(Nominatim 要求標示) |
| `LOG_LEVEL` | ❌ | `INFO` | 預設 `INFO` |
| `LLM_MODEL` | ❌ | `gemini-2.5-flash` | 預設 `gemini-2.5-flash`,可改 `gemini-2.0-flash` |

**`.env.example`**:

```bash
# === 必填(全免費) ===
TELEGRAM_TOKEN=your_telegram_bot_token_from_botfather
GEMINI_API_KEY=your_gemini_api_key_from_ai_studio
CONTACT_EMAIL=your_email@example.com

# === 選用 ===
LOG_LEVEL=INFO
LLM_MODEL=gemini-2.5-flash
```

---

## 10. Zeabur 部署步驟

1. **GitHub 上傳**
   ```bash
   git init && git add . && git commit -m "feat: initial bot"
   git remote add origin https://github.com/YOUR_USER/pikmin-coord-bot.git
   git push -u origin main
   ```

2. **登入 [zeabur.com](https://zeabur.com)** → Create Project

3. **Add Service** → GitHub → 選 repo

4. Zeabur 自動偵測 Python,讀 `Procfile` 啟動

5. **Variables 頁籤**逐一加入 §9 的 3 個必填變數

6. **Deploy**,等 build log 出現 `Bot starting`

7. **驗證**:
   - Telegram 找你的 Bot 傳 `/start` → 收到歡迎訊息
   - 傳菇點截圖 → 10 秒內收到座標訊息 + 原生地圖

**重要**:
- 不需要 webhook(用 polling)
- 不需要對外 port
- Service Plan 必須是長駐型,**不能用 Serverless**(否則 polling 會中斷)

---

## 11. 測試案例(手動驗收)

| 案例 | 輸入 | 預期 | 預期來源 |
|---|---|---|---|
| TC1 | `/start` | 歡迎訊息 | — |
| TC2 | Jangtsa Dumtseg Lhakhang 截圖 | `(27.4351, 89.4136)` ±0.01 | wikidata |
| TC3 | 東京鐵塔截圖 | `(35.6586, 139.7454)` ±0.01 | wikidata 或 wikipedia |
| TC4 | 比較冷門但 OSM 有的地點 | 任何合理座標 | nominatim 或 photon |
| TC5 | 純文字訊息 | 「請傳送圖片」 | — |
| TC6 | 純風景照無地標 | 「無法識別」 | — |
| TC7 | 識別到但 4 層全 miss(極罕見) | 顯示地名 + 自行搜尋提示 | — |

**識別率驗證**:準備 20 張不同國家的菇點截圖,跑過全部 → 至少 18 張(≥90%)有正確座標。

---

## 12. 後續擴充(不在本次範圍)

- SQLite 快取(image hash → 結果)
- 群組模式 + 共用菇點資料庫
- Inline mode `@yourbot` 直接搜尋
- 使用者「👍/👎」回饋按鈕,收集誤判樣本
- 支援多張圖一次傳(album)
- 把識別結果輸出 GPX/KML 路線檔

---

## 13. 給 Claude Code 的最後叮嚀

1. **嚴格按 Phase 順序**,每階段跑驗收條件再往下
2. **不要改函式簽章或環境變數名稱**,本文件是唯一真實來源
3. **每個 async I/O 必須有 timeout**(預設 8 秒,Gemini 30 秒)
4. **不要把 token / API key 印到 log**
5. **provider 任一掛掉不應讓整體流程崩**,務必 try/except 後 fallback
6. **commit 訊息用 Conventional Commits**:`feat:` / `fix:` / `docs:` / `chore:`
7. 完成後在 README.md 寫「快速開始」與「識別率測試結果」兩節
