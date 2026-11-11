# 第 3 週：條件判斷 — if/else 與比較運算

## 本週目標
> 能讀懂策略程式碼中的 `(df['close'] < df['BB_Lower']) & (df['RSI'] < rsi_low)`，理解條件判斷就是「如果⋯就⋯」的邏輯。

## 本專案對應檔案
- `strategies/bollinger.py` 第 27~31 行：買賣條件的完整判斷（`buy_condition` / `sell_condition`，然後 `df.loc[..., 'signal'] = 1 / -1`）
- `strategies/breakout.py` 第 29~31 行：突破條件的判斷（`buy_condition`／`sell_condition`，含 ATR 波動度過濾）
- `strategies/ma_cross.py` 第 35 行：黃金交叉是「三個條件同時成立」的範例
- `user_strategies.py`：自訂策略範本（`g1_strategy_2` 週 KD 黃金交叉等），買賣條件寫法也一樣
  （`strategies/kd.py`、`strategies/macd.py` 只是工具函式，**沒有**接進實盤策略清單）

## 核心觀念
1. **if / elif / else**：如果（if）條件成立做 A，否則如果（elif）做 B，再否則（else）做 C。
2. **比較運算子**：`>`（大於）、`<`（小於）、`>=`（大於等於）、`<=`（小於等於）、`==`（等於）、`!=`（不等於）。
3. **and（且）**：兩個條件都要成立，整題才成立。在 pandas 裡寫成 `&`，每個小條件要用括號包起來。
4. **or（或）**：兩個條件只要一個成立，整題就成立。在 pandas 裡寫成 `|`。
5. **這些就是策略的核心**：策略最後不是吐 `1`（買）、`-1`（賣）、`0`（不動），就是交給主程式用同樣的條件決定要不要下單。

## 小程式說明
`week-03-simple_signal.py` 會讀取股價資料，計算 5 日均線，然後判斷：收盤價在均線上方 → 印 BUY，在均線下方 → 印 SELL，否則 → 印 HOLD。

實盤主程式 `selfselect_trader.py` 也是這樣跑：每檔股票算出策略訊號（第 849 行
`signal = strat_func(acd, **strat_params)['signal'].iloc[-1]`），再看 `signal == 1` 還是 `-1` 決定買賣。

## 本週練習
1. 打開 `strategies/bollinger.py`，找出第 27 行的 `buy_condition`，寫下它有幾個條件、用什麼連接（`&` / `|`）
2. 打開 `strategies/breakout.py`，第 29 行（`buy_condition`），找出突破買進的條件（提示：除了突破，還要求 ATR 夠大）
3. 打開 `strategies/ma_cross.py` 第 35 行，寫下黃金交叉的三個條件分別是什麼
4. 回答：如果 `close=150`、`BB_Lower=148`、`RSI=25`（且 `rsi_low=30`），買進條件會成立嗎？

## 學完自評清單
- [ ] 我知道 `if` 後面接的是「條件」，條件成立才會執行下面的程式碼
- [ ] 我知道 `&` 和 `|` 的差別（以及每個小條件要加括號）
- [ ] 我能在策略檔案中指出買進條件是哪幾行程式碼
- [ ] 我執行過 week-03-simple_signal.py 並看到 BUY/SELL/HOLD 輸出

## 下週預告
下週要學移動平均與 rolling window，理解 `rolling(window=20).mean()` 為什麼需要夠多資料才能用。
