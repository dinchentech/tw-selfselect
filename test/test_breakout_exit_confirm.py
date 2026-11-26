#!/usr/bin/env python
"""回歸測試：breakout 出場確認變體（2026-11-24）。

## 背景

2603 於 2026-11-20 13:25 依 `breakout` 規則出場（報價 236.00 跌破 20 日低點 236.50、−14.9%），
之後 11/23 收 241、11/24 收 257 ⇒ 使用者要求比較兩個「不要太早出場」的變體：

- `BREAKOUT_CONFIRM_DAYS=2`：連續 2 日收盤都在各自前 20 日低點之下才賣（第 2 天才出場）。
- `BREAKOUT_MA_CONFIRM=1`：跌破前低**且**收盤 < MA20 才賣。

**變體 2 在數學上是 no-op**：收盤 < 前 20 日最低 ⇒ 收盤比前 20 天每根收盤都低 ⇒ 必然 < MA20
（下面 `test_ma_confirm_is_redundant` 用隨機序列把這個等價關係釘住，防止它未來被誤開而改變行為）。
"""
import os
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategies.breakout import breakout_strategy  # noqa: E402


def _df(closes, lows=None, highs=None):
    n = len(closes)
    lows = lows if lows is not None else [c - 0.5 for c in closes]
    highs = highs if highs is not None else [c + 1.0 for c in closes]
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                         "volume": [2_000_000] * n}, index=idx)


def _sells(df):
    return [str(d)[:10] for d, v in breakout_strategy(df)["signal"].items() if v == -1]


class _EnvMixin:
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("BREAKOUT_CONFIRM_DAYS", "BREAKOUT_MA_CONFIRM")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _enable(self, **kv):
        for k, v in kv.items():
            os.environ[k] = str(v)


class TestConfirmDays(_EnvMixin, unittest.TestCase):

    def test_baseline_sells_on_first_break(self):
        """現行規則：跌破當天就賣（2603 的實際情形）。"""
        closes = [100.0] * 25 + [90.0, 85.0, 80.0, 78.0, 76.0]
        days = _sells(_df(closes))
        self.assertEqual(days[0], "2026-02-05")     # 第 26 根＝第一次跌破

    def test_confirm_two_delays_first_exit_by_one_day(self):
        closes = [100.0] * 25 + [90.0, 85.0, 80.0, 78.0, 76.0]
        self._enable(BREAKOUT_CONFIRM_DAYS=2)
        days = _sells(_df(closes))
        self.assertEqual(days[0], "2026-02-06")     # 第 27 根才出場

    def test_confirm_requires_consecutive_breaks(self):
        """跌破 → 立刻收回：連續條件不成立 ⇒ 變體 1 那一波不出場（現行會賣）。"""
        closes = [100.0] * 25 + [90.0, 99.0, 95.0, 94.0, 93.0]
        self.assertEqual(_sells(_df(closes))[0], "2026-02-05")     # 現行：第一天就賣
        self._enable(BREAKOUT_CONFIRM_DAYS=2)
        self.assertEqual(_sells(_df(closes)), [], "沒有連續兩天跌破就不該出場")

    def test_confirm_never_earlier_than_baseline(self):
        rng = np.random.default_rng(7)
        closes = list(100 + np.cumsum(rng.normal(0, 2, 400)))
        base = _sells(_df(closes))
        self._enable(BREAKOUT_CONFIRM_DAYS=2)
        v1 = _sells(_df(closes))
        self.assertTrue(set(v1) <= set(base), "變體 1 的賣訊必須是基準的子集（只是晚一天）")

    def test_bad_env_value_is_ignored(self):
        closes = [100.0] * 25 + [90.0, 85.0, 80.0]
        self._enable(BREAKOUT_CONFIRM_DAYS="abc")
        self.assertEqual(_sells(_df(closes))[0], "2026-02-05")     # 壞值 ⇒ 回到基準行為


class TestMaConfirm(_EnvMixin, unittest.TestCase):

    def test_ma_confirm_is_redundant(self):
        """收盤 < 前 20 日最低 ⇒ 必然 < MA20 ⇒ 變體 2 與基準逐位相同。"""
        rng = np.random.default_rng(11)
        closes = list(100 + np.cumsum(rng.normal(0, 2.5, 600)))
        base = _sells(_df(closes))
        self._enable(BREAKOUT_MA_CONFIRM=1)
        self.assertEqual(_sells(_df(closes)), base)

    def test_ma_confirm_accepts_truthy_strings_only(self):
        closes = [100.0] * 25 + [90.0, 85.0, 80.0]
        self._enable(BREAKOUT_MA_CONFIRM="yes")
        self.assertEqual(_sells(_df(closes))[0], "2026-02-05")
        os.environ["BREAKOUT_MA_CONFIRM"] = "0"
        self.assertEqual(_sells(_df(closes))[0], "2026-02-05")     # 關閉時仍是基準


if __name__ == "__main__":
    unittest.main(verbosity=2)
