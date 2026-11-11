"""
TW SelfSelect Python 基礎 - 第 6 週
簡化版「每月選股 → 每天檢查」流程

這個程式模擬 selfselect_trader.py 的核心循環（簡化到只剩一檔股票）：

1. 讀取 CSV 資料（模擬券商行情）
2. D1（名單日）：做最小版的選股初篩（收盤價 > 20 日均線 → 入選）
3. D2（進場日）：在 13:25–13:30 的下單窗口買進（用這檔的 alloc% 算股數）
4. 之後每個交易日 13:25 檢查策略訊號（收盤價跌破 5 日均線 → 賣出）
5. 賣掉之後名單清空 ⇒ 剩下的錢「停泊」到 0050（這裡只印訊息，不真的下單）

實盤每分鐘檢查一次、每檔股票各自一條 PC_ 設定；
這個小程式只是把同一套「選股 → 進場 → 每日判定 → 出場」的順序演給你看。
"""
import time

import pandas as pd

print("🚀 簡易 selfselect_trader 啟動（模擬模式）")
print("=" * 56)

# === 1. 讀取資料（實盤是從券商 API 取日 K） ===
df = pd.read_csv("data/prices_medium.csv")
df['MA5'] = df['close'].rolling(window=5).mean()
df['MA20'] = df['close'].rolling(window=20).mean()

# === 2. 資金設定（對照 .env：TOTAL_CAPITAL、SELFSELECT_LEG_PCT、PC_ 的 alloc） ===
capital = 500_000        # TOTAL_CAPITAL
alloc_pct = 20           # PC_2330 的 alloc = 20（%）⇒ 這檔最多用 20% 資金
stock_capital = capital * alloc_pct / 100

position = 0             # 0 = 空手, >0 = 持有股數
cost = 0.0               # 買進成本
symbol = "2330"

# === 3. D1：選股（最小版初篩，MA20 從第 20 根才有值） ===
d1 = 19
row = df.iloc[d1]
picked = row['close'] > row['MA20']
print(f"📊 D1（{row['date']}）選股初篩：收盤 {row['close']:.2f} vs MA20 {row['MA20']:.2f}"
      f" → {'✅ 入選' if picked else '❌ 不選'}")
if not picked:
    print("🅿️  本月沒有入選的股票 ⇒ 資金停泊 0050（SELFSELECT_PARK_ASSET）")
    print("🏁 模擬結束")
    raise SystemExit

# === 4. D2：13:25–13:30 的下單窗口進場 ===
d2 = d1 + 1
row = df.iloc[d2]
price = row['close']
shares = int(stock_capital // price)          # 台股以「股」為單位，程式會自己拆整股/零股
cost = shares * price
position = shares
print(f"🔔 D2（{row['date']}）13:25 買進 {symbol} {shares} 股 @ {price:.2f}（成本 NT${cost:,.0f}）")

# === 5. 之後每個交易日 13:25 檢查一次策略訊號 ===
parked = False          # 空手時資金是否已停泊到 0050
for i in range(d2 + 1, len(df)):
    row = df.iloc[i]
    close, ma5, ma20 = row['close'], row['MA5'], row['MA20']

    if position == 0:
        tag = "空手，資金停泊 0050" if parked else "空手"
        print(f"⏳ {row['date']} 13:25 檢查：收盤 {close:.2f} / MA5 {ma5:.2f} → HOLD（{tag}）")
    elif close < ma5:
        revenue = position * close
        profit = revenue - cost
        print(f"🔔 {row['date']} 13:25 賣出 {symbol} {position} 股（收盤 {close:.2f} "
              f"跌破 MA5 {ma5:.2f}） | 損益 {profit:+,.0f}")
        position = 0
        parked = True
        print("🅿️  名單已空手 ⇒ 閒置資金停泊 0050（SELFSELECT_PARK_ASSET），等下次 D1 選股")
    else:
        print(f"⏳ {row['date']} 13:25 檢查：收盤 {close:.2f} / MA5 {ma5:.2f} / "
              f"MA20 {ma20:.2f} → HOLD（持有中）")

    time.sleep(0.5)   # 實盤是每分鐘一圈；這裡放慢讓你看得清楚

print()
print("=" * 56)
print("🏁 模擬結束（實盤會在 13:45 發收盤日報＋儀表板，然後休眠到下次開盤）")
