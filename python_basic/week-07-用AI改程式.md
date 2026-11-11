# 第 7 週：用 AI（DSH）改程式 — 實戰心法

## 本週目標
> 學會跟 DSH 對話的五種實用 prompt 模板，並能驗證 AI 的答案是否正確。

## 本專案對應檔案
- 你自己選一支策略（`strategies/bollinger.py`、`strategies/ma_cross.py`、`strategies/breakout.py`、`strategies/vwap_deviation.py`）+ `backtest.py`
- 想改「這檔股票用什麼策略、參數多少」時，改的是 `.env` 的 `PC_<代號>` 條目（說明見 `使用手冊.md` §4「策略選擇」）

## 核心觀念
1. **DSH 就是你隨 call 隨到的工程師**：你不會寫程式沒關係，會描述需求就好。
2. **好 prompt 的公式**：在哪個檔案（或 `.env` 哪一條）+ 要改什麼 + 改成什麼值 + 預期結果。
3. **要驗證 AI 的答案**：AI 可能講錯。每次改完一定要跑 `python backtest.py --strategy xxx` 確認。
4. **兩個改參數的地方，先想清楚改哪個**：
   - `.env` 的 `PC_<代號>` → **只影響那一檔股票**、不用動程式、不用重新部署（`.env` 改了主程式會立刻套用）。**推薦先用這個。**
   - 策略檔的預設值 → 會影響所有沒寫參數的股票，屬於「程式修改」，依本專案硬規則要把 `core/version.py` 的 `APP_VERSION` +1，並由你本人手動執行 `./deploy_source.sh` 部署。

## 五個 prompt 模板（直接複製貼上給 DSH）

**模板 1：改參數（推薦走 `.env`）**
```
在 .env 的 PC_2330 那條加上布林通道參數：strategy 保持 bollinger、alloc 20、
window=20、std_dev=2.5。改完告訴我怎麼驗證。
```
（`PC_` 條目可寫哪些參數名，見 `core/config_loader.py` 第 12 行 `STRATEGY_PARAM_KEYS`）

**模板 2：問邏輯**
```
在 strategies/bollinger.py 中，第 25 行到第 31 行在做什麼？用白話解釋，不要用術語。
```

**模板 3：加過濾條件**
```
在 strategies/breakout.py 中，在 buy_condition（第 27 行）加上條件：
今日成交量要大於 5 日平均成交量的 1.5 倍。
成交量欄位是 df['volume']，5 日均量用 df['volume'].rolling(window=5).mean() 計算。
```

**模板 4：比較差異**
```
用 backtest.py 跑 bollinger 策略、只回測 2330，
std_dev 分別用 1.5、2.0、2.5，比較交易次數、勝率、總報酬。
```

**模板 5：解釋錯誤**
```
執行 python backtest.py --strategy bollinger 時出現 [貼上錯誤訊息]，原因是什麼？怎麼修？
```

## 小程式說明
`week-07-dsh_practice.py` 包含 4 個練習題目。請照指示操作。

## 本週練習
1. 用模板 2 問 DSH `strategies/bollinger.py` 第 25~31 行在做什麼
2. 用模板 3 請 DSH 幫 `strategies/breakout.py` 加上成交量過濾
3. 用模板 4 請 DSH 比較不同參數的回測結果（記得指定 `--symbol`，否則會回測 `config/symbols.py` 裡的全部標的，跑很久）
4. **最重要**：每次 AI 改完，一定自己跑一次 backtest 確認
5. 回答：如果只是要改某一檔的參數，你會改 `.env` 還是改策略檔？為什麼？

## 學完自評清單
- [ ] 我知道好 prompt 的公式：檔案 + 改什麼 + 改成什麼 + 預期結果
- [ ] 我能直接複製模板給 DSH 用
- [ ] 我知道「改 `.env` 參數」和「改程式碼」的差別（後者要升 `APP_VERSION`、要自己部署）
- [ ] 每次 AI 改完程式，我一定會跑一次 backtest 驗證
- [ ] AI 給的答案太複雜時，我知道可以請它「用白話解釋」

## 下週預告
最後一週！會把所有學到的東西整合起來，做一個完整的修改 → 回測 → 驗證循環。
