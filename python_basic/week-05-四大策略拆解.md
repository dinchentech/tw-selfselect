# 第 5 週：四大策略拆解

### 本週目標
> 能打開四支策略檔案，指出買進條件在哪一行、賣出條件在哪一行，並知道每個參數在做什麼。

### 原專案對應檔案
- `strategies/vwap_deviation.py`（全部 30 行）
- `strategies/ma_cross.py`（全部 46 行）
- `strategies/bollinger.py`（全部 33 行）
- `strategies/breakout.py`（全部 34 行）

### 核心觀念
1. **每支策略的結構都一樣**：先複製資料 → 計算技術指標 → 設定買進條件 → 設定賣出條件 → 回傳。
2. **四個策略可以分兩組**：
   - **逆勢組**（VWAP、Bollinger）：跌深了買、漲多了賣，賺回歸均值。
   - **順勢組**（MA Cross、Breakout）：突破壓力買、跌破支撐賣，賺趨勢延續。
3. **參數就是調整敏感度的旋鈕**：`std_dev=2.0` 調成 `2.5`，通道變寬，訊號變少但更準。
4. **回測是你最好的朋友**：不確定哪組參數好？跑一次 backtest.py 就知道了。

### 本週練習（核心！）
**這週的練習直接在原專案上做，不再是玩小程式。**

1. 依序打開四支策略檔案，各回答三個問題：
   - 哪一行是買進條件？
   - 哪一行是賣出條件？
   - 這個策略有幾個參數？
2. 進入 `python_basic/` 目錄，執行 `python week-05-tweak_params.py`，它會示範如何用 DSH 改參數。

### 學完自評清單
- [ ] 我能在 vwap_deviation.py 中找出買進條件（第 26 行）
- [ ] 我能在 ma_cross.py 中找出黃金交叉的條件（第 36 行）
- [ ] 我能在 bollinger.py 中找出布林下軌的計算（第 16 行）
- [ ] 我能在 breakout.py 中找出 ATR 波動度過濾（第 27 行）
- [ ] 我執行過 `python backtest.py --strategy bollinger --std_dev 2.5` 並看到不同結果

### 下週預告
下週要看 live_trader_finmind.py — 實盤交易的「心臟」是怎麼跳動的。
