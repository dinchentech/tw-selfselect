# 第 7 週：用 AI（DSH）改程式 — 實戰心法

## 本週目標
> 學會跟 DSH 對話的五種實用 prompt 模板，並能驗證 AI 的答案是否正確。

## 原專案對應檔案
- 你自己選一支策略 + backtest.py

## 核心觀念
1. **DSH 就是你隨call隨到的工程師**：你不會寫程式沒關係，會描述需求就好。
2. **好 prompt 的公式**：在哪個檔案 + 要改什麼 + 改成什麼值 + 預期結果。
3. **要驗證 AI 的答案**：AI 可能講錯。每次改完一定要跑 `python backtest.py --strategy xxx` 確認。
4. **五個永遠有用的 prompt 模板**（見下面）。

## 五個 prompt 模板（直接複製貼上給 DSH）

**模板 1：改參數**
```
在 strategies/bollinger.py 中，把 std_dev 的預設值從 2.0 改成 2.5
```

**模板 2：問邏輯**
```
在 strategies/ma_cross.py 中，第 22 行到第 24 行在做什麼？用白話解釋。
```

**模板 3：加過濾條件**
```
在 strategies/breakout.py 中，在 buy_condition 加上成交量比 5 日均量大 1.5 倍的條件。
成交量欄位是 df['volume']，5 日均量是 df['volume'].rolling(window=5).mean()。
```

**模板 4：比較差異**
```
用 backtest.py 跑 bollinger 策略，std_dev 分別用 1.5、2.0、2.5，比較勝率和交易次數。
```

**模板 5：解釋錯誤**
```
執行 python backtest.py 時出現 [貼上錯誤訊息]，原因是什麼？怎麼修？
```

## 小程式說明
`week-07-dsh_practice.py` 包含 4 個練習題目。請照指示操作。

## 本週練習
1. 用模板 2 問 DSH bollinger.py 的 buy_condition 在做什麼
2. 用模板 3 請 DSH 幫 breakout.py 加上成交量過濾
3. 用模板 4 請 DSH 比較不同參數的回測結果
4. **最重要**：每次 AI 改完，一定自己跑一次 backtest 確認

## 學完自評清單
- [ ] 我知道好 prompt 的公式：檔案 + 改什麼 + 改成什麼 + 預期結果
- [ ] 我能直接複製模板給 DSH 用
- [ ] 每次 AI 改完程式，我一定會跑一次 backtest 驗證
- [ ] AI 給的答案太複雜時，我知道可以請它「用白話解釋」

## 下週預告
最後一週！會把所有學到的東西整合起來，做一個完整的修改 → 回測 → 驗證循環。
