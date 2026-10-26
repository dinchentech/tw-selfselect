"""
TW AutoTrader Python 基礎 - 第 3 週
條件判斷：if/else

這個程式會：
1. 讀取股價資料
2. 計算 5 日移動平均線
3. 用 if 判斷收盤價在均線上方還是下方
4. 印出 BUY / SELL / HOLD 訊號
"""
import pandas as pd

# === 1. 讀取資料 ===
df = pd.read_csv("data/prices_short.csv")

# === 2. 計算 5 日均線（先學著用，下週會詳細解釋） ===
df['MA5'] = df['close'].rolling(window=5).mean()

# === 3. 只看最後一根 K 線的判斷 ===
last_row = df.iloc[-1]
close_price = last_row['close']
ma5 = last_row['MA5']

print(f"日期：{last_row['date']}")
print(f"收盤價：{close_price}")
print(f"5 日均線：{ma5}")
print()

# === 4. 用 if/else 判斷訊號 ===
print("=== 訊號判斷 ===")
if close_price > ma5:
    print("👉 訊號：BUY（收盤價在均線上方，趨勢偏多）")
elif close_price < ma5:
    print("👉 訊號：SELL（收盤價在均線下方，趨勢偏空）")
else:
    print("👉 訊號：HOLD（收盤價等於均線）")

print()

# === 5. 逐根 K 線檢查 ===
print("=== 逐日檢查 ===")
for i in range(len(df)):
    row = df.iloc[i]
    if pd.isna(row['MA5']):  # 前 4 根沒有 MA5（資料不夠）
        print(f"{row['date']} | 收盤價：{row['close']} | 尚無 MA5（warm-up 中）")
        continue
    if row['close'] > row['MA5']:
        signal = "BUY"
    elif row['close'] < row['MA5']:
        signal = "SELL"
    else:
        signal = "HOLD"
    print(f"{row['date']} | 收盤價：{row['close']:>7} | MA5：{row['MA5']:>7} | {signal}")
