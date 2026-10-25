#!/usr/bin/env python3
"""`scripts/backtest_plan2_monthly_3group.py` 的 PER 取值回歸測試（2026-09-18）。

背景（實測事故）：該腳本的「過熱閘門」用 FinMind PER，而 PER 原本**只存在記憶體快取**、
每次執行都重打 API ⇒ 抓到／抓不到 PER 會讓閘門行為不同：
**同一組參數兩次跑出 正常組 +79.2% 與 +109.6%**（重跑不可重現 ⇒ 回測結論不可信）。
修法：改用與 `分析腳本` **共用**的磁碟快取
`cache/rotation_per/per_{代號}.pkl`（`{date_str: PER}`），抓不到才打 API 並落地。

本測試只驗純函式 `per_at()`（不連網、不載入重型快取）。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import pandas as pd  # noqa: E402
import backtest_plan2_monthly_3group as B  # noqa: E402


class TestPerAt(unittest.TestCase):
    def setUp(self):
        self.series = {"2026-01-05": 12.5, "2026-03-02": 15.0, "2026-06-30": 20.0}

    def test_takes_latest_on_or_before_date(self):
        self.assertEqual(B.per_at(self.series, pd.Timestamp("2026-03-15")), 15.0)
        self.assertEqual(B.per_at(self.series, pd.Timestamp("2026-06-30")), 20.0)

    def test_no_lookahead_ignores_future(self):
        """選在 2026-02-01：只能用 2026-01-05 那筆，不得偷看 3 月以後。"""
        self.assertEqual(B.per_at(self.series, pd.Timestamp("2026-02-01")), 12.5)

    def test_returns_none_when_all_dates_are_future(self):
        self.assertIsNone(B.per_at(self.series, pd.Timestamp("2025-12-31")))

    def test_returns_none_for_empty_or_bad(self):
        self.assertIsNone(B.per_at({}, pd.Timestamp("2026-03-15")))
        self.assertIsNone(B.per_at(None, pd.Timestamp("2026-03-15")))

    def test_skips_non_numeric_values(self):
        s = {"2026-01-05": 12.5, "2026-03-02": "-", "2026-06-30": 20.0}
        self.assertEqual(B.per_at(s, pd.Timestamp("2026-03-15")), 12.5)

    def test_accepts_various_date_key_formats(self):
        s = {pd.Timestamp("2026-01-05"): 12.5, "2026/03/02": 15.0}
        self.assertEqual(B.per_at(s, pd.Timestamp("2026-04-01")), 15.0)


class TestSeriesMaxDate(unittest.TestCase):
    """過期判定：既有快取只到 2025-12-31，拿去過濾 2026 年選股＝閘門失效 ⇒ 必須能判斷新舊。"""

    def test_max_date(self):
        s = {"2025-12-31": 10.0, "2025-01-02": 9.0}
        self.assertEqual(B.series_max_date(s), pd.Timestamp("2025-12-31"))

    def test_handles_bad_keys_and_empty(self):
        self.assertEqual(B.series_max_date({"bad": 1}), None)
        self.assertIsNone(B.series_max_date({}))
        self.assertIsNone(B.series_max_date(None))

    def test_stale_detection_threshold(self):
        old_series = {"2025-12-31": 10.0}
        sel = pd.Timestamp("2026-06-30")
        fresh_enough = (B.series_max_date(old_series)
                        >= sel - pd.Timedelta(days=B._PER_STALE_DAYS))
        self.assertFalse(fresh_enough, "2025-12-31 對 2026-06-30 的選股＝過期，必須重抓")


class TestDiskCacheWiring(unittest.TestCase):
    """釘住「有共用磁碟快取」這件事 —— 否則又會退回不可重現的記憶體快取。"""



if __name__ == "__main__":
    unittest.main()
