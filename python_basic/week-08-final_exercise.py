"""
TW SelfSelect Python 基礎 - 第 8 週
整合回顧 — 期末練習

請從以下三個任務中選一個完成。
完成後執行 backtest 驗證。
"""
print("""
╔══════════════════════════════════════════════════════════╗
║  第 8 週：期末練習                                       ║
║                                                         ║
║  請從以下 3 個任務中選 1 個，用 DSH 完成。               ║
╚══════════════════════════════════════════════════════════╝

⚠️ 指令都在專案根目錄執行；只有最終要把參數寫進實盤時才改 .env。

【任務 A】調整 Bollinger 策略參數
  目標：讓 Bollinger 策略在台積電（2330）上的表現更好。
  
  步驟：
  1. 對 DSH 說：
     「幫我比較 bollinger 策略用 window=15, 20, 25
      三種參數的回測結果，只回測 2330」
  2. 選最好的 window，再比較 std_dev=1.8, 2.0, 2.2
  3. 把最後選定的參數寫進 .env 的 PC_ 條目（使用手冊 §4「策略選擇」）：
     PC_2330={"strategy":"bollinger","alloc":20,"window":20,"std_dev":2.0}
  4. 執行驗證：
     .venv/bin/python backtest.py --strategy bollinger --std_dev 2.0 --symbol 2330

【任務 B】調整 MA Cross 策略參數
  目標：讓 MA Cross 在 0050 上的勝率 > 55%。
  
  步驟：
  1. 對 DSH 說：
     「幫我比較 ma_cross 策略用 fast=5, 9, 12
      slow=20, 21, 26 的各種組合，只回測 0050」
  2. 選出勝率最高的組合
  3. 執行驗證：
     .venv/bin/python backtest.py --strategy ma_cross --fast_period X --slow_period Y --symbol 0050

【任務 C】調整 Breakout 策略參數
  目標：讓 Breakout 在廣達（2382）上的交易次數適中（10~20 次）。
  
  步驟：
  1. 對 DSH 說：
     「幫我比較 breakout 策略用 lookback=15, 20, 30
      三種參數的回測結果，只回測 2382」
  2. 選交易次數接近 15 次的那組
  3. 執行驗證：
     .venv/bin/python backtest.py --strategy breakout --lookback X --symbol 2382

=== 完成後 ===
請在下方寫下你的結果：
  選擇的任務：_____
  選定的參數：_____
  回測結果（勝率/報酬）：_____
  我改的是 .env 還是程式碼？（提示：改程式碼要升 APP_VERSION）_____
  學到的一件事：_____
""")
