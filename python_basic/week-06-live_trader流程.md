# 第 6 週：live_trader 是怎麼活的？

## 本週目標
> 能讀懂 `live_trader_multi.py` 的主要流程：初始化 → 三階段主迴圈（盤中交易 / 收盤日報 / 休眠）→ 訊號判斷 → 下單 → 風險控管。

## 原專案對應檔案
- `live_trader_multi.py` 第 153~506 行（main 函式完整流程）
- `live_trader_finmind.py` 第 38~154 行（簡化版，單股單策略）
- `core/risk_manager.py`（風險控管邏輯）
- `core/market_filter.py`（大盤年線過濾）

## 核心觀念

### 1. 三階段主迴圈（Phase Loop）
程式不再是單純的 `while True + sleep(60)`，而是根據時間切換三種模式：

```
08:45 ────────────────────────── 13:30 ── 13:45 ──────► 隔天 08:45
      │                          │        │
      ▼                          ▼        ▼
   時段 1                     時段 2    時段 3
   盤中交易                   收盤日報   休眠
  每分鐘檢查                 發送 TG   休眠到下次開盤
  跑策略、下單                          每小時醒一次檢查
```

- **時段 1（08:45-13:30）**：暖機 15 分鐘 → 開始每分鐘檢查訊號
- **時段 2（13:30-13:45）**：收盤後產生交易日報發送到 Telegram
- **時段 3（其餘時間）**：算出下次開盤時間，休眠到那個時候（期間每小時醒來確認一次）

### 2. 多股多策略分流
一次監控多檔股票，每檔搭配不同策略：
```
0xx0 → BOLLINGER（逆勢）
2xx0 → MA_CROSS（順勢）
2xx1 → VWAP（逆勢）
2xx2 → BREAKOUT（順勢）
```
投資組合從 `.env` 的 `PORTFOLIO` 變數讀取。

### 3. 訊號 → 風險檢查 → 下單
```
策略產生訊號（1=買 / -1=賣 / 0=不動）
        │
        ▼
 風險控管檢查（單筆風險 / 每日虧損 / 交易次數）
  回傳 (bool, reason) → 被擋時會說原因
        │
        ▼
  大盤年線過濾（MARKET_TREND_FILTER=true 時）
  用 TWSE FMTQIK API（免 FinMind Token）
        │
        ▼
  庫存檢查（持有股數夠不夠賣？防假賣出）
        │
        ▼
  執行下單 → 更新 holdings.json → Telegram 通知
```

### 4. 庫存追蹤（holdings）
- 每次買進/賣出後，記錄在 `logs/holdings.json`
- 賣出前檢查持有數：`持有 0 股卻想賣 → 跳過`
- 避免重啟容器後「空賣」

### 5. Broker 選擇
支援兩家券商，從 `.env` 的 `BROKER` 設定：
- `BROKER=kgi` → 凱基（可 mock 模擬）
- `BROKER=esun` → 玉山（自動啟用真實 API）

### 6. 資金配置
從 `.env` 讀取總資金與各策略分配比例：
```ini
TOTAL_CAPITAL=500000
ALLOC_BOLLINGER=40    # 40% → NT$200,000
ALLOC_VWAP=20         # 20% → NT$100,000
ALLOC_MA_CROSS=25     # 25% → NT$125,000
ALLOC_BREAKOUT=15     # 15% → NT$75,000
```
每筆交易前會檢查該策略是否已用盡配額。

## 小程式說明
`week-06-simple_live.py` 是一個簡化版的監控程式 — 它模擬「每分鐘檢查一次」的感覺，讓你體會主迴圈的概念。

## 本週練習
1. 打開 `live_trader_multi.py`，找出三階段的 `if/elif/else` 判斷（第 317~396 行）
2. 找出 `holdings.get(symbol, 0)` 的庫存檢查（第 428 行）
3. 找出風險控管檢查 `check_trade_allowed()` 回傳了哪些攔截原因
4. 比較 `live_trader_finmind.py`（單股）與 `live_trader_multi.py`（多股）的差異

## 學完自評清單
- [ ] 我知道程式的三階段：盤中交易 / 收盤日報 / 休眠
- [ ] 我知道 `holdings.json` 記錄已持有的股數，避免空賣
- [ ] 我知道 `check_trade_allowed()` 回傳 `(bool, reason)`，被擋時會說原因
- [ ] 我知道 `PORTFOLIO` 變數決定監控哪些股票各配什麼策略
- [ ] 我執行過 week-06-simple_live.py 並看到模擬的監控輸出

## 下週預告
下週要學最重要的一招：用 AI（DSH）幫你改程式！
