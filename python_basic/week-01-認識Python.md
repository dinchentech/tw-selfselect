# 第 1 週：認識 Python — 變數、數字、文字

### 本週目標
> 能讀懂策略檔案裡的 `= 1.5`、`= "vwap"` 這種寫法，知道數字和文字的差別。

### 原專案對應檔案
- `strategies/vwap_deviation.py` 第 13~14 行：`df['VWAP'] = df['close']` 和 `sigma_mult=1.5`
- `backtest.py` 第 21 行：`"params": {"sigma_mult": 1.5, "rsi_period": 5}`

### 核心觀念（5 點）
1. **變數（Variable）**：就是用一個名字來裝資料。像是「股價 = 150」，以後用「股價」這個名字就能拿到 150。
2. **數字型態**：Python 有整數（int）如 `5`、小數（float）如 `1.5`。策略參數兩者都有。
3. **文字型態（string）**：用引號包起來的，如 `"vwap"`。策略名稱就是文字。
4. **print()**：把東西印出來給你看，是程式除錯最重要的工具。
5. **加減乘除**：`+ - * /`，報酬率計算就是 `(賣價 - 買價) / 買價`。

### 小程式說明
`week-01-calc_return.py` 會讀取 `data/prices_short.csv`，用最後一天的收盤價減去第一天的收盤價，除以第一天的收盤價，算出這段期間的報酬率。

### 本週練習
1. 打開 `strategies/vwap_deviation.py`，找出第 11 行的函式定義，找到 `sigma_mult=1.5` 和 `rsi_period=5`
2. 打開 `backtest.py`，找出第 21 行的 `"sigma_mult": 1.5`
3. 回答：`1.5` 是數字還是文字？`"vwap"` 呢？

### 學完自評清單
- [ ] 我知道 `= 1.5` 是把 1.5 這個數字存進一個名字裡
- [ ] 我知道 `"vwap"` 和 `vwap` 的差別（引號 vs 沒有引號）
- [ ] 我執行過 week-01-calc_return.py 並看到輸出
- [ ] 我能在策略檔案中找到數字和文字型態的參數

### 下週預告
下週要學「資料容器」— list、dict、DataFrame，這會幫助你讀懂 `df['close']` 這種寫法。
