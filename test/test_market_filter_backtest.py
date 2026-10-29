#!/usr/bin/env python
"""大盤年線（MA200）濾網的回歸測試（2026-10-28）。

背景：實盤買進前會檢查加權指數是否在 MA200 之上（`core/market_filter.py` +
`selfselect_trader.py` 的 `MARKET_TREND_FILTER`），**回測原本沒有這條** ⇒ 2018／2022 空頭年
的回測比實盤更差（實盤那段時間不會買）。回測用 `MARKET_FILTER=1` 重現，
判定規則抽成純函式 `core.backtest_rules.above_ma200()`（不 import 回測腳本，避免 50 秒載入）。
"""
import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import above_ma200  # noqa: E402

IDX = pd.date_range("2024-01-01", periods=400, freq="B")


def series(values):
    return pd.Series(values, index=IDX[:len(values)], dtype=float)


class TestAboveMa200(unittest.TestCase):
    def test_uptrend_is_above(self):
        self.assertTrue(above_ma200(series([100 + i * 0.5 for i in range(300)]), IDX[299]))

    def test_downtrend_is_below(self):
        self.assertFalse(above_ma200(series([400 - i * 0.5 for i in range(300)]), IDX[299]))

    def test_no_lookahead(self):
        """只能用 `as_of`（含）以前的資料：後面塞一段暴跌不能影響前面的判定。"""
        vals = [100 + i * 0.5 for i in range(300)]
        # 判定日 idx[299] 之後才暴跌
        vals += [50.0] * 50
        s = series(vals)
        self.assertTrue(above_ma200(s, IDX[299]), "as_of 當天之後的資料不得影響判定")
        self.assertIsNone(above_ma200(s, IDX[120]), "資料不足 200 筆 ⇒ 不過濾（None）")

    def test_insufficient_data_returns_none(self):
        """與實盤一致：不足 200 筆 → 跳過過濾（回傳 None，呼叫端視為不擋）。"""
        self.assertIsNone(above_ma200(series([100.0] * 199), IDX[198]))
        self.assertIsNone(above_ma200(pd.Series(dtype=float), IDX[0]))
        self.assertIsNone(above_ma200(None, IDX[0]))

    def test_custom_window(self):
        s = series([100 + i for i in range(300)])
        self.assertTrue(above_ma200(s, IDX[299], window=20))

    def test_bad_values_are_none(self):
        s = series([0.0] * 300)
        self.assertIsNone(above_ma200(s, IDX[299]), "均價 <= 0 屬於異常資料 ⇒ 不過濾")


if __name__ == "__main__":
    unittest.main(verbosity=2)
