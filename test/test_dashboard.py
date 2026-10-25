"""回歸測試：績效儀表板現值必須反映真實市價，而非凍結在成本價。

Bug 背景：build_html() 呼叫 compute_positions() 時未傳入即時市價，
導致市價 = performance.csv 最後一筆成交價（對未平倉部位而言就是買進價），
未實現損益恆為 +0、現值永不更動。
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def make_trades_df():
    """2357 於 2026-08-03 以 798 買進 93 股（後續無交易）。"""
    df = pd.DataFrame([
        {"timestamp": "2026-08-03 09:00:00", "symbol": "2357", "signal": "BUY",
         "price": 798.0, "quantity": 93, "action": "BUY", "group": 1},
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    return df


class TestDashboardCurrentPrices(unittest.TestCase):
    def setUp(self):
        from scripts import generate_dashboard as gd
        self.gd = gd
        self.df = make_trades_df()

    def _write_fixtures(self, tmp: Path):
        """寫入 holdings.json / stock_allocation.json fixture。"""
        (tmp / "holdings.json").write_text(
            json.dumps({"2357": 93}), encoding="utf-8")
        (tmp / "stock_allocation.json").write_text(
            json.dumps({"2357": {"total_buy_cost": 798 * 93,
                                 "total_buy_shares": 93}}), encoding="utf-8")

    def test_build_html_uses_fetched_market_prices(self):
        """修復後：build_html 應抓取真實市價並反映在未實現損益。

        2357 成本 798、市價 996（2026-08-14 實際收盤）→
        未實現損益 = (996 - 798) × 93 = +18,414，而非 +0。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._write_fixtures(tmp)
            with patch.object(self.gd, "HOLDINGS_PATH", tmp / "holdings.json"), \
                 patch.object(self.gd, "STOCK_ALLOC_PATH", tmp / "stock_allocation.json"), \
                 patch.object(self.gd, "CSV_PATH", tmp / "performance.csv"), \
                 patch.object(self.gd, "fetch_current_prices_dated",
                              return_value=({"2357": 996.0}, {"2357": datetime.now().strftime("%Y-%m-%d")})):
                html = self.gd.build_html(self.df)

        # 市價欄應顯示真實市價 996（修復前會顯示 798 = 成本）
        self.assertIn("<td>996</td>", html)
        # 未實現損益應為 +18,414（修復前恆為 +0）
        self.assertIn("+18,414", html)
        # 持倉市值應為 996 × 93 = 92,628（修復前為 74,214 = 成本市值）
        self.assertIn("92,628", html)
        # 報酬率應為 +24.81%（修復前恆為 +0.00%）
        self.assertIn("+24.81%", html)
        # 2026-10-06：未平倉部位上方必須顯示「參考市價」的資料日期（與 TG 同一串字）
        self.assertIn("📈 參考市價：" + datetime.now().strftime("%Y-%m-%d"), html)

    def test_fetch_current_prices_returns_latest_close(self):
        """fetch_current_prices 應回傳標的最後交易日收盤價（mock TWSE 資料）。"""
        fake_twse = pd.DataFrame([
            {"date": pd.Timestamp("2026-08-14"), "open": 990.0, "high": 1000.0,
             "low": 985.0, "close": 996.0, "volume": 100},
            {"date": pd.Timestamp("2026-08-13"), "open": 950.0, "high": 970.0,
             "low": 940.0, "close": 955.0, "volume": 200},
        ])
        def side_effect(stock_id, start, end):
            return fake_twse if stock_id == "2357" else pd.DataFrame()
        # 2026-09-16：fetch_latest_closes 改為「先 MIS 當日報價 → 再日線」；
        # 這裡把 MIS 關掉，讓本測試專注在日線來源（不連網）
        with patch("core.inst_data.fetch_intraday_quotes", return_value={}), \
             patch("core.inst_data._fetch_price_twse", side_effect=side_effect) as m:
            prices = self.gd.fetch_current_prices(["2357", "9999"])
        self.assertEqual(prices, {"2357": 996.0})
        # 每檔應抓本月 + 上個月兩個月份
        self.assertEqual(m.call_count, 4)

    def test_fetch_current_prices_network_failure_returns_empty(self):
        """兩個來源都抓不到價時應回傳空 dict，讓既有 fallback 生效、不中斷產檔。"""
        with patch("core.inst_data.fetch_intraday_quotes", return_value={}), \
             patch("core.inst_data._fetch_price_twse",
                   return_value=pd.DataFrame()) as m:
            prices = self.gd.fetch_current_prices(["2357"])
        self.assertEqual(prices, {})
        self.assertEqual(m.call_count, 2)


