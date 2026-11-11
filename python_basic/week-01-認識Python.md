# 第 1 週：認識 Python — 變數、數字、文字

### 本週目標
> 能讀懂策略檔案裡的 `= 1.5`、`= "auto"` 這種寫法，知道數字和文字的差別。

### 本專案對應檔案
- `strategies/vwap_deviation.py` 第 17 行：`def vwap_deviation_strategy(df, sigma_mult=1.5, rsi_period=5, rsi_low=30, rsi_high=70)` — 函式後面那群 `名稱=值` 就是參數，值全是數字
- `strategies/vwap_deviation.py` 第 19 行：`df['VWAP'] = calculate_vwap(df['close'], df['volume'])` — `'VWAP'` 是文字，`df['close']` 裡的 `'close'` 也是文字
- `backtest.py` 第 32 行：`"params": {"sigma_mult": 1.5, "rsi_period": 5}` — 同樣的參數，回測版也寫了一份
- `.env` 的 `PC_` 條目（範例見 `.env.example.txt` 第 161 行）：`PC_2330={"strategy":"auto","alloc":20,"max_entry_price":980}` — `"auto"` 是文字、`20` 和 `980` 是數字

### 核心觀念（5 點）
1. **變數（Variable）**：就是用一個名字來裝資料。像是「股價 = 150」，以後用「股價」這個名字就能拿到 150。
2. **數字型態**：Python 有整數（int）如 `20`、小數（float）如 `1.5`。策略參數兩者都有——`window=20` 是整數、`std_dev=2.0` 是小數。
3. **文字型態（string）**：用引號包起來的，如 `"auto"`、`'close'`。策略名稱、欄位名稱都是文字。
4. **print()**：把東西印出來給你看，是程式除錯最重要的工具。實盤程式也靠 print 把 `🔔 交易通知`、`⚠️` 這類訊息寫進日誌。
5. **加減乘除**：`+ - * /`，報酬率計算就是 `(賣價 - 買價) / 買價`。

### 小程式說明
`week-01-calc_return.py` 會讀取 `data/prices_short.csv`，用最後一天的收盤價減去第一天的收盤價，除以第一天的收盤價，算出這段期間的報酬率。

這跟 `backtest.py` 的 `calculate_performance()`（第 200 行附近）在算單筆交易報酬用的是同一個公式：
`(next_close - close) / close`。

### 本週練習
1. 打開 `strategies/vwap_deviation.py`，找出第 17 行的函式定義，找到 `sigma_mult=1.5` 和 `rsi_period=5`
2. 打開 `backtest.py`，找出第 32 行的 `"sigma_mult": 1.5`
3. 打開 `.env.example.txt`，找出第 161 行的 `PC_2330=...`，回答：`"auto"` 是數字還是文字？`20` 呢？
4. 回答：`1.5` 是數字還是文字？`"vwap"` 呢？

### 學完自評清單
- [ ] 我知道 `= 1.5` 是把 1.5 這個數字存進一個名字裡
- [ ] 我知道 `"auto"` 和 `auto` 的差別（引號 vs 沒有引號）
- [ ] 我執行過 week-01-calc_return.py 並看到輸出
- [ ] 我能在策略檔案與 `.env` 的 `PC_` 條目中找到數字和文字型態的參數

### 下週預告
下週要學「資料容器」— list、dict、DataFrame，這會幫助你讀懂 `df['close']` 這種寫法，
以及為什麼 `PC_2330={"strategy":"auto","alloc":20}` 這種大括號寫法叫做「字典」。
