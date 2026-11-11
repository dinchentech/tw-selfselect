# 第 6 週：selfselect_trader.py 是怎麼活的？

## 本週目標
> 能讀懂 `selfselect_trader.py` 的主要流程：啟動 → 主迴圈（08:40 熱重載 → 盤中每分鐘檢查 → 13:25 下單窗口 → 13:45 報告 → 休眠）→ 每月 D1 選股／D2 進場 → 訊號判斷 → 風控 → 下單 → 通知。

## 本專案對應檔案
- `selfselect_trader.py` `main()`：第 212 行起；`while True:` 主迴圈第 637 行
- `core/selfselect_scheduler.py`：每月 D1 13:36 起自動選股、D2 08:05–08:39 補跑（`run_if_due`，第 274 行）
- `scripts/monthly_selfselect_run.py`：真正去補資料、跑選股、改 `.env` 的程式（會先備份 `.env`，且**絕不刪掉已持倉**）
- `core/risk_manager.py`（風控）、`core/market_filter.py`（大盤年線）、`core/park_asset.py`（閒置資金停泊 0050）
- `core/live_utils.py`（交易日曆、下單窗口、成交回報解析）、`data/esun_provider.py`（玉山行情／下單）

## 核心觀念

### 1. 一天的時間軸
程式不是單純的 `while True + sleep(60)`，而是**每分鐘看一次「現在該做哪件事」**：

```
08:40 ─────────────── 09:00 ────── 13:25 ─ 13:30 ─ 13:45 ──────► 隔天 08:40
   │                    │            │        │       │
   ▼                    ▼            ▼        ▼       ▼
 熱重載 .env          盤中開始    日K下單窗口  收盤   日報＋儀表板
 換新名單生效         每分鐘跑策略  （5 分鐘）         然後休眠
```

- **08:40**：熱重載 `.env`（`selfselect_trader.py` 第 650~676 行）。這是**換股生效點**：D1 選股寫進 `.env`，隔天 08:40 才進到執行中的程式。
- **08:40 之後～盤前**：`.env` 的內容指紋一變（第 678~690 行）就**立刻**套用，不必等隔天——所以 D2 13:25 前改完名單，當天就吃得到。
- **09:00–13:30**：盤中每分鐘圈（`intraday_trade_window`，第 722 行）跑每檔策略訊號、庫存檢查、孤兒清倉。**日 K 策略的委託只在 13:25–13:30 送出**（`close_order_window_open`，第 646 行；`CLOSE_ORDER_FROM` 可調）。
- **13:31 以後**：13:45 發收盤日報＋睡前持倉報告、產生儀表板（第 1232~1246 行）；這一天若是每月第 1 個交易日，13:36 起觸發自動選股（第 1257 行）。
- **其餘時間**：算出下次開盤，休眠（第 1350 行；單次最多睡 1 小時，期間每 30 秒醒一下並檢查 `.env`，第 1388 行）。

### 2. 每月的兩個交易日（D1／D2）
```
D1（每月第 1 個交易日）13:36 起
   core/selfselect_scheduler.run_if_due()
        │  （D1 沒跑到 ⇒ D2 08:05–08:39 補跑）
        ▼
   scripts/monthly_selfselect_run.py
        補資料 → 跑選股 → 算出新名單 → 備份後改 .env 的 PC_ 區段 → Telegram 通知
        │
        ▼
D2（每月第 2 個交易日）08:40 熱重載生效 → 13:25–13:30 買進新名單
   ⇒ 已持倉的一律保留（滿倉＝N 檔都在手上時不換股）
```
選股不是你手動買；程式只負責「把名單換成新的」，實際買進還是走第 3 點那條路。

### 3. 訊號 → 風控 → 下單
```
策略產生訊號（1=買 / -1=賣 / 0=不動）
        │   selfselect_trader.py 第 847~849 行：signal = strat_func(acd, **strat_params)['signal'].iloc[-1]
        ▼
  庫存檢查（第 1022 行：持倉已達目標就不重複買；第 1030 行：賣出前先看 holdings 股數，0 股就不動作）
  空手不會賣、已滿倉不重複買
        │
        ▼
  RiskManager.check_trade_allowed()（第 1033 行）
  回傳 (bool, reason)：單筆風險／每日虧損／每日交易次數 被擋時會帶原因
        │
        ▼
  大盤年線過濾（第 1046 行，MARKET_TREND_FILTER=true 時）
  core/market_filter.py 用 TWSE 公開 API 算 MA200，指數在年線下就不買
        │
        ▼
  下單（玉山 SDK）→ 更新三本帳 → Telegram 通知
```

