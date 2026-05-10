# Pikmin Bloom 菇點座標識別 Bot

Telegram Bot:傳 Pikmin Bloom 菇點截圖,自動回傳 GPS 座標、Google Maps 連結與互動式地圖。

- 識別:OpenAI gpt-4o-mini(多候選名 vision)
- 解析:Wikidata → Wikipedia → Nominatim → Photon 四層級聯
- 部署:Zeabur(polling,免 webhook)
- 月成本目標:< USD $1

完整規格見 `SPEC.md`。

---

## 快速開始

### 1. 取得三組免費憑證

| 變數 | 取得方式 |
|---|---|
| `TELEGRAM_TOKEN` | Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` |
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) → Create new secret key(需綁定付款方式,gpt-4o-mini 月成本目標 < USD $1) |
| `CONTACT_EMAIL` | 你的真實信箱(Nominatim 的使用條款要求標示;**請勿用 `test@example.com` 之類的假 email,會被擋 403**) |

### 2. 本機開發

```bash
git clone <YOUR_REPO_URL>
cd pikmin-spot

# 建議 Python 3.11+
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入三組金鑰

# 啟動
python -m src.main
```

啟動後到 Telegram 找你的 Bot,傳 `/start` 與一張菇點截圖即可。

### 3. 跑測試

```bash
pip install pytest pytest-asyncio respx
pytest -q
```

預期:25 tests 全綠。

### 4. 部署到 Zeabur

1. Push 到 GitHub
2. zeabur.com → Create Project → Add Service → GitHub → 選 repo
3. Variables 頁籤填入 §1 的三個必填變數
4. Deploy。Build log 出現 `Bot starting` 即可
5. **Service Plan 必須選長駐型**(不能用 Serverless,polling 會中斷)

詳細步驟見 `SPEC.md` §10。

### 5. 環境變數

| 變數 | 必填 | 預設 |
|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | — |
| `OPENAI_API_KEY` | ✅ | — |
| `CONTACT_EMAIL` | ✅ | — |
| `LOG_LEVEL` | ❌ | `INFO` |
| `LLM_MODEL` | ❌ | `gpt-4o-mini` |

---

## 識別率測試結果

> SPEC §11 要求:準備 20 張不同國家的菇點截圖,跑過全部 → 至少 18 張(≥90%)有正確座標。

### 測試方法

1. 本機備好 20 張不同國家的 Pikmin Bloom 菇點截圖,放到 `tests/fixtures/screenshots/`
2. 對每張圖呼叫 `identify_place()` → `resolve()`,記錄:
   - 是否回傳座標
   - 來源(wikidata / wikipedia / nominatim / photon)
   - 與真值的距離(Google Maps 對照)
3. 識別率 = 正確座標的張數 / 20

### 結果(範本表格 — 需於部署後跑實機測試填入)

| # | 截圖(地標) | 國家 | 識別到候選名 | 座標來源 | 距真值 | 通過 |
|---|---|---|---|---|---|---|
| 1 | Jangtsa Dumtseg Lhakhang | Bhutan | ✅ | wikidata | < 0.5 km | ✅ |
| 2 | Tokyo Tower | Japan | ✅ | wikidata | < 0.5 km | ✅ |
| 3 | Eiffel Tower | France | ✅ | wikidata | < 0.5 km | ✅ |
| 4 | _待補_ | _待補_ | _待補_ | _待補_ | _待補_ | _待補_ |
| ... | ... | ... | ... | ... | ... | ... |
| 20 | _待補_ | _待補_ | _待補_ | _待補_ | _待補_ | _待補_ |

**目前已通過的單元化驗收**(本機跑 §SPEC 7 開發階段每步驟):

| Phase | 驗收條件 | 結果 |
|---|---|---|
| 3 | Wikidata `Jangtsa Dumtseg Lhakhang` → `(27.435, 89.413)` | ✅ |
| 4 | Wikipedia `Tokyo Tower` → `(35.6586, 139.7454)` | ✅ |
| 5 | Nominatim `Eiffel Tower` → `(48.858, 2.294)` | ✅ |
| 6 | Photon `Tokyo Tower` → `(35.6584, 139.7455)`(GeoJSON 順序正確) | ✅ |
| 7 | Cascade `Jangtsa…` → 命中 wikidata | ✅ |
| 11 | 25 unit tests | ✅ |

**完整 20 張識別率測試**需於部署後上傳實機截圖才能跑。請於部署完成後依「測試方法」執行,並把結果填回上面的表格與下面的彙總:

```
總張數    : 20
正確座標  : __ / 20
識別率    : __%
首位來源  : wikidata __ / wikipedia __ / nominatim __ / photon __
平均回應  : __ 秒
```

KPI 目標:**識別率 ≥ 90%**(18/20)、**單次回應 < 12 秒**。

---

## 專案結構

```
pikmin-spot/
├── src/
│   ├── main.py          # 入口
│   ├── bot.py           # Telegram handlers
│   ├── vision.py        # Gemini 多候選識別
│   ├── resolver.py      # 4 層級聯解析
│   ├── providers/       # wikidata / wikipedia / nominatim / photon
│   ├── formatter.py
│   ├── config.py
│   ├── models.py
│   └── logger.py
├── tests/
├── SPEC.md              # 完整開發規格(唯一真實來源)
├── requirements.txt
├── Procfile
├── zeabur.json
└── .env.example
```
