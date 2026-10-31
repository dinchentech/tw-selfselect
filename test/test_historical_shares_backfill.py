#!/usr/bin/env python3
"""`scripts/build_historical_shares.py` 增量跳過邏輯的回歸測試（2026-09-18）。

背景：`historical_shares.pkl` 是母專案季度換股回測「誠實逐季池」（當時市值前 N 大）的股本來源。
舊版以「該 symbol 是否已有任何資料」決定跳過，導致**用 2015-2025 抓過的權值股
永遠補不到 2026 季點**：2026-09-18 實測 2026-02/05/08 各只有 ~350 檔（缺 152 檔，
含 2330/2317/2454 等大型股）⇒ 逐季池退化成中小型股池 → 2026 各季選股全錯。

本測試鎖住「逐季點判斷」這個行為。
"""
import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import build_historical_shares as B  # noqa: E402


class TestSymbolNeedsFetch(unittest.TestCase):
    YEARS = list(range(2015, 2027))

    def test_latest_quarter_point(self):
        # 未發生的季點不算（否則每次執行都會重抓整個候選池）
        yrs = list(range(2015, 2027))
        self.assertEqual(B.latest_quarter_point(yrs, today="2026-09"), "2026-08")
        self.assertEqual(B.latest_quarter_point(yrs, today="2026-12"), "2026-11")
        self.assertEqual(B.latest_quarter_point(yrs, today="2026-02"), "2026-02")
        self.assertEqual(B.latest_quarter_point(yrs, today="2026-01"), "2025-11")

    def test_symbol_without_latest_quarter_needs_fetch(self):
        """舊 bug：有 2015-2025 資料就整檔跳過 → 2026 季點永遠補不到。"""
        data = {("2330", q): 25_932_615_521 for q in
                [f"{y}-{m:02d}" for y in range(2015, 2026) for m in (2, 5, 8, 11)]}
        self.assertTrue(B.symbol_needs_fetch(data, "2330", self.YEARS))

    def test_symbol_with_latest_quarter_is_skipped(self):
        """有「今天為止最新的季點」就跳過。

        ⚠️ 2026-11-01 修：原本寫死 `2026-08`，到了 11 月最新季點變成 `2026-11` ⇒ 這個測試在換月當天
        自己紅掉（與程式無關，是測試對日期的隱性依賴）。改成向 `latest_quarter_point()` 動態取，
        測試就不會隨日期漂移（真正的行為仍由上面 `test_latest_quarter_point` 用固定 today 鎖住）。
        """
        latest = B.latest_quarter_point(self.YEARS)
        data = {("2330", "2025-08"): 25_932_615_521,
                ("2330", latest): 25_932_615_521}
        self.assertFalse(B.symbol_needs_fetch(data, "2330", self.YEARS))

    def test_symbol_without_todays_latest_quarter_needs_fetch(self):
        """只有「上一個」季點、沒有最新季點 ⇒ 仍要補（這正是 2026-09-18 修掉的舊 bug 行為）。"""
        latest = B.latest_quarter_point(self.YEARS)
        prev = None
        for cand in ("2025-08", "2026-02", "2026-05", "2026-08", "2026-11"):
            if cand < latest:
                prev = cand
        data = {("2330", prev or "2025-08"): 25_932_615_521}
        self.assertTrue(B.symbol_needs_fetch(data, "2330", self.YEARS))

    def test_unknown_symbol_needs_fetch(self):
        self.assertTrue(B.symbol_needs_fetch({}, "2330", self.YEARS))

    def test_other_symbols_data_does_not_cover(self):
        """別檔有 2026 季點，不代表本檔有（舊版集合判斷正是這樣誤放的鄰居）。"""
        data = {("2317", "2026-11"): 13_891_701_949}
        self.assertTrue(B.symbol_needs_fetch(data, "2330", self.YEARS))


class TestBuildQuarterlyShares(unittest.TestCase):
    class _FakeDL:
        def __init__(self, df):
            self._df = df

        def taiwan_stock_shareholding(self, stock_id, start, end):
            return self._df

    def test_takes_last_day_of_each_quarter_month(self):
        df = pd.DataFrame({
            "date": ["2026-02-05", "2026-02-27", "2026-05-29", "2026-08-31"],
            "NumberOfSharesIssued": [100, 200, 300, 400],
        })
        got = B.build_quarterly_shares(self._FakeDL(df), "2330", [2026])
        self.assertEqual(got, {("2330", "2026-02"): 200,
                               ("2330", "2026-05"): 300,
                               ("2330", "2026-08"): 400})

    def test_month_without_data_is_skipped(self):
        df = pd.DataFrame({"date": ["2026-08-31"], "NumberOfSharesIssued": [400]})
        got = B.build_quarterly_shares(self._FakeDL(df), "9999", [2026])
        self.assertEqual(got, {("9999", "2026-08"): 400})


if __name__ == "__main__":
    unittest.main()
