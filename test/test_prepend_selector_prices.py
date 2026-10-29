#!/usr/bin/env python
"""`scripts/prepend_selector_prices.py` 的回歸測試（2026-10-28）。

背景：股價快取幾乎全部從 2022-01-03 開始 ⇒ 2016-2021 的回測（2018 空頭、2020 COVID）跑不了。
補歷史時**既有列一個位元都不能動**（回測可重現性），新增（較舊）那段要用重疊日算出的
ratio 縮放（yfinance `auto_adjust` 的還原價會回溯改變），否則接縫日會出現假跳空。

`plan_symbol()` / `merge_prepend()` 是純函式，這裡直接測（不需要網路）。
"""
import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.prepend_selector_prices import (  # noqa: E402
    MAX_RATIO_STD, merge_prepend, plan_symbol,
)


def _df(dates, close, scale=1.0):
    """造一個快取格式的 DataFrame（open/high/low/close/volume，index 名 Date）。"""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates], name="Date")
    close = [c * scale for c in close]
    return pd.DataFrame({
        "close": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "open": [c * 1.0 for c in close],
        "volume": [1_000_000] * len(close),
    }, index=idx)


OLD_DATES = ["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06", "2022-01-07"]
OLD_CLOSE = [100.0, 101.0, 102.0, 103.0, 104.0]
NEW_OLD_DATES = ["2021-12-28", "2021-12-29", "2021-12-30"]   # 快取沒有的更早日子


class TestPlanSymbol(unittest.TestCase):
    def setUp(self):
        self.old = _df(OLD_DATES, OLD_CLOSE)
        # 新抓的資料：重疊段是舊資料 ÷ 1.25（版本差異），外加更早三天
        self.fresh = _df(NEW_OLD_DATES + OLD_DATES,
                         [80.0, 79.2, 78.4] + [c / 1.25 for c in OLD_CLOSE])

    def test_ratio_is_applied_to_older_segment(self):
        pl = plan_symbol(self.old, self.fresh)
        self.assertTrue(pl["ok"], pl.get("reason"))
        self.assertAlmostEqual(pl["ratio"], 1.25, places=6)
        # 只有「更早」的列會被補
        self.assertEqual(list(pl["rows"].index.strftime("%Y-%m-%d")), NEW_OLD_DATES)
        # 縮放後要接得回舊基準（80 × 1.25 = 100 附近的水位）
        self.assertAlmostEqual(float(pl["rows"]["close"].iloc[-1]), 78.4 * 1.25, places=6)

    def test_seam_jump_is_within_a_single_day_move(self):
        pl = plan_symbol(self.old, self.fresh)
        self.assertLess(abs(pl["seam_jump"]), 0.05, "縮放正確時接縫不該有假跳空")

    def test_ratio_one_means_no_scaling(self):
        fresh = _df(NEW_OLD_DATES + OLD_DATES, [80.0, 79.2, 78.4] + OLD_CLOSE)
        pl = plan_symbol(self.old, fresh)
        self.assertTrue(pl["ok"])
        self.assertAlmostEqual(pl["ratio"], 1.0, places=9)
        self.assertAlmostEqual(float(pl["rows"]["close"].iloc[-1]), 78.4, places=9)

    def test_no_older_data_is_not_ok(self):
        pl = plan_symbol(self.old, _df(OLD_DATES, OLD_CLOSE))
        self.assertFalse(pl["ok"])
        self.assertIn("沒有更早", pl["reason"])

    def test_insufficient_overlap_is_not_ok(self):
        fresh = _df(NEW_OLD_DATES + ["2022-01-07"], [80.0, 79.2, 78.4, 104.0])
        pl = plan_symbol(self.old, fresh, min_overlap=3)
        self.assertFalse(pl["ok"])
        self.assertIn("重疊", pl["reason"])

    def test_unstable_ratio_is_rejected(self):
        """重疊段比值忽大忽小 ⇒ 不是單純版本差異（可能是資料錯/不同標的）⇒ 拒絕。"""
        fresh = _df(NEW_OLD_DATES + OLD_DATES,
                    [80.0, 79.2, 78.4, 100.0 / 1.0, 101.0 / 1.5, 102.0 / 1.25,
                     103.0 / 1.25, 104.0 / 1.25])
        pl = plan_symbol(self.old, fresh)
        self.assertFalse(pl["ok"])
        self.assertIn("ratio", pl["reason"])
        self.assertLess(MAX_RATIO_STD, 0.1)

    def test_empty_fresh_is_not_ok(self):
        self.assertFalse(plan_symbol(self.old, None)["ok"])
        self.assertFalse(plan_symbol(self.old, pd.DataFrame())["ok"])


class TestMergePrepend(unittest.TestCase):
    def test_existing_rows_are_untouched(self):
        old = _df(OLD_DATES, OLD_CLOSE)
        pl = plan_symbol(old, _df(NEW_OLD_DATES + OLD_DATES,
                                  [80.0, 79.2, 78.4] + [c / 1.25 for c in OLD_CLOSE]))
        merged = merge_prepend(old, pl["rows"])
        self.assertEqual(len(merged), len(OLD_DATES) + len(NEW_OLD_DATES))
        for d, c in zip(OLD_DATES, OLD_CLOSE):
            self.assertEqual(float(merged.loc[pd.Timestamp(d), "close"]), c, d)
        self.assertEqual(merged.index.name, "Date")
        self.assertTrue(merged.index.is_monotonic_increasing)
        self.assertFalse(merged.index.has_duplicates)


if __name__ == "__main__":
    unittest.main(verbosity=2)