### 4. 三本帳（很重要）
| 檔案 | 記什麼 | 用途 |
|---|---|---|
| `logs/holdings.json` | 每檔持有股數 | 賣出前檢查持有數：`持有 0 股卻想賣 → 跳過`，避免重啟後「空賣」 |
| `logs/performance.csv` | 每筆成交明細（含手續費、證交稅） | 儀表板、日報、回測對帳 |
| `logs/stock_allocation.json` | 每檔分帳本（成本、股數、上限） | 資金上限與均價計算 |

三者股數對不起來的時候，主程式會發 Telegram 告警（第 696 行「三本帳一致性斷言」）。

### 5. 閒置資金停泊（0050）
名單建倉完成後，還沒用到的錢會拿去買 `SELFSELECT_PARK_ASSET`（預設 `0050`），要買股票前先全部賣掉再買。
這一步記在**獨立帳本** `logs/park_position.json`，不會被當成自選股（`core/park_asset.py`）。

### 6. 券商與「假錢／真錢」
- `BROKER=esun` → 玉山證券（行情＋下單，本專案主要用法）；`BROKER=kgi` → 凱基（可 mock）
- `ESUN_ENVIRONMENT=simulation` → **模擬帳戶**（預設）；`real` → 真錢。切 `real` 前請先照 `使用手冊.md` §8 的檢查清單走一遍。

### 7. 資金配置不是「每個策略一個比例」
舊的寫法是 `TOTAL_CAPITAL` 配 `ALLOC_<策略>`；本專案是**每檔股票一條 `PC_` 設定**：

```ini
TOTAL_CAPITAL=500000                     # 可動用總資金
SELFSELECT_TOP_N=5                       # 名單上限 N 檔
SELFSELECT_LEG_PCT=100                   # 自選股腿佔比 ⇒ 每檔 alloc = 100 ÷ 5 = 20%
PC_2330={"strategy":"auto","alloc":20}   # 這檔用型態自動路由、配 20% 資金
PC_2454={"strategy":"vwap","alloc":10}   # 這檔固定用 VWAP、配 10%
```
每筆交易前會檢查該檔是否已用盡自己的 `alloc`（分帳本的上限）。

## 小程式說明
`week-06-simple_live.py` 是一個簡化版的「選股 → 建倉 → 每天檢查 → 賣出」流程 —
它用同一份 CSV 模擬 D1 選股、D2 買進、之後每天 13:25 檢查策略訊號出場，讓你體會主迴圈在做什麼。

## 本週練習
1. 打開 `selfselect_trader.py`，找出 `while True:`（第 637 行），往下數：哪一行是「交易日＋下單窗口」的判斷（第 641~646 行）？
2. 找出 13:31 之後發日報的分支（第 1232 行），看看它還做了哪兩件事（提示：儀表板、D1 自動選股）
3. 找出 `rm.check_trade_allowed(` 的呼叫（第 1033 行），回答：它回傳幾個值？被擋時 Telegram 會發什麼訊息？
   （答案線索在第 1034~1037 行：`🛑 *代號* 風險控管攔截（原因）`）
4. 打開 `core/selfselect_scheduler.py`，找出 `D1_FROM`／`D2_FROM` 兩個時窗（第 44~45 行）
5. 打開 `core/park_asset.py` 的檔頭說明，回答：為什麼停泊部位要記在獨立帳本？

## 學完自評清單
- [ ] 我知道程式一天的時間軸：08:40 熱重載 / 盤中 / 13:25 下單窗口 / 13:45 報告 / 休眠
- [ ] 我知道每月 D1 選股、D2 進場，且 `.env` 的生效點是 08:40 熱重載
- [ ] 我知道 `logs/holdings.json` 記錄已持有的股數，避免空賣
- [ ] 我知道 `check_trade_allowed()` 回傳 `(bool, reason)`，被擋時會說原因
- [ ] 我知道「三本帳」是 `holdings.json`＋`performance.csv`＋`stock_allocation.json`
- [ ] 我知道 `PC_<代號>` 決定每檔股票用什麼策略、配多少資金
- [ ] 我執行過 week-06-simple_live.py 並看到模擬的選股／建倉／出場輸出

## 下週預告
下週要學最重要的一招：用 AI（DSH）幫你改程式！
