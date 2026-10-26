"""
TW AutoTrader Python 基礎 - 第 4 週
移動平均與 rolling window

這個程式會：
1. 用手算 3 日移動平均，對比 pandas rolling 的結果
2. 觀察前 N-1 個值為 NaN（warm-up）
3. 比較不同 window 大小的差異
"""
import pandas as pd

# === 1. 讀取資料 ===
df = pd.read_csv("data/prices_short.csv")
prices = df['close'].values

print("=== 原始收盤價 ===")
for i, p in enumerate(prices):
    print(f"  第 {i+1:2d} 根：{p}")
print()

# === 2. 用手算 3 日移動平均 ===
print("=== 手算 3 日移動平均 ===")
manual_ma3 = []
for i in range(len(prices)):
    if i < 2:  # 前 2 根不夠 3 天的資料
        manual_ma3.append(None)
        print(f"  第 {i+1} 根：資料不足，無法計算")
    else:
        avg = (prices[i-2] + prices[i-1] + prices[i]) / 3
        manual_ma3.append(round(avg, 2))
        print(f"  第 {i+1} 根：( {prices[i-2]} + {prices[i-1]} + {prices[i]} ) / 3 = {avg:.2f}")

print()

# === 3. 用 pandas rolling 算 ===
print("=== pandas 3 日移動平均 ===")
df['MA3'] = df['close'].rolling(window=3).mean()
for i in range(len(df)):
    val = df['MA3'].iloc[i]
    if pd.isna(val):
        print(f"  第 {i+1} 根：NaN（warm-up 中）")
    else:
        print(f"  第 {i+1} 根：{val:.2f}")

print()
print(f"✅ 手算結果與 pandas 一致：{manual_ma3[2:] == [round(v,2) for v in df['MA3'].iloc[2:] if not pd.isna(v)]}")

# === 4. 比較不同 window 大小 ===
print()
print("=== 不同 window 的 warm-up 差異 ===")
for w in [3, 5, 10, 20]:
    col_name = f'MA{w}'
    df[col_name] = df['close'].rolling(window=w).mean()
    first_valid = df[col_name].first_valid_index()
    na_count = df[col_name].isna().sum()
    print(f"  window={w:2d}：前 {na_count} 根為 NaN，第 {first_valid+1} 根開始有效")
