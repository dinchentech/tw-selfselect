---
type: project_topic
status: active
summary: "回測數字無法重現的三類根因（快取語義變更、長短歷史互相覆寫、半成品 K 棒）與現行防護；部分內容由程式註解反推，待人工校正"
tags: [回測, 快取, 資料品質, 事故]
contains: [experience, procedure, lesson, open_question]
created: "2026-10-26"
updated: "2026-10-28"
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

### 五、短歷史造成的「暖機空池」（2026-10-28 查獲，比上面三類更陰險）

價格快取幾乎都只從 **2022-01-03** 開始（當初是「標的進池才抓近 250 天」）。選股評分需要約 3 個月歷史
⇒ **2022 年 1~3 月每組都選不出股票**（`PICKERS` 回空 list，程式**不報錯**），回測等於「4 月才進場」，
**無意間跳過 2022 年初的大跌** ⇒ 2022-2025 正常組因此從 +19.9% 被美化成 +59.1%。

- 症狀：`selection_log` 前幾個月的 `S` 是空 list 且 `skipped=False`（不是股災防護，是沒資料）；
  或 `逐季池: 47 季點, 空池 28`（28 個季點沒有任何標的同時有股本與價格）。
- 修法：`scripts/prepend_selector_prices.py --apply` 把快取第一天之前的歷史補進來（只補、**既有列不動**、
  用重疊日 `ratio=舊÷新` 縮放新增段以吸收 yfinance 還原價的版本差異）；補完空池從 28 個季點降到 4 個。
- 教訓：**「回測看起來贏在起跑點」要先去查那段時間有沒有真的持倉**；空 list 不報錯是這類 bug 的共同特徵。

### 六、回測缺實盤濾網：大盤年線（2026-10-28 補上）

實盤買進前會檢查**加權指數是否在 MA200 之上**（`selfselect_trader.py:819` → `core/market_filter.py`，
`.env` 的 `MARKET_TREND_FILTER=true`），指數在年線下就跳過買進。**回測腳本原本沒有這條規則** ⇒
2018／2022 空頭年的回測比實盤更差（實盤那段根本不買）：2022-2025 正常組 MDD 因此從 −46.4%（假象）變成 −18.4%。

- 指數資料：`scripts/build_market_index.py` 逐月抓 TWSE `FMTQIK`（免 token）→ `cache/market_index/taiex.pkl`
  （2015-01-05 起 2,878 筆；只補缺月）。
- 回測開關：`MARKET_FILTER=1`（**預設 0**；刻意不沿用 `MARKET_TREND_FILTER`——`.env` 已設 true，
  沿用會讓所有既有回測靜默改變）。只擋買進、賣出照舊。判定是純函式 `core/backtest_rules.above_ma200()`。
- 同名資料也要注意：**法人確認**快取全期只有 41 個交易日 ⇒ 回測裡那道濾網實質沒作用（實盤每天有資料）。

### 七、倖存者偏差：宇宙只含「今天還活著」的股票（2026-10-29 修）

`historical_shares.pkl` 只有 610 檔**今天還在交易**的股票 ⇒ 季池（當時市值前 N）**結構上不可能**選到後來下市／被併的公司，
而回測會因此高估績效。實測：池 20 每季平均 **2.2 檔**、池 150 **10.8 檔** 已下市股本該進池；2016-01 的前 5 名
（6452 康友-KY、2325 矽品、1704 榮化、3474 華亞科、2311 日月光）全部是後來下市／被併的公司。

修法與兩條必須保留的細節：

- 宇宙：`core/candidate_pool.load_historical_shares()` 併入 `historical_shares_delisted.pkl`（TWSE 2016-2025 下市 62 檔；
  `UNIVERSE_DELISTED=0` 可關閉以量化偏誤）。**91xx 台灣存託憑證要排除**，否則與存活宇宙口徑不一致。
- 下市股價格**沒有現成來源**：Yahoo 回 0 筆、FinMind `TaiwanStockPriceAdj` 對下市股回 400 ⇒ 只能用
  `TaiwanStockPrice` 原始價 + `TaiwanStockDividend` 現金股利**自己做向後還原**（`TMP/build_delisted.py`），屬「另一個版本」的價格。
- 新鮮度閘門：`build_quarterly_pool(max_stale_days=45)`——季點前 45 天內沒有成交價就視為「當時買不到」。
  少了這條，下市股會用它最後一個價格一直留在後面的季池裡，甚至滲進實盤選股。
- 期末估值：引擎 `_roll()` 會把 close **ffill** 到全期日曆 ⇒ 下市持股以「最後成交價」續值、被剔除時以該價賣出。
  對被併購下市（溢價）是對的，對「停牌→下市」的地雷股（6452 康友-KY 最後成交 56.6、實務上幾乎歸零）**偏樂觀**。

**修正後的效果不是單向的**：大池被下修（池150＋營收＋產業2 +1289.5%→+1070.5%）、小池反而略升（池20 +369.4%→+395.1%），
因為補進來的 62 檔同時含地雷股與被溢價併購股。⇒ 不要用「偏差一定往哪邊」來推理，要重跑。

### 八、因子快取「補到一半」比沒補更危險：月營收覆蓋率（2026-10-29 查獲）

`FACTOR_REVENUE=1` 時月營收 YoY 是評分因子之一，**缺值以中性 0 計**（不會踢掉該股）。
問題是缺值比例會隨補資料而變，於是同一支回測程式、同一組參數，**換個時間跑就得到不同答案**：

