# 第 4 週：移動平均與 rolling window

## 本週目標
> 理解 `rolling(window=20).mean()` 是什麼意思，知道為什麼策略需要至少 22 根 K 線才能穩定。

## 原專案對應檔案
- `strategies/ma_cross.py` 第 13~14 行：兩個 rolling 計算
- `strategies/bollinger.py` 第 13~14 行：rolling 計算通道
- `strategies/breakout.py` 第 14~15 行：rolling 計算通道
- `strategies/vwap_deviation.py` 第 18 行：rolling 計算標準差

## 核心觀念
1. **移動平均（Moving Average）**：取最近 N 天的收盤價算平均。N=5 就是「近 5 天平均成本」。
2. **rolling(window=N)**：pandas 的滑動視窗功能。window=20 表示一次看 20 根 K 線。
3. **warm-up 問題**：如果沒有 20 筆資料，rolling 就無法計算。前 N-1 根 K 線會是 NaN（無效值）。
4. **min_periods**：有些策略用了 `min_periods=1`（如 Bollinger），意思是至少有 1 筆就開始算，但早期資料不穩定。
5. **參數的意義**：backtest.py 中每個 `window`、`period`、`lookback` 都代表 rolling 的 N。

## 小程式說明
`week-04-rolling_demo.py` 會示範 rolling 的實際效果：用手算與 pandas 算對比，觀察前 N-1 根是 NaN，了解 warm-up 需要多少資料。

## 本週練習
1. 打開 `strategies/ma_cross.py`，找出第 13 行 `rolling(window=fast_period` 和第 14 行 `rolling(window=slow_period`
2. 在 `USER_MANUAL.md` 中找到「策略暖身所需最少 K 線數」章節，對照你看到的 rolling window 大小
3. 回答：為什麼背後的說明一直強調回測要給 1 年以上的資料？

## 學完自評清單
- [ ] 我知道 `rolling(window=5).mean()` 就是「最近 5 天的平均」
- [ ] 我理解為什麼前 4 根 K 線的 rolling 是 NaN
- [ ] 我執行過 week-04-rolling_demo.py 並理解輸出
- [ ] 我能在策略中找到所有使用 `rolling()` 的地方

## 下週預告
下週開始進入真正的主題：拆解四大策略的完整程式碼！
