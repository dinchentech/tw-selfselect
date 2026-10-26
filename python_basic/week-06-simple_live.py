"""
TW AutoTrader Python 基礎 - 第 6 週
簡化版監控迴圈

這個程式模擬 live_trader 的行為：
1. 讀取 CSV 資料（模擬 broker API）
2. 計算 5 日均線（當作策略）
3. 用 while 迴圈逐根 K 線檢查
4. 有訊號就印通知
5. 每 5 秒檢查下一根（實盤是每 60 秒）
"""
import pandas as pd
import time

print("🚀 簡易 live_trader 啟動（模擬模式）")
print("=" * 50)

# === 1. 讀取資料（模擬從券商 API 取得） ===
df = pd.read_csv("data/prices_short.csv")
df['MA5'] = df['close'].rolling(window=5).mean()

# === 2. 設定參數 ===
position = 0  # 0 = 空手, 1 = 持有中
capital = 100000  # 模擬資金 10 萬元

# === 3. 從第 5 根開始（warm-up 完畢後） ===
for i in range(4, len(df)):
    row = df.iloc[i]
    close = row['close']
    ma5 = row['MA5']
    
    # === 4. 策略判斷 ===
    signal = 0
    if close > ma5 and position == 0:
        signal = 1  # 突破均線，買進
    elif close < ma5 and position == 1:
        signal = -1  # 跌破均線，賣出
    
    # === 5. 執行 ===
    if signal == 1:
        shares = int(capital * 0.5 / close)  # 用 50% 資金買
        cost = shares * close
        position = 1
        print(f"🔔 BUY  {row['date']} | 價格: {close:.2f} | 股數: {shares} | 成本: {cost:.0f}")
    elif signal == -1:
        revenue = shares * close
        profit = revenue - cost
        position = 0
        print(f"🔔 SELL {row['date']} | 價格: {close:.2f} | 收入: {revenue:.0f} | 損益: {profit:+.0f}")
    else:
        print(f"⏳ HOLD {row['date']} | 價格: {close:.2f} | MA5: {ma5:.2f} | 持有中" if position else f"⏳ HOLD {row['date']} | 價格: {close:.2f} | MA5: {ma5:.2f} | 空手")
    
    # 暫停，模擬等待下一次檢查
    time.sleep(5)

print()
print("=" * 50)
print("🏁 模擬結束")
