# 第 5 週：四大固定策略拆解

### 本週目標
> 能打開四支策略檔案，指出買進條件在哪一行、賣出條件在哪一行，並知道每個參數在做什麼。

### 本專案對應檔案
- `strategies/vwap_deviation.py`（全 29 行）
- `strategies/bollinger.py`（全 32 行）
- `strategies/ma_cross.py`（全 45 行）
- `strategies/breakout.py`（全 33 行）
- `策略說明.md` §5.1–§5.4（第 398／473／542／615 行起）：每支策略的設計理由、參數意義與回測數字

### 核心觀念
1. **每支策略的結構都一樣**：先複製資料 → 計算技術指標 → 設定買進條件 → 設定賣出條件 → 回傳（回傳的 DataFrame 多一欄 `signal`：`1`=買、`-1`=賣、`0`=不動）。
2. **四個策略可以分兩組**：
   - **逆勢組**（Bollinger、VWAP）：跌深了買、漲多了賣，賺回歸均值。
   - **順勢組**（MA Cross、Breakout）：突破壓力買、跌破支撐賣，賺趨勢延續。
3. **本專案多兩條路**：`strategy` 填 `auto` 時 `strategies/auto_sensing.py` 依目前的型態自動挑上面四支之一（`策略說明.md` §6，買入當下鎖定、持有期間不換）；填 `keep_wait` 時走 `strategies/keep_wait.py`（人工管理的低接加碼，§9）。你調四支策略的參數，等於也在影響 `auto` 路由到它們時的行為。
4. **參數就是調整敏感度的旋鈕**：`std_dev=2.0` 調成 `2.5`，通道變寬，訊號變少但更準。參數有**兩個**可以改的地方：
   - 策略檔的預設值（`def bollinger_reverse_strategy(..., std_dev=2.0)`）
   - `.env` 的 `PC_<代號>` 條目（例如 `PC_2454={"strategy":"bollinger","alloc":10,"window":20,"std_dev":2.5}`；哪些參數名可寫，見 `core/config_loader.py` 第 12 行 `STRATEGY_PARAM_KEYS`）
5. **回測是你最好的朋友**：不確定哪組參數好？跑一次 `backtest.py` 就知道了。
   它是**簡化口徑**：買進訊號只算「下一根 K 的漲跌幅」、賣出訊號算 0（見 `backtest.py` 第 200 行
   `calculate_performance()`），不是完整持倉模擬，資料由 Yahoo Finance 下載（要連網）。
   想看每月換股的**完整投組**績效，請看 `策略說明.md` 附錄 K 的數字或 `scripts/backtest_plan2_monthly_3group.py`。

### 本週練習（核心！）
**這週的練習直接在專案上做，不再是玩小程式。**

1. 依序打開四支策略檔案，各回答三個問題：
   - 哪一行是買進條件？
   - 哪一行是賣出條件？
   - 這個策略有幾個參數？
2. 進入 `python_basic/` 目錄，執行 `python week-05-tweak_params.py`，它會示範如何用 DSH 改參數並用回測驗證。
3. 回到專案根目錄跑一次對照：
   ```bash
   .venv/bin/python backtest.py --strategy bollinger --std_dev 2.0 --symbol 2330
   .venv/bin/python backtest.py --strategy bollinger --std_dev 2.5 --symbol 2330
   ```
   比較交易次數與勝率。
4. 打開 `策略說明.md` §5.1，找出布林策略那節對 `std_dev` 的說明，看看跟你剛才觀察到的是否一致。

### 學完自評清單
- [ ] 我能在 `vwap_deviation.py` 中找出買進條件（第 26 行）
- [ ] 我能在 `ma_cross.py` 中找出黃金交叉的條件（第 36 行）
- [ ] 我能在 `bollinger.py` 中找出布林下軌的計算（第 16 行）
- [ ] 我能在 `breakout.py` 中找出 ATR 波動度過濾（第 27 行）
- [ ] 我知道策略參數可以寫在 `.env` 的 `PC_` 條目，且參數名必須列在 `core/config_loader.py` 的 `STRATEGY_PARAM_KEYS`
- [ ] 我跑過 `python backtest.py --strategy bollinger --std_dev 2.5` 並看到不同結果

### 下週預告
下週要看 `selfselect_trader.py` — 每月選股、每天下單的「心臟」是怎麼跳動的。
