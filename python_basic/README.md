# TW SelfSelect Python 基礎課程

> 給非資訊科系、沒寫過程式的人設計。
> 8 週 × 每週 1 小時，就能讀懂策略程式碼，並用 AI（DSH）修改參數。

## 課程目標

完成這 8 週後，你將能夠：

1. 打開 `strategies/` 底下的四支固定策略檔案，指出買進條件和賣出條件在哪一行
2. 知道 `sigma_mult=1.5`、`rolling(window=20)` 這些參數在做什麼
3. 用 DSH 修改策略參數（策略檔的預設值，或 `.env` 裡 `PC_<代號>` 條目的 JSON 參數）
4. 跑 `backtest.py` 驗證修改後的績效
5. 理解 `selfselect_trader.py` 的運作流程（每月 D1 選股 → D2 收盤前進場 → 每天 13:25–13:30 依訊號進出）

## 課程大綱

| 週次 | 主題 | 小程式 | 對應本專案檔案 |
|------|------|--------|----------------|
| 第 1 週 | 認識 Python：變數、數字、文字 | week-01-calc_return.py | `strategies/vwap_deviation.py`、`backtest.py` 的策略參數 |
| 第 2 週 | 資料容器：list、dict、DataFrame | week-02-build_dataframe.py | `strategies/*.py` 的 `df['close']`、`backtest.py` 的 `STRATEGY_CONFIG` |
| 第 3 週 | 條件判斷：if/else、比較運算 | week-03-simple_signal.py | 四支策略的買賣條件 |
| 第 4 週 | 移動平均與 rolling window | week-04-rolling_demo.py | 四支策略檔內所有 `rolling(...)` 使用處 |
| 第 5 週 | 四大固定策略完整拆解 | week-05-tweak_params.py | `strategies/` 四支策略 + `策略說明.md` §5.1–§5.4 |
| 第 6 週 | 自選股主程式流程 | week-06-simple_live.py | `selfselect_trader.py`、`core/selfselect_scheduler.py` |
| 第 7 週 | 用 AI（DSH）改程式 | week-07-dsh_practice.py | 套用 prompt 模板 |
| 第 8 週 | 整合回顧 + 期末練習 | week-08-final_exercise.py | 自選策略 |

> 四支「固定策略」只是本專案策略的一部分：`strategy` 填 `auto` 時由 `strategies/auto_sensing.py`
> 在順勢／逆勢之間自動路由，`strategy` 填 `keep_wait` 時由 `strategies/keep_wait.py` 做人工管理的
> 低接加碼（見 `策略說明.md` §6、§9）。第 5 週會一起說明。

## 如何使用

```bash
# 1. 進入課程目錄
cd python_basic

# 2. 按週次順序閱讀 .md 檔案
# 3. 執行同週的 .py 小程式（建議用專案既有的 .venv，裡面才有 pandas）
../.venv/bin/python week-01-calc_return.py
#   或先啟用虛擬環境：source ../.venv/bin/activate && python week-01-calc_return.py

# 4. 完成每週練習和自評清單
```

課程用的小程式都放在 `python_basic/` 底下，只讀 `python_basic/data/` 的範例 CSV，
**不會碰到實盤的 `cache/`、`logs/`、`.env`**；要回測真的股票時才回到專案根目錄跑 `backtest.py`。

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

要跑專案根目錄的 `backtest.py` 還需要 `requirements.txt` 裡的套件（yfinance、python-dotenv 等），
建議直接使用專案既有的 `.venv`；它會用 Yahoo Finance 下載歷史資料，所以要連網。
不指定 `--symbol` 時會回測 `config/symbols.py` 裡的全部標的（很慢），練習時請一律加 `--symbol 2330` 之類的參數：

```bash
cd ..                      # 回到專案根目錄
.venv/bin/python backtest.py --strategy bollinger --symbol 2330
```

## 參考文件

| 文件 | 什麼時候看 |
|------|-----------|
| `策略說明.md` | 想懂「這個策略為什麼這樣設計、參數怎麼影響結果」（§5 四大固定策略、§6 型態感知、§9 keep_wait） |
| `使用手冊.md` | 想懂 `.env` 每個設定、每月作業 SOP、真錢上線檢查清單（§4 參數速查、§5 每天會發生什麼） |
| `README.md`（根目錄） | 專案全貌與最高原則 |

## 給學習者的話

> **你不必學會寫程式，你只需要學會「跟程式溝通」。**
>
> 這 8 週不會教你成為工程師，而是教你：
> 1. 策略程式碼的結構長什麼樣子
> 2. 參數在哪裡調
> 3. 有問題時怎麼問 AI
>
> 這些技能就足夠你開始自己調整 SelfSelect 了。
> 剩下的，DSH（AI）會幫你補上。

> ⚠️ 本專案的硬規則：**只有程式碼真的被改動時**才把 `core/version.py` 的 `APP_VERSION` +1；
> 部署一律由你本人手動執行 `./deploy_source.sh`，AI 不會代跑。
