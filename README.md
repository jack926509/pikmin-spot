# Pikmin Bloom 菇點座標識別 Bot(Slack)

Slack Bot:在頻道或 DM 傳 Pikmin Bloom 菇點截圖,自動回傳 GPS 座標與 Google Maps 連結。

- 識別:OpenAI gpt-4o-mini(多候選名 vision)
- 解析:Wikidata → Wikipedia → Nominatim → Photon 四層級聯
- 連線:Slack Socket Mode(免 webhook、免公網 URL)
- 部署:Zeabur / 任何長駐 worker(月成本目標 < USD $1)

完整規格見 `SPEC.md`(Telegram 版規格,核心管線一致;接入層差異見本文件)。

---

## 快速開始

### 1. 建立 Slack App

到 <https://api.slack.com/apps> → **Create New App** → **From scratch**。

#### 1.1 啟用 Socket Mode

**Settings → Socket Mode** → 開啟 → 產生 *App-Level Token*(scope `connections:write`),拿到 `xapp-...` → 對應 `SLACK_APP_TOKEN`。

#### 1.2 OAuth Scopes(Bot Token Scopes)

**Features → OAuth & Permissions → Scopes → Bot Token Scopes**:

| Scope | 用途 |
|---|---|
| `app_mentions:read` | 收 `@pikmin-bot` 提及 |
| `channels:history` | 讀公開頻道訊息(包含附檔) |
| `groups:history` | 讀私人頻道訊息 |
| `im:history` | 讀 DM 訊息 |
| `chat:write` | 回覆訊息 |
| `files:read` | 下載使用者上傳的截圖 |
| `commands` | `/pikmin-help` 等 slash commands |

#### 1.3 Event Subscriptions

**Features → Event Subscriptions** → On。Bot Events 加:

- `app_mention`
- `message.channels`
- `message.groups`
- `message.im`
- `file_shared`

#### 1.4 Slash Commands(選用,建議加)

**Features → Slash Commands** → Create New Command,加兩個:

| Command | Short Description |
|---|---|
| `/pikmin-start` | 歡迎訊息 |
| `/pikmin-help` | 使用說明 |

#### 1.5 安裝到工作區

**Settings → Install App** → Install to Workspace → 同意。拿到 *Bot User OAuth Token*(`xoxb-...`)→ 對應 `SLACK_BOT_TOKEN`。

### 2. 取得四組憑證

| 變數 | 取得方式 |
|---|---|
| `SLACK_BOT_TOKEN` | 上面 §1.5,`xoxb-...` |
| `SLACK_APP_TOKEN` | 上面 §1.1,`xapp-...` |
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) → Create new secret key |
| `CONTACT_EMAIL` | 你的真實信箱(Nominatim 使用條款要求,**請勿用假 email,會被擋 403**) |

### 3. 本機開發

```bash
git clone https://github.com/jack926509/pikmin-spot.git
cd pikmin-spot

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 編輯 .env 填入四組金鑰

python -m src.main
```

啟動後到 Slack 頻道(或 DM bot)上傳一張菇點截圖即可。

### 4. 跑測試

```bash
pip install pytest pytest-asyncio respx
pytest -q
```

預期:54 tests 全綠。

### 5. 部署到 Zeabur

1. ✅ Push 到 GitHub
2. zeabur.com → Create Project → Add Service → GitHub → 選此 repo
3. Variables 頁籤填入 §2 的四個必填變數
4. Deploy。Log 出現 `Bot starting` 即可
5. **Service Plan 必須選長駐型**(Socket Mode 用 WebSocket,Serverless 會中斷)

### 6. 環境變數

| 變數 | 必填 | 預設 |
|---|---|---|
| `SLACK_BOT_TOKEN` | ✅ | — |
| `SLACK_APP_TOKEN` | ✅ | — |
| `OPENAI_API_KEY` | ✅ | — |
| `CONTACT_EMAIL` | ✅ | — |
| `LOG_LEVEL` | ❌ | `INFO` |
| `LLM_MODEL` | ❌ | `gpt-4o-mini` |

---

## 使用方式

- **頻道**:把 bot 加入頻道,直接上傳菇點截圖即可。Bot 會以 thread 回覆。
- **DM**:私訊 bot,上傳截圖。
- **`/pikmin-help`**:看完整說明。
- **`@pikmin-bot`**:任何頻道提及 → 回覆說明。

回應內容:

- 📍 地標名稱(含本地語腳本,如有)
- 🌏 國家 · 城市
- 🎯 GPS 座標(精度 6 位小數)
- 📝 一句話描述
- 按鈕:🗺 在 Google Maps 開啟

---

## 從 Telegram 版本遷移的優化

本次 Slack 移植同時做了三處強化:

1. **In-flight 去重**:Slack 同一檔案會同時觸發 `message` 與 `file_shared` 兩個事件,以 `file_id` 做集合去重避免重覆呼叫 OpenAI。
2. **圖片大小防護**:超過 20MB 的檔案直接擋下,避免 OOM 與浪費 token。
3. **下載重試**:Slack file API 有偶發 5xx/429,以指數退避重試 3 次。

核心管線(vision / resolver / providers / cache / models / logger)完全與框架無關,本次未動。

---

## 專案結構

```
pikmin-spot/
├── src/
│   ├── main.py          # 入口(Bolt AsyncSocketModeHandler)
│   ├── bot.py           # Slack handlers
│   ├── slack_blocks.py  # Block Kit builders
│   ├── formatter.py     # 框架無關的訊息文字
│   ├── vision.py        # OpenAI gpt-4o-mini 多候選識別
│   ├── resolver.py      # 4 層級聯解析
│   ├── providers/       # wikidata / wikipedia / nominatim / photon
│   ├── cache.py         # LRU 結果快取 + 進行中檔案去重集
│   ├── config.py
│   ├── models.py
│   └── logger.py
├── tests/
├── SPEC.md
├── requirements.txt
├── Procfile
├── zeabur.json
└── .env.example
```

---

## 識別率驗收

> SPEC §11 要求:準備 20 張不同國家的菇點截圖 → 至少 18 張(≥90%)有正確座標。

由於核心識別管線未動,Telegram 版的識別率驗收結果直接適用。請於 Slack 部署後再跑一次回歸測試。

KPI:**識別率 ≥ 90%**(18/20)、**單次回應 < 12 秒**。
