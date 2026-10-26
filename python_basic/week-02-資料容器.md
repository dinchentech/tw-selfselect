# 第 2 週：資料容器 — list、dict、DataFrame

## 本週目標
> 能讀懂 `df['close']` 這種寫法，理解 DataFrame 像 Excel 表格一樣有欄位有列。

## 原專案對應檔案
- `strategies/ma_cross.py` 第 13~14 行：`df['MA_Fast'] = df['close'].rolling(window=fast_period...`
- `strategies/bollinger.py` 第 27 行：`df['close'] < df['BB_Lower']`

## 核心觀念
1. **list（列表）**：用中括號包起來的序列，如 `prices = [150, 152, 153]`，用 `prices[0]` 取第一個。
2. **dict（字典）**：用大括號包起來的「Key → Value」配對，如 `params = {"sigma": 1.5, "period": 5}`。
3. **DataFrame**：pandas 套件提供的表格型資料結構，像 Excel。有欄位名稱（column）和索引（index）。
4. **df['close']**：從 DataFrame 中取出名為 close 的整欄資料。
5. **df.iloc[i]**：取出第 i 列的資料（用數字位置）。

## 小程式說明
`week-02-build_dataframe.py` 會讀取 CSV，用 `df.head()` 觀察前 5 列，然後計算每一日相對於前一日的漲跌。

## 本週練習
1. 打開 `strategies/ma_cross.py`，找出 `df['MA_Fast']` 出現的位置
2. 打開 `strategies/bollinger.py`，找出 `df['BB_Middle']` 在哪裡被計算
3. 回答：DataFrame 跟 Excel 有什麼相似之處？

## 學完自評清單
- [ ] 我知道 `df['close']` 是取出 DataFrame 中叫「close」的整欄資料
- [ ] 我知道 `backtest.py` 中的 `STRATEGY_CONFIG` 是 dict 型態
- [ ] 我執行過 week-02-build_dataframe.py 並看到輸出
- [ ] 我能在策略檔案中找出使用 `df['xxx']` 的地方

## 下週預告
下週要學條件判斷（if/else），這是策略決定「要買還是要賣」的核心邏輯。
