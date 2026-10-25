#!/usr/bin/env python
"""回測「硬停損」規則的回歸測試（2026-09-16 評估用）。

背景：使用者問「為何虧錢賣 / 怎麼沒有虧 10% 退場」，決定用回測評估「加 −N% 硬停損」。
規則本體在 `core/backtest_rules.py`（純函式）——**刻意不放在回測腳本裡**，
因為該腳本 import 時會載入全市場快取（實測 ~50 秒），會拖垮整套測試。

口徑（與回測既有慣例一致）：**日頻、以當日收盤價判定**
（回測所有買賣都用 `close_at()`）；`px <= entry × (1 − pct/100)` 即觸發。
"""
import os
import unittest.mock
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import (  # noqa: E402
    stop_hit, stop_loss_env, first_stop_date, skip_quarter_value,
)


class TestSkipQuarterValue(unittest.TestCase):
    """MDB 跳過換股那一季：**現金不可被吃掉**（2026-09-16 修引擎 bug 的回歸測試）。"""

    def test_cash_is_included(self):
        # 續抱 2 檔（市值 30 萬 + 20 萬）＋ 提前出場回籠現金 45 萬 → 帳戶 95 萬
        self.assertAlmostEqual(skip_quarter_value([300000.0, 200000.0], 450000.0), 950000.0)

    def test_no_cash_matches_holdings_only(self):
        self.assertAlmostEqual(skip_quarter_value([100.0, 50.0], 0.0), 150.0)

    def test_empty_and_bad_inputs(self):
        self.assertAlmostEqual(skip_quarter_value([], 0.0), 0.0)
        self.assertAlmostEqual(skip_quarter_value([100.0], None), 100.0)


class TestFirstStopDate(unittest.TestCase):
    """回測引擎用的「段內首個停損日」掃描（`backtest_selector` 的提前出場用）。"""

    def _window(self):
        return pd.Series([100.0, 98.0, 89.0, 86.0, 95.0],
                         index=pd.date_range('2026-01-01', periods=5, freq='D'))

    def test_finds_first_breach(self):
        w = self._window()
        got = first_stop_date(w, 100.0, 10)
        self.assertEqual(got, w.index[2], '應回第一個收盤 ≤ −10% 的日期（89）')

    def test_returns_none_when_disabled_or_not_breached(self):
        w = self._window()
        self.assertIsNone(first_stop_date(w, 100.0, 0), '停損關閉 → None')
        self.assertIsNone(first_stop_date(w, 100.0, 30), '沒跌破 −30% → None')

    def test_bad_inputs_are_safe(self):
        w = self._window()
        for pct in (None, 'x', -5):
            self.assertIsNone(first_stop_date(w, 100.0, pct), f'pct={pct!r} 應回 None')
        self.assertIsNone(first_stop_date(w, 0.0, 10), '沒有成本基礎 → None')


class TestStopHit(unittest.TestCase):
    def test_disabled_when_zero(self):
        self.assertFalse(stop_hit(50.0, 100.0, 0), 'STOP_LOSS_PCT=0 必須完全關閉（基準行為不變）')

    def test_triggers_at_or_below_threshold(self):
        self.assertTrue(stop_hit(90.0, 100.0, 10), '正好 −10% 要觸發（≤）')
        self.assertTrue(stop_hit(89.9, 100.0, 10))
        self.assertFalse(stop_hit(90.1, 100.0, 10), '−9.9% 不該觸發')

    def test_no_position_cost_basis_is_safe(self):
        self.assertFalse(stop_hit(50.0, 0.0, 10), '沒有成本基礎（entry=0）不可觸發')
        self.assertFalse(stop_hit(0.0, 100.0, 10), '無價格不可觸發')

    def test_negative_or_bad_pct_is_off(self):
        for pct in (-10, 0.0, None, 'x'):
            try:
                got = stop_hit(50.0, 100.0, pct)
            except Exception as e:
                self.fail(f'pct={pct!r} 不該拋例外：{e}')
            self.assertFalse(got, f'pct={pct!r} 應視為停用')

    def test_env_reader(self):
        with unittest.mock.patch.dict(os.environ, {"STOP_LOSS_PCT": "10"}):
            self.assertEqual(stop_loss_env("STOP_LOSS_PCT"), 10.0)
        with unittest.mock.patch.dict(os.environ, {"STOP_LOSS_PCT": "abc"}):
            self.assertEqual(stop_loss_env("STOP_LOSS_PCT", 0.0), 0.0, '壞值要回退預設（不可拋例外）')


if __name__ == '__main__':
    unittest.main()
