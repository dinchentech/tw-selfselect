# 第 2 週：資料容器 — list、dict、DataFrame

## 本週目標
> 能讀懂 `df['close']` 這種寫法，理解 DataFrame 像 Excel 表格一樣有欄位有列。

## 本專案對應檔案
- `strategies/ma_cross.py` 第 19~20 行：`df['MA_Fast'] = df['close'].rolling(window=fast_period, min_periods=1).mean()`
- `strategies/bollinger.py` 第 27 行：`df['close'] < df['BB_Lower']`
- `backtest.py` 第 29 行：`STRATEGY_CONFIG = {` — 整個策略設定就是一個 dict（字典）
- `core/config_loader.py` 第 31 行 `load_portfolio_config()`：把 `.env` 裡每條 `PC_<代號>=...` 的文字用 `json.loads()`（第 66 行）解析成 dict，主程式才讀得到 `strategy`、`alloc` 這些欄位

## 核心觀念
1. **list（列表）**：用中括號包起來的序列，如 `prices = [150, 152, 153]`，用 `prices[0]` 取第一個。
2. **dict（字典）**：用大括號包起來的「Key → Value」配對，如 `params = {"sigma": 1.5, "period": 5}`。`.env` 的 `PC_2330={"strategy":"auto","alloc":20}` 就是一個 dict。
3. **DataFrame**：pandas 套件提供的表格型資料結構，像 Excel。有欄位名稱（column）和索引（index）。本專案的策略都吃日 K 的 DataFrame：`open`／`high`／`low`／`close`／`volume` 五個欄位。
4. **df['close']**：從 DataFrame 中取出名為 close 的整欄資料。
5. **df.iloc[i]**：取出第 i 列的資料（用數字位置）。

## 小程式說明
`week-02-build_dataframe.py` 會讀取 CSV，用 `df.head()` 觀察前 5 列，然後計算每一日相對於前一日的漲跌。

## 本週練習
1. 打開 `strategies/ma_cross.py`，找出第 19 行的 `df['MA_Fast']`，看它從哪一欄算出均線
2. 打開 `strategies/bollinger.py`，找出第 13 行的 `df['BB_Middle']`：為什麼算出 `BB_Middle` 之後，`BB_Upper`／`BB_Lower`（第 15~16 行）就能直接拿來用？
3. 打開 `backtest.py` 第 29~47 行的 `STRATEGY_CONFIG`，回答：它最外層的 Key 是哪些策略名稱？
4. 回答：DataFrame 跟 Excel 有什麼相似之處？

## 學完自評清單
- [ ] 我知道 `df['close']` 是取出 DataFrame 中叫「close」的整欄資料
- [ ] 我知道 `backtest.py` 中的 `STRATEGY_CONFIG` 是 dict 型態
- [ ] 我知道 `.env` 的 `PC_` 條目也是 dict（JSON 格式），由 `core/config_loader.py` 解析
- [ ] 我執行過 week-02-build_dataframe.py 並看到輸出
- [ ] 我能在策略檔案中找出使用 `df['xxx']` 的地方

## 下週預告
下週要學條件判斷（if/else），這是策略決定「要買還是要賣」的核心邏輯。
