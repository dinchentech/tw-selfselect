"""
TW SelfSelect Python 基礎 - 第 5 週
用 DSH 改策略參數 + 跑回測

這個程式是「練習引導」，不是你要執行的主程式。
請照著下面的指示，用 DSH 修改參數，再用專案根目錄的 backtest.py 驗證。

=== 練 習 開 始 ===
"""
print("""
╔══════════════════════════════════════════════════════╗
║  第 5 週練習：用 DSH 改參數 + 跑回測                  ║
║                                                     ║
║  指令都在專案根目錄執行（不是 python_basic/ 底下）     ║
╚══════════════════════════════════════════════════════╝

【練習 1】改 Bollinger 的標準差倍數
    → 對 DSH 說：「把 .env 的 PC_2330 改成
       strategy=bollinger、alloc=20、window=20、std_dev=2.5」
    → 然後在專案根目錄執行：
       .venv/bin/python backtest.py --strategy bollinger --std_dev 2.5 --symbol 2330
    → 觀察交易次數與勝率有沒有變化

【練習 2】改 MA Cross 的均線週期
    → 對 DSH 說：「跑回測時用 --fast_period 12 --slow_period 26」
    → 然後執行：
       .venv/bin/python backtest.py --strategy ma_cross --fast_period 12 --slow_period 26 --symbol 2330
    → 比較和預設 (9,21) 哪個勝率高

【練習 3】改 Breakout 的 lookback
    → 執行：
       .venv/bin/python backtest.py --strategy breakout --lookback 15 --symbol 2330
    → 再執行：
       .venv/bin/python backtest.py --strategy breakout --lookback 30 --symbol 2330
    → 哪個交易次數比較多？為什麼？

【練習 4】改 VWAP 的 sigma_mult
    → 執行：
       .venv/bin/python backtest.py --strategy vwap --sigma_mult 1.2 --symbol 2330
    → 再執行：
       .venv/bin/python backtest.py --strategy vwap --sigma_mult 2.0 --symbol 2330
    → sigma 調大，交易次數變多還是變少？

💡 提示：
- 交易次數變多不一定比較好（手續費、證交稅會吃掉獲利）
- 參數的最佳值會因為股票不同而不同
- 這就是為什麼需要回測來驗證！
- 改 `.env` 的 PC_ 條目只影響那一檔、不用重新部署；
  改策略檔的預設值算「程式修改」，要把 core/version.py 的 APP_VERSION +1，
  並由你本人手動執行 ./deploy_source.sh 才會生效。
""")
