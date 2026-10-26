"""
TW AutoTrader Python 基礎 - 第 1 週
認識變數、數字、文字

這個程式會：
1. 讀取股價 CSV 檔案
2. 取出第一天的收盤價和最後一天的收盤價
3. 計算這段期間的報酬率
"""
import pandas as pd

# === 1. 從 CSV 讀取股價資料 ===
df = pd.read_csv("data/prices_short.csv")

# === 2. 取出我們需要的數字 ===
first_close = df['close'].iloc[0]    # 第一天的收盤價（數字）
last_close = df['close'].iloc[-1]     # 最後一天的收盤價（數字）
stock_name = "範例股票"               # 文字型態

# === 3. 計算報酬率 ===
# 公式：(最後價格 - 最初價格) / 最初價格
return_rate = (last_close - first_close) / first_close

# === 4. 印出結果 ===
print(f"股票名稱：{stock_name}")
print(f"第一天收盤價：{first_close}")
print(f"最後一天收盤價：{last_close}")
print(f"總報酬率：{return_rate:.2%}")

# === 5. 本週練習解答 ===
print()
print("--- 本週練習 ---")
print("sigma_mult 的型態：", type(1.5))      # 應該是 <class 'float'>
print('"vwap" 的型態：', type("vwap"))        # 應該是 <class 'str'>
