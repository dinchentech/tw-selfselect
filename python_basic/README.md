# TW AutoTrader Python 基礎課程

> 給非資訊科系、沒寫過程式的人設計。
> 8 週 × 每週 1 小時，就能讀懂策略程式碼，並用 AI（DSH）修改參數。

## 課程目標

完成這 8 週後，你將能夠：

1. 打開 `strategies/` 底下的四支策略檔案，指出買進條件和賣出條件在哪一行
2. 知道 `sigma_mult=1.5`、`rolling(window=20)` 這些參數在做什麼
3. 用 DSH 修改策略參數
4. 跑 `backtest.py` 驗證修改後的績效
5. 理解 live_trader 的運作流程

## 課程大綱

| 週次 | 主題 | 小程式 | 對應原專案 |
|------|------|--------|-----------|
| 第 1 週 | 認識 Python：變數、數字、文字 | calc_return.py | 策略中的參數設定 |
| 第 2 週 | 資料容器：list、dict、DataFrame | build_dataframe.py | df['close'] 讀取股價 |
| 第 3 週 | 條件判斷：if/else、比較運算 | simple_signal.py | 策略中的買賣條件 |
| 第 4 週 | 移動平均與 rolling window | rolling_demo.py | 所有 rolling() 使用處 |
| 第 5 週 | 四大策略完整拆解 | tweak_params.py | 四支策略 .py 檔案 |
| 第 6 週 | live_trader 流程 | simple_live.py | live_trader_finmind.py |
| 第 7 週 | 用 AI（DSH）改程式 | dsh_practice.py | 套用 prompt 模板 |
| 第 8 週 | 整合回顧 + 期末練習 | final_exercise.py | 自選策略 |

## 如何使用

```bash
# 1. 進入課程目錄
cd python_basic

# 2. 按週次順序閱讀 .md 檔案
# 3. 執行同週的 .py 小程式
python week-01-calc_return.py

# 4. 完成每週練習和自評清單
```

## 測試資料

`data/` 目錄下有兩組測試用股價 CSV：

| 檔案 | 筆數 | 用途 |
|------|------|------|
| prices_short.csv | 20 根 K 線 | 第 1~4 週基礎練習 |
| prices_medium.csv | 60 根 K 線 | 第 5~6 週進階練習 |

## 環境需求

```bash
pip install pandas
```

## 給學習者的話

> **你不必學會寫程式，你只需要學會「跟程式溝通」。**
>
> 這 8 週不會教你成為工程師，而是教你：
> 1. 策略程式碼的結構長什麼樣子
> 2. 參數在哪裡調
> 3. 有問題時怎麼問 AI
>
> 這些技能就足夠你開始自己調整 AutoTrader 了。
> 剩下的，DSH（AI）會幫你補上。
