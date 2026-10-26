"""
TW AutoTrader Python 基礎 - 第 2 週
資料容器：list、dict、DataFrame

這個程式會：
1. 用 list 和 dict 示範基本資料容器
2. 用 pandas 讀 CSV → 變成 DataFrame
3. 計算每一根 K 線的漲跌
"""
import pandas as pd

# === 1. list（列表）是什麼？ ===
print("=== list 範例 ===")
prices = [150.0, 152.5, 153.5, 154.0, 155.5]
print(f"價格列表：{prices}")
print(f"第 1 個價格（索引 0）：{prices[0]}")
print(f"第 3 個價格（索引 2）：{prices[2]}")
print()

# === 2. dict（字典）是什麼？ ===
print("=== dict 範例 ===")
strategy_params = {
    "name": "ma_cross",
    "fast_period": 9,
    "slow_period": 21
}
print(f"策略參數字典型：{strategy_params}")
print(f"策略名稱：{strategy_params['name']}")
print(f"快線週期：{strategy_params['fast_period']}")
print()

# === 3. DataFrame 是什麼？ ===
print("=== DataFrame 範例 ===")
df = pd.read_csv("data/prices_short.csv")

# 看看前 5 列
print("前 5 列資料：")
print(df.head())
print()

# 看看欄位名稱
print(f"欄位名稱：{list(df.columns)}")
print()

# === 4. 計算漲跌 ===
print("=== 每日漲跌計算 ===")
df['prev_close'] = df['close'].shift(1)      # 前一日的收盤價
df['change'] = df['close'] - df['prev_close'] # 漲跌金額
df['change_pct'] = df['change'] / df['prev_close']  # 漲跌幅

# 印出日期、收盤價、漲跌幅
result = df[['date', 'close', 'change', 'change_pct']]
print(result.to_string(index=False))
