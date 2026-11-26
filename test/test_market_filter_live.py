#!/usr/bin/env python
"""回歸測試：停泊閘門改用「日K MA200 × 當日即時指數」（2026-11-24 使用者裁定，v1.1.48）。

## 背景

A/C 原本跟自選股買進共用 `is_above_ma200()`，看的是**前一日收盤**（TWSE FMTQIK 當日列要收盤後才有）
⇒ 跳空日會慢一天。2026-11-24 實例：台股 +9.0%、0050 漲停 95.70，
但 13:25 的 A/C 只看到 11/23 收盤 36,811（< MA200 38,984）⇒ 把停泊賣在漲停、隔天再買回。

## 口徑

- 停泊（A/C）＝ **日K MA200 × 當日即時指數**（`MarketTrendFilter.is_above_ma200_live()`）。
- 自選股買進仍走 `is_above_ma200()`（日K 收盤，與回測同口徑）——刻意只改停泊。
- 即時指數取不到（MIS 失敗／非交易時段）⇒ **退回日K收盤**（＝舊行為），不擋停泊。
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.market_filter import MarketTrendFilter  # noqa: E402


def _df(last_close, base=38000.0, n=260):
    """260 根日K：最後一根是 `last_close`、前面都是 `base` ⇒ MA200 ≈ base 附近。"""
    closes = [base] * (n - 1) + [last_close]
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


class TestLiveMa200(unittest.TestCase):

    def _filter(self, daily_last, live):
        f = MarketTrendFilter()
        f._df, f._df_date = _df(daily_last), None   # 用指派注入，強制走我們的假資料
        f._fetch_tw_index = lambda: _df(daily_last)
        f.index_now = lambda: live
        return f

    def test_gap_up_day_uses_live_index(self):
        """11/24 實例：昨收 36,000 < MA200，但即時 40,123 > MA200 ⇒ 不賣停泊。"""
        f = self._filter(36000.0, 40123.0)
        self.assertTrue(f.is_above_ma200_live())

    def test_live_below_ma200_blocks(self):
        f = self._filter(38000.0, 35000.0)
        self.assertFalse(f.is_above_ma200_live())

    def test_unknown_when_live_index_unavailable(self):
        """2026-11-25（v1.1.51）：整天拿不到即時指數 ⇒ **None＝未知**，不得退回昨收翻轉閘門。

        11/25 事故：13:30 那圈 MIS 掛掉 ⇒ 舊版退回 11/24 收盤（在年線上）⇒ A 閘門翻成可停泊
        ⇒ 同一窗口把剛釋出的 6,000 股買回 4,000 股（同價）。
        """
        self.assertIsNone(self._filter(36000.0, 0.0).is_above_ma200_live())
        self.assertIsNone(self._filter(40000.0, 0.0).is_above_ma200_live())

    def test_stale_live_value_is_used_instead_of_flipping(self):
        """取不到新的即時值時，用當天稍早的值（≤30 分），不要翻成昨收判斷。"""
        import time as _time
        f = MarketTrendFilter()
        f._fetch_tw_index = lambda: _df(36000.0)
        f._live_price, f._live_ts = 40123.0, _time.time() - 120   # 兩分鐘前的即時值

        def _boom(syms, timeout=6, allow_prev_close=False):
            return {}
        import core.inst_data as inst
        orig = inst.fetch_intraday_quotes
        inst.fetch_intraday_quotes = _boom
        try:
            self.assertTrue(f.is_above_ma200_live())
            self.assertAlmostEqual(f.index_now(), 40123.0, places=2)
        finally:
            inst.fetch_intraday_quotes = orig

    def test_insufficient_daily_data_does_not_block(self):
        f = MarketTrendFilter()
        f._fetch_tw_index = lambda: _df(36000.0, n=50)
        f.index_now = lambda: 1.0
        self.assertTrue(f.is_above_ma200_live())

    def test_daily_version_still_uses_last_close(self):
        """自選股買進用的 `is_above_ma200()` 維持日K收盤口徑（與回測一致）。"""
        f = self._filter(36000.0, 40123.0)
        self.assertFalse(f.is_above_ma200())        # 昨收在年線下 ⇒ 仍擋買進

    def test_live_ttl_cache_keeps_value_for_a_minute(self):
        f = MarketTrendFilter()
        calls = []

        def _fake_quotes(syms, timeout=6, allow_prev_close=False):
            calls.append(1)
            return {"t00": {"price": 40123.0}}

        import core.inst_data as inst
        orig = inst.fetch_intraday_quotes
        inst.fetch_intraday_quotes = _fake_quotes
        try:
            self.assertAlmostEqual(f.index_now(), 40123.0, places=2)
            self.assertAlmostEqual(f.index_now(), 40123.0, places=2)   # 第二圈走快取
            self.assertEqual(len(calls), 1)
        finally:
            inst.fetch_intraday_quotes = orig


class TestTraderParkingUsesLive(unittest.TestCase):
    """`_park_market_ok()` 必須用即時版；自選股買進仍用日K版。"""

    def _fn(self, name):
        import ast
        import textwrap
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        body = list(fn.body)
        if isinstance(body[0], ast.Expr):
            body = body[1:]
        lines = src.splitlines()[body[0].lineno - 1:body[-1].end_lineno]
        return textwrap.dedent("\n".join(l for l in lines if not l.lstrip().startswith("#")))

    def test_parking_gate_uses_live_variant(self):
        seg = self._fn("_park_market_ok")
        self.assertIn("is_above_ma200_live()", seg)
        self.assertNotIn("market_filter.is_above_ma200()", seg)

    def test_stock_buy_filter_unchanged(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("market_filter.is_above_ma200()", src,
                      "自選股買進應維持日K收盤口徑（與回測一致）")




class TestLiveLogDedupe(unittest.TestCase):
    """v1.1.49：停泊閘門的診斷行每天只印一次（13:25–13:30 每圈 C/A 各呼叫一次會洗版）。"""

    def _filter(self, live):
        f = MarketTrendFilter()
        f._fetch_tw_index = lambda: _df(36000.0)
        f.index_now = lambda: live
        return f

    def test_prints_only_once_per_day(self):
        import contextlib
        import io
        f = self._filter(40123.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            f.is_above_ma200_live()
            f.is_above_ma200_live()      # 第二圈（C 之後換 A 再問一次）
            f.is_above_ma200_live()
        msg = buf.getvalue()
        self.assertEqual(msg.count("大盤過濾（停泊·即時）"), 1, msg)

    def test_resets_next_day(self):
        import contextlib
        import io
        f = self._filter(40123.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            f.is_above_ma200_live()
            f._live_log_date = "19000101"      # 模擬跨日
            f.is_above_ma200_live()
        self.assertEqual(buf.getvalue().count("大盤過濾（停泊·即時）"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
