"""回歸測試：睡前/啟動持倉報告的參考市價必須反映真實收盤價。

背景：_build_holdings_message 以 performance.csv 最後一筆成交價當市價，
未平倉部位的最後一筆成交就是買進 → 參考市價永遠 = 成本均價、未實現損益 +0。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestHoldingsMessagePrices(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        logs = Path("logs")
        logs.mkdir()
        (logs / "holdings.json").write_text(
            json.dumps({"2357": 93}), encoding="utf-8")
        (logs / "stock_allocation.json").write_text(
            json.dumps({"2357": {"total_buy_cost": 798 * 93,
                                 "total_buy_shares": 93}}), encoding="utf-8")
        pd.DataFrame([
            {"timestamp": "2026-08-03 09:00:00", "symbol": "2357",
             "signal": "BUY", "price": 798.0, "quantity": 93, "action": "BUY"},
        ]).to_csv(logs / "performance.csv", index=False)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _fake_twse(self, stock_id, start, end):
        return pd.DataFrame([
            {"date": pd.Timestamp("2026-08-13"), "open": 950.0, "high": 970.0,
             "low": 940.0, "close": 955.0, "volume": 100},
            {"date": pd.Timestamp("2026-08-14"), "open": 990.0, "high": 1000.0,
             "low": 985.0, "close": 996.0, "volume": 200},
        ])

    def test_sleep_report_uses_real_market_price(self):
        from core.live_notifications import _build_holdings_message
        # 2026-09-16：報告改走 fetch_latest_closes_dated（先 MIS 當日報價 → 再日線）；
        # 這裡把 MIS 關掉，讓本測試專注在「日線來源」的行為（不連網）
        with patch("core.inst_data.fetch_intraday_quotes", return_value={}), \
             patch("core.inst_data._fetch_price_twse",
                   side_effect=self._fake_twse):
            msg = _build_holdings_message(pd, "3.9", "💤", "睡前持倉報告")
        # 市價應為 996（修復前顯示 798 = 成本），未實現損益 +18,414（修復前 +0）
        self.assertIn("參考市價 996", msg)
        self.assertIn("未實現損益 +18,414", msg)

    def test_closing_summary_uses_real_market_price(self):
        from core.live_notifications import send_closing_summary
        captured = {}
        with patch("core.inst_data.fetch_intraday_quotes", return_value={}), \
             patch("core.inst_data._fetch_price_twse",
                   side_effect=self._fake_twse), \
             patch("core.live_notifications.notify_all",
                   side_effect=lambda m: captured.setdefault("msg", m)):
            send_closing_summary(pd, "3.9")
        self.assertIn("參考市價 996", captured["msg"])
        self.assertIn("未實現損益 +18,414", captured["msg"])

    def test_sleep_report_fallback_when_fetch_fails(self):
        from core.live_notifications import _build_holdings_message
        with patch("core.inst_data.fetch_intraday_quotes", return_value={}), \
             patch("core.inst_data._fetch_price_twse",
                   return_value=pd.DataFrame()):
            msg = _build_holdings_message(pd, "3.9", "💤", "睡前持倉報告")
        # 抓價失敗時回退 CSV 最後成交價（既有行為），不中斷報告
        self.assertIn("參考市價 798", msg)


if __name__ == "__main__":
    unittest.main()


