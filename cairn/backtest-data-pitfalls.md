---
type: project_topic
status: active
summary: "回測數字無法重現的三類根因（快取語義變更、長短歷史互相覆寫、半成品 K 棒）與現行防護；部分內容由程式註解反推，待人工校正"
tags: [回測, 快取, 資料品質, 事故]
contains: [背景, 當前結論, 實踐指南, 教訓, 開放問題]
created: "2026-10-26"
updated: "2026-10-26"
related: [environment-scope.md, total-assets-reconciliation.md]
authoring_mode: ai_generated
---
# 回測資料陷阱

> 內容來源：由 AI 從 `core/cache_io.py`、`core/inst_data.py`、`core/price_append.py`、`scripts/stock_selector_grid.py` 的註解與 docstring 反推整理（2026-10-26）；描述的是現行程式行為與防護措施。

## 背景

基線事實：**README 的 2015-2021 回測 +49.37% 曾在 2026-08 無法重現**。後來追出的根因不只一個，是同一個症狀下的三類問題。

## 當前結論

### 一、快取語義變更沒遞增版本（2026-08）

價格快取**混入了 yfinance 還原價**，與既有 FinMind 口徑混用 ⇒ 同一策略、同一區間算出不同績效。

機制與防護（`core/cache_io.py`，現行 `CACHE_SCHEMA_VERSION = 2`）：

- 快取資料的語義改變（欄位／價格調整／正規化方式）時**必須遞增版本**，否則舊快取會被**靜默載入**。
- 可重建快取（股價／法人／選股池）→ `load_cache`／`dump_cache`，版本不符自動重建。
- 累積型資料庫（`mcap_ranking`／`historical_shares`）→ `load_cache_or_raw`：舊格式原樣讀入（不丟棄無法重建的歷史），下次寫入時才升級為版本化。

### 二、長短歷史互相覆寫（2026-08-25）

回測與實盤**共用** `cache/inst_momentum/price/`，實盤的短歷史覆寫了回測的長歷史 ⇒ 2015-2020 無價格 ⇒ 魚過濾全滅 ⇒ README 數字無法重現。

現行做法：

- 回測走**獨立快取目錄** `cache/inst_momentum/bt_price/`，meta 記錄 `start`／`end`。
- 回測一律用 FinMind（與實盤同資料層，`fetch_price_history_bulk`）；**不要用 yfinance 補回測**。
- FinMind 免費配額 600/hr，遇 402 自動等待後重試（預設 `retry_wait=3600`、`max_retries=2`）；首次下載若遇配額殘缺會造成「全窗口假數字」，重跑前必須確認窗口完整。

### 三、半成品 K 棒（2026-09-17 / 09-18）

yfinance 對**最新交易日**常回傳「只有 volume、OHLC 全 NaN」的列（2026-09-17 當天 500/500 檔全是這種列）⇒ 快取最後一列（＝選股基準日）是 NaN ⇒ `score_stock()` 的 close／波動／均線全變 NaN ⇒ `total` 全 NaN ⇒ 排序失效 ⇒ **亂選**（實測選出 2317／2881／2882，總分全是 NaN）。

兩端防護，缺一不可：

- **source 端**：`core/price_append.drop_unusable_rows()` 丟掉 close 為 NaN 或 ≤ 0 的列；寧可那天不進快取（隔天補價會自然補上）。
- **消費端**：`scripts/stock_selector_grid.py` 的 `_drop` 一併擋掉**已經躺在快取裡的**舊 NaN 列（只影響含 NaN 的資料，歷史回測結果不變）。

原則：**舊歷史一個位元都不動**（回測可重現性優先），所以修好 source 端之後**已經寫進去的壞列不會自己消失**，要用修補工具清（見下）。

### 四、周邊同類地雷

- `core/fees.py`：2026-09-17 前的舊列**沒有 `cost` 欄** ⇒ pandas 讀成 `NaN`（不是 `None`／`""`）；不擋會讓總計變成 NaN，需用 `math.isnan` 判。
- `scripts/rebuild_mcap_ranking.py`：法人動能資料的**寫入者在 repo 外／加密程式內**，repo 內沒有產生器 ⇒ 這份資料無法從頭重建，只能累積。

## 實踐指南

| 症狀 | 動作 |
|---|---|
| 快取裡有 NaN／≤0 的 close | `scripts/append_selector_prices.py --drop-nan --apply`（補救用，只丟列不補價；預設備份到 `cache/selector_prices_bak_<時間戳>`） |
| 懷疑接縫有假跳空 | 同腳本 `--truncate-after <日期>` 先丟掉該日之後的列再重跑（舊列不受影響）；`--no-splice` 可關掉接縫縮放 |
| 回測數字對不上 README | 先確認是否混到 `bt_price/` 以外的快取、是否用了 yfinance 價格、`CACHE_SCHEMA_VERSION` 是否被改過而沒遞增 |
| 想改快取欄位或價格口徑 | 先遞增 `CACHE_SCHEMA_VERSION`，再重跑產生器 |

`cache/` 下的 `selector_prices_bak_<時間戳>` 目錄是歷次事故留下的快照（可見 2026-09-14、09-18 `nanfix`、10-01、10-06、10-25 等），可作為比對歷史證據；`cache/` 本身不進版控。

## 教訓

- **資料層的語義變更是回測最大的隱形殺手**：程式沒改、資料口徑變了，績效就變了，而且不會報錯。
- **「最新交易日」是資料品質最差的一天**：選股基準日正好落在這裡，等於用半成品資料做決策。
- **修補要留備份與開關**：預設 dry-run、預設備份、測試一律指向 tmp（`--backup-dir`），否則會弄壞真實快取。
- **實驗與實盤的資料要分倉**：共用目錄就會互相覆寫，而且是靜默的。

## 開放問題

1. `cache/inst_momentum` 法人動能的寫入者在 repo 外；是否要補一份口徑文件，或至少把「不可從頭重建」寫進資料來源清單？
2. `bt_price/` 與實盤 `price/` 目錄分倉靠慣例（預設參數），沒有硬性防護；要不要在 `fetch_price_history_bulk` 加一道「caller 沒指定目錄就拒絕」的檢查？