| 月營收快取 | 池 150＋營收＋產業上限 2（2016-2025） |
|---|---:|
| 515/672 檔 | +1070.5% |
| 645/672 檔 | **+1323.6%** |

差 253 pp，而且方向剛好是「資料補齊 → 看起來變好」⇒ 很容易把**資料補齊**誤讀成**策略變好**。

- 檢查：`ls cache/stock_revenue/*.pkl | wc -l`（應接近宇宙檔數 672）；或缺檔清單由 `load_historical_shares()` 算。
- 修法：`TMP/build_revenue_missing.py`（FinMind `TaiwanStockMonthRevenue`、可重複執行、402 自動等配額）。
  2026-10-29 補了 123 檔，**另 27 檔 FinMind 完全沒有月營收資料**（多為早期下市／小型股，如 2847 大眾銀行、2856 元富證券）。
- 紀律：**比較參數前先把資料補滿，並在報告寫下快照**（本次：宇宙 672、PER 672、月營收 645）。

### 九、資格門檻默默吃掉 6 成候選股：PER 快取覆蓋率（2026-10-29 修）

`SCORING_MODEL=zscore` 的資格是 `0 < PER <= 40`（`core/scoring.eligible()`），**沒有 PER 的股票根本不會被選到**。
實測 `cache/stock_per/` 只有 **267/672 檔** ⇒ 回測等於「先偷看過誰有本益比資料」，而新補進來的下市股 0 檔有 PER。

- 檢查 symptom：回測結尾的 `[PER 快取] 完全查不到 PER N 次`；`N` 很大就代表資格門檻在亂篩人。
- 修法：`TMP/build_per_missing.py`（FinMind `TaiwanStockPER` 一次抓 2015 起全段、可重複執行、402 會等配額解鎖）。
- 補齊後 **`FILL_MODE=topup` 在池 20 完全沒作用**（每月都選得滿 5 檔），這是健康訊號，不是 bug。

## 實踐指南

| 症狀 | 動作 |
|---|---|
| 快取裡有 NaN／≤0 的 close | `scripts/append_selector_prices.py --drop-nan --apply`（補救用，只丟列不補價；預設備份到 `cache/selector_prices_bak_<時間戳>`） |
| 懷疑接縫有假跳空 | 同腳本 `--truncate-after <日期>` 先丟掉該日之後的列再重跑（舊列不受影響）；`--no-splice` 可關掉接縫縮放 |
| 回測數字對不上 README | 先確認是否混到 `bt_price/` 以外的快取、是否用了 yfinance 價格、`CACHE_SCHEMA_VERSION` 是否被改過而沒遞增 |
| 回測前幾個月選不出股票／`逐季池` 空池很多 | 短歷史暖機空池 ⇒ `scripts/prepend_selector_prices.py --apply`（先 dry-run 看要補幾檔） |
| 想跟實盤等價比較 | 加 `MARKET_FILTER=1`（指數在 MA200 下不買）；先跑 `scripts/build_market_index.py` 建 TAIEX 快取 |
| 懷疑回測被倖存者偏差高估（池越大越可疑） | 確認 `UNIVERSE_DELISTED` 沒被設成 0；宇宙應為 672 檔（610 存活＋62 下市） |
| 選股結果怪異、某類股永遠不會被選 | 查 `cache/stock_per` 覆蓋率（`ls cache/stock_per/*.pkl | wc -l`，應為 672） |
| 開了營收因子後數字變來變去 | 查 `cache/stock_revenue` 覆蓋率（應 645/672）⇒ 缺檔先跑 `TMP/build_revenue_missing.py` |
| 想改快取欄位或價格口徑 | 先遞增 `CACHE_SCHEMA_VERSION`，再重跑產生器 |

`cache/` 下的 `selector_prices_bak_<時間戳>` 目錄是歷次事故留下的快照（可見 2026-09-14、09-18 `nanfix`、10-01、10-06、10-25 等），可作為比對歷史證據；`cache/` 本身不進版控。

## 教訓

- **資料層的語義變更是回測最大的隱形殺手**：程式沒改、資料口徑變了，績效就變了，而且不會報錯。
- **「最新交易日」是資料品質最差的一天**：選股基準日正好落在這裡，等於用半成品資料做決策。
- **修補要留備份與開關**：預設 dry-run、預設備份、測試一律指向 tmp（`--backup-dir`），否則會弄壞真實快取。
- **實驗與實盤的資料要分倉**：共用目錄就會互相覆寫，而且是靜默的。

## 開放問題

1. **上櫃（TPEX）下市股沒有納入宇宙**：TWSE OpenAPI 有下市清單、TPEX 找不到對應端點 ⇒ 宇宙仍不完整（2026-10-29 已知缺口）。
2. 下市股價格是「自建現金股利還原」，與既有 yfinance 還原價不同源；要不要統一成同一套還原流程？
3. `cache/inst_momentum` 法人動能的寫入者在 repo 外；是否要補一份口徑文件，或至少把「不可從頭重建」寫進資料來源清單？
2. `bt_price/` 與實盤 `price/` 目錄分倉靠慣例（預設參數），沒有硬性防護；要不要在 `fetch_price_history_bulk` 加一道「caller 沒指定目錄就拒絕」的檢查？
