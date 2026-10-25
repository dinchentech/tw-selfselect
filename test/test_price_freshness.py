#!/usr/bin/env python
"""回歸測試：報告的「參考市價」必須是**當日**，且要標示價格日期（2026-09-16）。

症狀（實盤）：09-16 13:45 的收盤持倉報告用的是 **09-15 的收盤價**
（2059 顯示 11,715、3017 顯示 3,115、3515 顯示 201、3653 顯示 5,310 —— 全是前一日收盤），
因為價格來源 `fetch_latest_closes` 走 TWSE STOCK_DAY，而該端點盤後才更新
⇒ 13:45 產生的報告系統性落後一個交易日。

修法：
- `core.inst_data.fetch_intraday_quotes()`：TWSE MIS 即時報價（`z`=最後成交、`d`=資料日期；
  13:30 後即當日收盤）為**第一順位**，失敗才退回 TWSE STOCK_DAY（可能為前一交易日）。
- `fetch_latest_closes_dated()`：回傳 `{sym: {'price','date','source'}}`；
  報告據此在標題旁標示「參考市價：<日期>」，非當日則加 ⚠️。
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

import core.inst_data as ID
from core.live_notifications import _build_holdings_message

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()


class TestDatedCloseFetch(unittest.TestCase):

    def test_prefers_same_day_intraday_quote(self):
        with mock.patch.object(ID, "fetch_intraday_quotes",
                               return_value={"2059": {"price": 12045.0, "date": TODAY, "time": "13:30:00"}}), \
             mock.patch.object(ID, "_fetch_daily_closes_dated", return_value={}):
            got = ID.fetch_latest_closes_dated(["2059"])
        self.assertEqual(got["2059"]["price"], 12045.0)
        self.assertEqual(got["2059"]["source"], "mis")
        self.assertEqual(got["2059"]["date"], TODAY)

    def test_falls_back_to_daily_close_with_its_date(self):
        with mock.patch.object(ID, "fetch_intraday_quotes", return_value={}), \
             mock.patch.object(ID, "_fetch_daily_closes_dated",
                               return_value={"2059": {"price": 11715.0, "date": YESTERDAY}}):
            got = ID.fetch_latest_closes_dated(["2059"])
        self.assertEqual(got["2059"]["price"], 11715.0)
        self.assertEqual(got["2059"]["source"], "daily")
        self.assertEqual(got["2059"]["date"], YESTERDAY)
        self.assertNotEqual(got["2059"]["date"], TODAY, "退回日線時必須誠實回報「那一筆」的日期")

    def test_daily_fetch_takes_date_from_data_not_clock(self):
        """日線來源的日期必須取自資料本身（否則又會標成當日、變成騙人）"""
        frame = pd.DataFrame([
            {"date": pd.Timestamp(YESTERDAY), "open": 1, "high": 1, "low": 1, "close": 11715.0, "volume": 1},
        ])
        with mock.patch.object(ID, "_fetch_price_twse", return_value=frame):
            got = ID._fetch_daily_closes_dated(["2059"])
        self.assertEqual(got["2059"]["date"], YESTERDAY)
        self.assertEqual(got["2059"]["price"], 11715.0)

    def test_legacy_api_still_returns_floats(self):
        with mock.patch.object(ID, "fetch_latest_closes_dated",
                               return_value={"2059": {"price": 12045.0, "date": TODAY, "source": "mis"}}):
            self.assertEqual(ID.fetch_latest_closes(["2059"]), {"2059": 12045.0})

    def test_source_guards(self):
        root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src = (root / "core" / "inst_data.py").read_text(encoding="utf-8")
        self.assertIn("def fetch_intraday_quotes", src, "缺少 MIS 當日報價來源")
        self.assertIn("mis.twse.com.tw", src, "MIS 端點不見了")
        body = src.split("def fetch_latest_closes_dated")[1].split("\ndef ")[0]
        self.assertIn("fetch_intraday_quotes", body, "fetch_latest_closes_dated 必須先試當日報價")
        self.assertLess(body.index("fetch_intraday_quotes"), body.index("_fetch_daily_closes_dated"),
                        "順序必須是「當日報價 → 日線」，不可顛倒")


class TestReportPriceNote(unittest.TestCase):
    """報告必須標示參考市價的日期，非當日要示警"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.getcwd()
        os.chdir(self._tmp.name)
        logs = Path("logs")
        logs.mkdir()
        (logs / "holdings.json").write_text(json.dumps({"2059": 18}), encoding="utf-8")
        (logs / "stock_allocation.json").write_text(
            json.dumps({"2059": {"total_buy_cost": 252000.0, "total_buy_shares": 18}}), encoding="utf-8")

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()

    def _msg(self, price, price_date, source):
        fake = {"2059": {"price": price, "date": price_date, "source": source}}
        with mock.patch.object(ID, "fetch_latest_closes_dated", return_value=fake):
            return _build_holdings_message(pd, "9.99", "📋", "收盤持倉報告", None, {"2059": {"strategy": "keep_wait"}})

    def test_uses_same_day_price_and_shows_date(self):
        msg = self._msg(12045.0, TODAY, "mis")
        self.assertIn("12,045", msg, "必須使用當日價（12,045）、不可用前一日 11,715")
        self.assertNotIn("11,715", msg)
        self.assertIn(f"參考市價：{TODAY}", msg, "報告要標示價格日期")
        self.assertNotIn("非當日", msg)

    def test_flags_stale_price(self):
        msg = self._msg(11715.0, YESTERDAY, "daily")
        self.assertIn(f"參考市價：{YESTERDAY}", msg)
        self.assertIn("非當日", msg, "退回前一交易日時必須示警，不能默默給舊數字")


if __name__ == '__main__':
    unittest.main()
