"""
TW AutoTrader Python 基礎 - 第 5 週
用 DSH 改策略參數

這個程式是「練習引導」，不是你要執行的主程式。
請照著下面的指示，用 DSH 修改原專案的 backtest.py 並執行回測。

=== 練 習 開 始 ===
"""
print("""
╔══════════════════════════════════════════════════════╗
║  第 5 週練習：用 DSH 改參數 + 跑回測          ║
║                                                     ║
║  請打開 DSH，輸入以下指令：                    ║
╚══════════════════════════════════════════════════════╝

【練習 1】改 Bollinger 的標準差倍數
    → 對 DSH 說：「把 backtest.py 的 bollinger 策略
       std_dev 預設值從 2.0 改成 2.5」
    → 然後執行：
       python backtest.py --strategy bollinger
    → 觀察報酬率有沒有變化

【練習 2】改 MA Cross 的均線週期
    → 對 DSH 說：「跑回測時用 --fast_period 12
       --slow_period 26」
    → 然後執行：
       python backtest.py --strategy ma_cross --fast_period 12 --slow_period 26
    → 比較和預設 (9,21) 哪個勝率高

【練習 3】改 Breakout 的 lookback
    → 執行：
       python backtest.py --strategy breakout --lookback 15
    → 再執行：
       python backtest.py --strategy breakout --lookback 30
    → 哪個交易次數比較多？為什麼？

【練習 4】改 VWAP 的 sigma_mult
    → 執行：
       python backtest.py --strategy vwap --sigma_mult 1.2
    → 再執行：
       python backtest.py --strategy vwap --sigma_mult 2.0
    → sigma 調大，交易次數變多還是變少？

💡 提示：
- 交易次數變多不一定比較好（手續費會吃掉獲利）
- 參數的最佳值會因為股票不同而不同
- 這就是為什麼需要回測來驗證！
""")