class TestDashboardPriceDateBanner(unittest.TestCase):
    """2026-10-06：儀表板必須顯示「參考市價」的**資料日期**（非當日要示警）。

    背景：使用者比對儀表板與 TG 的 2059 損益（−12,465 vs −64,650）發現不一致；
    兩邊都走 TWSE MIS，但**儀表板是靜態快照、TG 是即時**，而儀表板沒顯示價格日期 ⇒ 看不出誰舊。
    """

    def setUp(self):
        from scripts import generate_dashboard as gd
        self.gd = gd
        self.df = make_trades_df()

    def _html_with_dates(self, dates):
        tmp = tempfile.TemporaryDirectory()
        t = Path(tmp.name)
        (t / "holdings.json").write_text(json.dumps({"2357": 93}), encoding="utf-8")
        (t / "stock_allocation.json").write_text(
            json.dumps({"2357": {"total_buy_cost": 798 * 93, "total_buy_shares": 93}}),
            encoding="utf-8")
        with patch.object(self.gd, "HOLDINGS_PATH", t / "holdings.json"), \
             patch.object(self.gd, "STOCK_ALLOC_PATH", t / "stock_allocation.json"), \
             patch.object(self.gd, "CSV_PATH", t / "performance.csv"), \
             patch.object(self.gd, "fetch_current_prices_dated",
                          return_value=({"2357": 996.0}, dates)):
            html = self.gd.build_html(self.df)
        tmp.cleanup()
        return html

    def test_same_day_price_has_no_warning(self):
        today = datetime.now().strftime("%Y-%m-%d")
        html = self._html_with_dates({"2357": today})
        self.assertIn(f"📈 參考市價：{today}", html)
        self.assertNotIn("⚠️非當日", html)

    def test_stale_price_is_flagged(self):
        html = self._html_with_dates({"2357": "2026-10-02"})
        self.assertIn("📈 參考市價：2026-10-02", html)
        self.assertIn("⚠️非當日", html)

    def test_uses_shared_helper_with_tg_report(self):
        """必須使用與 TG 持倉報告**同一個 helper**（否則兩邊口徑會漂移）。"""
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "scripts" / "generate_dashboard.py").read_text(
            encoding="utf-8")
        self.assertIn("from core.live_notifications import price_date_note", src)

    def test_dated_fetcher_splits_price_and_date(self):
        fake = {"2357": {"price": 996.0, "date": "2026-10-06", "source": "mis"}}
        with patch("core.inst_data.fetch_latest_closes_dated", return_value=fake):
            prices, dates = self.gd.fetch_current_prices_dated(["2357"])
        self.assertEqual(prices, {"2357": 996.0})
        self.assertEqual(dates, {"2357": "2026-10-06"})

    def test_dated_fetcher_handles_missing_date(self):
        with patch("core.inst_data.fetch_latest_closes_dated",
                   return_value={"2357": {"price": 996.0, "date": ""}}):
            prices, dates = self.gd.fetch_current_prices_dated(["2357"])
        self.assertEqual(prices, {"2357": 996.0})
        self.assertEqual(dates, {})


if __name__ == "__main__":
    unittest.main()
