# 第 4 週：移動平均與 rolling window

## 本週目標
> 理解 `rolling(window=20).mean()` 是什麼意思，知道為什麼策略需要先「暖身」、為什麼回測要給足資料。

## 本專案對應檔案
- `strategies/ma_cross.py` 第 19~20 行：兩個 rolling 算快線／慢線
- `strategies/bollinger.py` 第 13~14 行：rolling 算通道中線與標準差
- `strategies/breakout.py` 第 19~20 行：rolling 算唐奇安通道的最高／最低
- `strategies/vwap_deviation.py` 第 23 行：rolling 算偏差的標準差

## 核心觀念
1. **移動平均（Moving Average）**：取最近 N 天的收盤價算平均。N=5 就是「近 5 天平均成本」；本專案 MA Cross 用 `fast_period=9`、`slow_period=21`。
2. **rolling(window=N)**：pandas 的滑動視窗功能。window=20 表示一次看 20 根 K 線。本專案策略全部吃**日 K**，所以是 20 個交易日。
3. **warm-up 問題**：如果沒有 20 筆資料，rolling 就無法計算。前 N-1 根 K 線會是 NaN（無效值）。
4. **min_periods=1**：本專案四支策略都寫 `min_periods=1`，意思是「有 1 筆就開始算」。好處是第一根就有值、不會整欄空掉；代價是前 N-1 根算出來的均線／通道不穩定。
5. **實盤的暖身**：`selfselect_trader.py` 第 501 行啟動時對每檔抓 `days=260` 的日 K（約一年份）才開始跑策略；`backtest.py` 的 `--start` 預設 `2023-01-01`（第 141 行）。資料給太少，策略前面那段等於在亂做。

## 小程式說明
`week-04-rolling_demo.py` 會示範 rolling 的實際效果：用手算與 pandas 算對比，觀察前 N-1 根是 NaN，了解 warm-up 需要多少資料。

## 本週練習
1. 打開 `strategies/ma_cross.py`，找出第 14 行 `rolling(window=fast_period` 和第 15 行 `rolling(window=slow_period`
2. 打開 `策略說明.md` §5.1（第 398 行起），找到布林通道 `window=20`、`std_dev=2.0` 的說明，對照 `strategies/bollinger.py` 第 13~16 行
3. 回答：為什麼回測要給足資料？（提示：`rolling(20)` 前 19 根是 NaN，回測出現 NaN 的那段等於沒有策略）

## 學完自評清單
- [ ] 我知道 `rolling(window=5).mean()` 就是「最近 5 天的平均」
- [ ] 我理解為什麼前 4 根 K 線的 rolling 是 NaN
- [ ] 我知道本專案策略都用 `min_periods=1`，以及它換到什麼、犧牲什麼
- [ ] 我執行過 week-04-rolling_demo.py 並理解輸出
- [ ] 我能在策略中找到所有使用 `rolling()` 的地方

## 下週預告
下週開始進入真正的主題：拆解四大固定策略的完整程式碼！
