"""回歸測試：儀表板產生後的摘要計數（2026-10-19）。

## 事故

2026-10-19 13:26 五檔自選股全部成交（`holdings.json` 7 檔、`performance.csv` 7 筆 BUY），
但收盤時 log 印：

    ✅ dashboard.html 已產生（0 筆交易）

看起來像「今天沒成交」。原因：那行只算 `compute_pnl()` 的長度，而 `compute_pnl` 回的是
**已實現（賣出配對）** 的交易 ⇒ 沒有賣出的日子永遠是 0（買進完全不計）。
頁面本身是對的（「近 50 筆交易」含買進），只是這行訊息會誤導。
"""
import unittest

import pandas as pd

from scripts.generate_dashboard import trade_count_summary

_COLS = ["timestamp", "symbol", "signal", "price", "quantity", "action",
         "exclude_daily", "cost", "group"]


def _df(rows):
    df = pd.DataFrame(rows, columns=_COLS)
    df["timestamp"] = pd.to_datetime(df["timestamp"])   # load_trades() 實際也會轉
    return df


class TradeCountSummaryTest(unittest.TestCase):

    def test_buy_only_day_reports_buys_not_zero(self):
        """只有買進的一天：已實現 0，但買進要有數字（這就是誤導的那個 case）。"""
        df = _df([
            ["2026-10-19 13:26:05", "4938", 1, 103.0, 582, "BUY", 0, 85.0, 1],
            ["2026-10-19 13:26:17", "2603", 1, 265.0, 226, "BUY", 0, 85.0, 1],
            ["2026-10-19 13:26:45", "2347", 1, 99.9, 600, "BUY", 0, 85.0, 1],
        ])
        s = trade_count_summary(df)
        self.assertEqual(s["realized"], 0)
        self.assertEqual(s["buys"], 3)
        self.assertEqual(s["rows"], 3)

    def test_buy_then_sell_counts_both(self):
        df = _df([
            ["2026-10-19 09:00:00", "1301", 1, 79.6, 1000, "BUY", 1, 113.0, 1],
            ["2026-10-19 13:25:00", "1301", -1, 85.0, 1000, "SELL", 0, 121.0, 1],
        ])
        s = trade_count_summary(df)
        self.assertEqual(s["buys"], 1)
        self.assertEqual(s["realized"], 1)

    def test_empty_is_all_zero(self):
        self.assertEqual(trade_count_summary(pd.DataFrame()),
                         {"realized": 0, "buys": 0, "rows": 0})
        self.assertEqual(trade_count_summary(None),
                         {"realized": 0, "buys": 0, "rows": 0})


if __name__ == '__main__':
    unittest.main()
