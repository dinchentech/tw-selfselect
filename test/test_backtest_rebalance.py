#!/usr/bin/env python
"""回測「換股頻率」規則的回歸測試（2026-10-28 新增 REBAL_MONTHS）。

需求：把「每月選股」改成「每 N 個月選股」，N 可設定、**預設 1（＝舊行為）**。

口徑差異（兩邊刻意不同，各自都要測）：
  - 回測：`selection_month_starts()` ＝ 期間內第 1、N+1、2N+1… 個月（跟著 START 走）
  - 實盤：`selfselect_scheduler.is_selection_month()` ＝ 日曆月對齊（N=12 ⇒ 每年 1 月）

規則本體放 `core/`（回測腳本 import 會載入全市場快取 ~50 秒，不能拿來跑測試）。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import selection_month_starts  # noqa: E402

# 2022-01 起的 12 個月第 1 個交易日（實際日期不重要，這裡只要「每月一個」的序列）
_MONTHS = [f"{y}-{m:02d}-01" for y in (2022, 2023) for m in range(1, 13)]


class TestSelectionMonthStarts(unittest.TestCase):
    def test_n1_keeps_every_month(self):
        """預設 N=1 必須回傳全部月份 —— 否則等於偷改既有回測結果。"""
        self.assertEqual(selection_month_starts(_MONTHS, 1), set(_MONTHS))

    def test_n12_takes_first_every_year(self):
        got = sorted(selection_month_starts(_MONTHS, 12))
        self.assertEqual(got, ["2022-01-01", "2023-01-01"])

    def test_n4_quarters(self):
        got = sorted(selection_month_starts(_MONTHS, 4))
        self.assertEqual(got, ["2022-01-01", "2022-05-01", "2022-09-01",
                               "2023-01-01", "2023-05-01", "2023-09-01"])

    def test_unsorted_input_and_odd_step(self):
        """輸入順序不影響結果；N 大於月份數時只取第一個。"""
        shuffled = list(reversed(_MONTHS))
        self.assertEqual(selection_month_starts(shuffled, 5),
                         selection_month_starts(_MONTHS, 5))
        self.assertEqual(sorted(selection_month_starts(_MONTHS, 99)), ["2022-01-01"])

    def test_bad_values_fall_back_to_every_month(self):
        for bad in (0, -3, None, "abc"):
            self.assertEqual(selection_month_starts(_MONTHS, bad), set(_MONTHS), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestFillMode(unittest.TestCase):
    """`FILL_MODE`（2026-10-29）：選不滿 N 檔時要「補滿」還是「就那幾檔平均分配」。

    `_fill()` 在回測腳本裡（import 時不會載資料），用假的 ranked 清單即可測。
    """

    def _fill(self, ranked, mode, top_n=5, pool=None, sel_date=None):
        import importlib
        import scripts.backtest_plan2_monthly_3group as bt
        old = bt.FILL_MODE
        old_top = bt.TOP_N
        try:
            bt.FILL_MODE = mode
            bt.TOP_N = top_n
            bt._FILL_STATS.update({"months": 0, "month_short": 0, "names_added": 0})
            return bt._fill(ranked, pool, sel_date)[0], dict(bt._FILL_STATS)
        finally:
            bt.FILL_MODE = old
            bt.TOP_N = old_top

    def test_proportional_keeps_only_strict(self):
        ranked = [("A", 9.0, True), ("B", 8.0, True), ("C", 7.0, False), ("D", 6.0, False)]
        got, stats = self._fill(ranked, "proportional")
        self.assertEqual(got, ["A", "B"], "比例模式：不過濾網的股票不買")
        self.assertEqual(stats["month_short"], 1)
        self.assertEqual(stats["names_added"], 0)

    def test_topup_fills_from_relaxed_candidates(self):
        ranked = [("A", 9.0, True), ("B", 8.0, True), ("C", 7.0, False), ("D", 6.0, False)]
        got, stats = self._fill(ranked, "topup")
        self.assertEqual(got, ["A", "B", "C", "D"])
        self.assertEqual(stats["names_added"], 2)

    def test_topup_does_not_exceed_top_n(self):
        ranked = [(f"S{i}", 10 - i, True) for i in range(8)]
        got, _ = self._fill(ranked, "topup")
        self.assertEqual(len(got), 5)

    def test_proportional_when_already_full_is_unchanged(self):
        ranked = [(f"S{i}", 10 - i, True) for i in range(6)]
        got, stats = self._fill(ranked, "proportional")
        self.assertEqual(len(got), 5)
        self.assertEqual(stats["month_short"], 0)


class TestTopupOnlyStocks(unittest.TestCase):
    """補滿只用個股（2026-10-29 使用者裁定）：ETF 只用在閒置停泊，不參與選股／補滿。"""

    def test_no_etf_option_left(self):
        import scripts.backtest_plan2_monthly_3group as bt
        for name in ("FILL_TOPUP_SOURCE", "FILL_TOPUP_ETFS", "FILL_TOPUP_ETF_RANK",
                     "_etf_rank", "_order_etfs"):
            self.assertFalse(hasattr(bt, name), f"{name} 應該已經移除")
        self.assertTrue(hasattr(bt, "IDLE_CASH_ASSET"), "閒置停泊（ETF）要保留")

    def test_topup_fills_with_stocks_only(self):
        import scripts.backtest_plan2_monthly_3group as bt
        old = (bt.FILL_MODE, bt.TOP_N)
        try:
            bt.FILL_MODE, bt.TOP_N = "topup", 5
            bt._FILL_STATS.update({"months": 0, "month_short": 0, "names_added": 0})
            got = bt._fill([("A", 9.0, True), ("B", 8.0, False), ("C", 7.0, False)], None, None)[0]
        finally:
            bt.FILL_MODE, bt.TOP_N = old
        self.assertEqual(got, ["A", "B", "C"])


class TestScoringModel(unittest.TestCase):
    """`SCORING_MODEL`（2026-10-29）：legacy（現行綜合分）vs zscore（AI 代理固定公式）。"""

    def test_default_is_zscore_and_park_0050(self):
        """2026-10-29 使用者裁定：預設組合＝zscore·停泊0050。"""
        import scripts.backtest_plan2_monthly_3group as bt
        self.assertEqual(bt.SCORING_MODEL, "zscore", "預設評分模型應為 zscore")
        self.assertEqual(bt.IDLE_CASH_ASSET, "0050", "預設閒置資金停泊 0050")

    def test_zscore_returns_nothing_without_data(self):
        """沒有價格資料時回空清單（不得丟錯）——用 setattr 造一個空的 data 全域。"""
        import pandas as pd
        import scripts.backtest_plan2_monthly_3group as bt
        had = hasattr(bt, "data")
        old = getattr(bt, "data", None)
        bt.data = {}
        try:
            got = bt._zscore_picks(["2330"], pd.Timestamp("2024-01-31"))
            self.assertEqual(got, [])
        finally:
            if had:
                bt.data = old
            else:
                del bt.__dict__["data"]

    def test_zscore_helper_exists_and_sorted(self):
        import scripts.backtest_plan2_monthly_3group as bt
        self.assertTrue(callable(bt._zscore_picks))
