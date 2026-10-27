# TW SelfSelect Trader — 台股「自選股」量化自動交易系統

> 每月自動選股、自動換股、自動下單的台股交易機器人。
> 由 [tw-autotrader](https://github.com/dinchentech/tw-autotrader) 拆出，**只有一條資金腿：每月換股的自選股**。

📖 **[使用手冊](使用手冊.md)** — 安裝、參數、每月作業、真錢上線檢查清單
📊 **[線上儀表板](https://dinchentech.github.io/tw-selfselect/)** — 由 VM 在每個交易日收盤後自動更新（13:45 產生 `logs/dashboard.html`、13:50 推上 GitHub Pages）；要不要公開由 `.env` 的 `DASHBOARD_PUBLISH` 決定，預設 `0`＝不公開（見[使用手冊 §5-3](使用手冊.md#5-3-儀表板公開頁可選預設關閉)）　·　📊 **[策略說明](策略說明.md)** — 策略原理、選股口徑、風控、參數總表

---

## ⚠️ 先讀這段（免責聲明）

本軟體係依「現狀（AS-IS）」提供，不帶有任何形式的明示或暗示之保證（包括但不限於對適銷性、特定目的之適用性以及不侵權的暗示保證）。
開發團隊在任何情況下，均不對因使用或無法使用本軟體所引起的任何直接、間接、偶發、特殊、懲罰性或衍生性損失（包括但不限於利潤損失、業務中斷、資料遺失、設備損壞或電腦故障）承擔任何法律及賠償責任。
**使用者須自行承擔使用本軟體之所有風險；本專案不構成任何投資建議。** 回測績效不代表未來實績。

預設設定為 **`ESUN_ENVIRONMENT=simulation`（模擬帳戶）**。切到 `real` 之前，請完整跑過
[使用手冊 §真錢上線檢查清單](使用手冊.md#真錢上線檢查清單) 的每一項。

---

## 這是什麼？

| 項目 | 說明 |
|---|---|
| 選股 | 每月第 1 個交易日（D1）盤後自動選股：誠實候選池（歷史市值前 N 大，無倖存者偏差）→ 動能／技術面／穩定性評分 → 法人確認 → 過熱剔除 → 取前 N 檔 |
| 執行 | 每月第 2 個交易日（D2）13:25–13:30 自動買進新名單；持股依策略訊號進出，進場當下鎖定型態對應的策略 |
| 風控 | 大盤年線過濾、帳戶回撤保護（MIN_DRAW_BACK）、買入當下過熱閘門、每日交易次數／虧損上限、滿倉不重複買 |
| 券商 | 玉山證券（E.Sun SDK：行情＋交易）；另有凱基（mock／實單）介面 |
| 通知 | Telegram（下單、選股、持倉報告、異常告警），可選 LINE Notify |
| 儀表板 | `scripts/generate_dashboard.py` 產生 `logs/dashboard.html`；VM 每交易日 13:45 產生、13:50 自動推上 GitHub Pages（`DASHBOARD_PUBLISH=1` 才啟用） |
| 部署 | Docker（`docker compose up -d --build`）；雲端建議 GCP e2-micro 之類的便宜 VM |

## 架構

```
selfselect_trader.py     主程式：主迴圈 / 訊號判定 / 下單 / 記帳 / 通知
core/
  selfselect_scheduler.py  每月自動選股排程（D1 選股、D2 補跑）
  config_loader.py         PC_<代號> 設定解析（.env 是唯一真相）
  risk_manager.py          風控（每日次數/虧損、漲跌停檢查）
  drawdown_guard.py        MIN_DRAW_BACK 回撤保護 + 總資產口徑
  books.py                 三本帳（performance.csv／holdings／分帳本）稽核
  live_utils.py            下單成交確認、時段窗、報告節流等共用工具
  live_broker.py           券商工廠（esun / kgi）
  trading_calendar.py      台灣交易日曆（含國定假日、補班日）
  candidate_pool.py        誠實候選池（歷史股本 × 當期價格）
  inst_data.py             TWSE 法人／FinMind 股價資料層（含版本化快取）
  cache_io.py              快取讀寫（schema 版本化）
data/
  esun_provider.py         玉山 SDK 封裝（行情 + 下單）
  yahoo_loader.py          yfinance 日線
strategies/                策略函式（auto 型態分派 / ma_cross / bollinger / vwap / breakout / keep_wait）
scripts/
  monthly_selfselect_run.py   每月作業一條指令（補資料 → 選股 → 改 .env → 可選同步到 VM）
  monthly_rebalance_picker.py 選股引擎（兩種風險組 normal／high_profit、法人確認、過熱剔除）
  stock_selector_grid.py      選股共用函式庫（資料載入／特徵／評分）
  backtest_plan2_monthly_3group.py  每月換股策略回測（含交易成本、誠實池）
test/                      單元測試（unittest）
```

## 快速開始

```bash
# 1) 環境（Python 3.11；玉山 SDK 只支援特定版本，建議照 requirements.txt 安裝）
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2) 設定
cp .env.example.txt .env      # 填入 FINMIND_API_TOKEN / 券商金鑰 / Telegram
vi .env                       # 確認 PC_ 名單與 TOTAL_CAPITAL

# 3) 先手動跑一次選股（dry-run，不會寫任何檔）
.venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5

# 4) 補齊候選池資料（第一次必做）
.venv/bin/python scripts/rebuild_mcap_ranking.py
.venv/bin/python scripts/build_historical_shares.py

# 5) 跑測試
.venv/bin/python -m unittest discover -s test -p 'test_*.py'

# 6) 啟動（模擬帳戶）
.venv/bin/python selfselect_trader.py
```

Docker：

```bash
cp .env.example.txt .env       # 先填好
docker compose up -d --build
docker compose logs -f         # 看主迴圈
```

> 玉山 SDK（`esun_marketdata` / `esun_trade`）**不在 PyPI**，需向玉山證券申請 whl 後放進 `esun_sdk/`。
> 沒有 SDK 時仍可跑回測與選股（只用到 FinMind／yfinance），但無法下單。

## 每月作業（一句話）

```bash
.venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5            # 預覽
.venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5 --apply    # 寫入 .env（自動備份）
```

開啟 `SELFSELECT_AUTO=1` 後，主程式會在 D1 盤後自己做（並發 Telegram 通知），
你只要在 D2 13:25 前看過名單、想改再改 `.env` 即可。細節見 [使用手冊](使用手冊.md)。

## 資料來源與授權

- 股價：FinMind、yfinance（Yahoo Finance）、TWSE 公開資料。
- `cache/` 內的快取檔**不進版控**（可由程式重建，且屬於第三方資料，不散布）。
- 本專案程式碼為**專有授權**（僅供個人學習／研究／學術使用；商業使用須經原作者書面授權，見 [LICENSE](LICENSE)）；第三方資料請遵守其各自授權條款（FinMind 有配額與使用限制）。

## 版權聲明

本專案（TW SelfSelect）僅供個人學習、研究與學術使用。

未經原作者（dinchentech）書面明確授權，嚴格禁止：

1. 將本系統之全部或部分原始碼進行商業販售、出租或轉讓。
2. 將本系統包裝為付費軟體、付費雲端服務或訂閱制產品。
3. 利用本專案進行任何直接或間接獲取商業利益之行為。

- 允許個人學習／研究／學術使用，以及在不涉及商業利益前提下修改與分享（須保留授權聲明）。
- 第三方套件、SDK 與資料來源（FinMind、玉山 SDK、TWSE 等）不在本授權範圍，請遵守其各自條款。
- 完整條文：[LICENSE](LICENSE)
- **商業使用／授權洽詢**：`frank@dinchen.com.tw`（主旨請註明「TW SelfSelect 商業授權」）。
- 備註：本專案早期版本曾以 MIT 授權發布；已依 MIT 取得的副本仍受 MIT 條款保護，無法追溯撤銷。
