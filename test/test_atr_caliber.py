"""ATR 口徑回歸測試（2026-11-05）。

背景：`breakout` 的 TR 曾寫成 `max(high−low, |high−close|, |low−close|)`——因為 `close`
恆落在 `[low, high]` 內，後兩項永遠贏不過 `high−low` ⇒ 整個 max 退化為「當日振幅」，
**跳空完全不算**；而 `ma_cross` 另一份實作是正確的（含前一日收盤）。兩支同名不同義。

現在兩支都走 `strategies/indicators.atr()`，口徑＝Wilder TR（含跳空）＋ Wilder 平滑
（RMA／SMMA，α=1/N、以前 N 根平均起種）＝ TA-Lib `TA_ATR`／TradingView `ta.atr()`。

本檔鎖住四件事（任一被改壞就會紅）：
1. TR 一定含跳空（`|high − prev_close|` 能勝出）；
2. ATR 是 Wilder 平滑（跟獨立寫的遞迴參考實作逐位相同），不是簡單移動平均；
3. 兩支策略拿到**同一份** ATR（不許再分家）；
4. 退化版公式不得復活（原始碼守門）。
"""
import inspect
import unittest

import numpy as np
import pandas as pd

from strategies.breakout import breakout_strategy
from strategies.indicators import atr, true_range, wilder_smooth
from strategies.ma_cross import ma_cross_strategy


def _df(highs, lows, closes):
    n = len(closes)
    return pd.DataFrame({
        'open': list(closes),
        'high': list(highs),
        'low': list(lows),
        'close': list(closes),
        'volume': [1_000_000] * n,
    }, index=pd.date_range('2024-01-01', periods=n))


def _wilder_reference(series, period):
    """獨立實作的 Wilder 參考值（純 Python 迴圈，不共用被測程式碼的任何邏輯）。"""
    vals = [float(x) for x in series]
    out = [None] * len(vals)
    if len(vals) < period:
        return out
    acc = sum(vals[:period]) / period
    out[period - 1] = acc
    for i in range(period, len(vals)):
        acc = (acc * (period - 1) + vals[i]) / period
        out[i] = acc
    return out


class TestTrueRange(unittest.TestCase):

    def test_first_bar_is_high_minus_low(self):
        df = _df(highs=[11, 12], lows=[9, 10], closes=[10, 11])
        self.assertAlmostEqual(true_range(df).iloc[0], 2.0)

    def test_gap_up_counts_prev_close(self):
        """跳空：前收 100、今日 high 110/low 105 ⇒ TR 應為 10（不是 5）。"""
        df = _df(highs=[101, 110], lows=[99, 105], closes=[100, 108])
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[1], 10.0)
        self.assertGreater(tr.iloc[1], df['high'].iloc[1] - df['low'].iloc[1])

    def test_gap_down_counts_prev_close(self):
        df = _df(highs=[101, 95], lows=[99, 90], closes=[100, 92])
        self.assertAlmostEqual(true_range(df).iloc[1], 10.0)

    def test_no_gap_equals_high_minus_low(self):
        df = _df(highs=[101, 103], lows=[99, 100], closes=[100, 102])
        self.assertAlmostEqual(true_range(df).iloc[1], 3.0)

    def test_never_below_daily_range(self):
        rng = np.random.default_rng(7)
        close = 100 + rng.normal(0, 2, 200).cumsum()
        high = close + np.abs(rng.normal(0, 1, 200))
        low = close - np.abs(rng.normal(0, 1, 200))
        df = _df(high, low, close)
        tr = true_range(df)
        self.assertTrue((tr >= (df['high'] - df['low']) - 1e-9).all())


class TestWilderAtr(unittest.TestCase):

    def setUp(self):
        rng = np.random.default_rng(42)
        close = 100 + rng.normal(0, 2, 120).cumsum()
        high = close + np.abs(rng.normal(0, 0.8, 120))
        low = close - np.abs(rng.normal(0, 0.8, 120))
        self.df = _df(high, low, close)

    def test_first_period_minus_one_bars_are_nan(self):
        a = atr(self.df, 14)
        self.assertTrue(a.iloc[:13].isna().all(), '起種前不該有值')
        self.assertFalse(pd.isna(a.iloc[13]), '第 14 根（index 13）應該有起種值')

    def test_seed_is_simple_average_of_first_period(self):
        tr = true_range(self.df)
        a = atr(self.df, 14)
        self.assertAlmostEqual(a.iloc[13], float(tr.iloc[:14].mean()))

    def test_matches_independent_wilder_reference(self):
        """與獨立遞迴實作逐位相同（α=1/N，不是簡單移動平均）。"""
        tr = true_range(self.df)
        got = atr(self.df, 14).to_numpy(dtype=float)
        ref = _wilder_reference(tr.to_numpy(), 14)
        for i, r in enumerate(ref):
            if r is None:
                self.assertTrue(np.isnan(got[i]), f'第 {i} 根應為 NaN')
            else:
                self.assertAlmostEqual(got[i], r, places=9, msg=f'第 {i} 根不符 Wilder 遞迴')

    def test_is_not_simple_moving_average(self):
        """守門：如果誰把 Wilder 平滑改回 rolling().mean()，這裡會紅。"""
        a = atr(self.df, 14)
        sma = true_range(self.df).rolling(14, min_periods=1).mean()
        diff = (a - sma).abs().dropna().max()
        self.assertGreater(diff, 1e-6, 'Wilder 平滑與 SMA 不可能完全相同')

    def test_wilder_smooth_on_plain_series(self):
        s = pd.Series([1.0] * 14)
        out = wilder_smooth(s, 14)
        self.assertAlmostEqual(out.iloc[13], 1.0)

    def test_short_series_all_nan(self):
        df = _df(highs=[11, 12, 13], lows=[9, 10, 11], closes=[10, 11, 12])
        self.assertTrue(atr(df, 14).isna().all())


class TestStrategiesShareOneAtr(unittest.TestCase):

    def setUp(self):
        rng = np.random.default_rng(3)
        close = 100 + rng.normal(0, 2, 150).cumsum()
        high = close + np.abs(rng.normal(0, 1, 150))
        low = close - np.abs(rng.normal(0, 1, 150))
        self.df = _df(high, low, close)

    def test_both_strategies_use_indicators_atr(self):
        expected = atr(self.df, 14)
        for name, fn in (('ma_cross', ma_cross_strategy), ('breakout', breakout_strategy)):
            got = fn(self.df)['ATR']
            pd.testing.assert_series_equal(got, expected, check_names=False,
                                           obj=f'{name} 的 ATR 必須等於 indicators.atr()')

    def test_degenerate_true_range_formula_is_gone(self):
        """守門：`max(high−low, |high−close|, |low−close|)` 這個退化式不得復活。"""
        for mod in ('strategies/breakout.py',):
            src = inspect.getsource(__import__(mod.replace('/', '.').removesuffix('.py'),
                                               fromlist=['x']))
            self.assertNotIn("abs(row['high'] - row['close'])", src,
                             f'{mod}: 退化版 TR（用當日收盤捕跳空）又回來了')
            self.assertNotIn("abs(df['high'] - df['close'])", src,
                             f'{mod}: 退化版 TR（用當日收盤捕跳空）又回來了')
            self.assertNotIn('rolling(window=atr_period', src,
                             f'{mod}: ATR 不得自己用 rolling 算（要走 strategies/indicators）')


class TestGapAffectsSignals(unittest.TestCase):

    def test_gap_up_breakout_is_seen_only_with_gap_aware_atr(self):
        """連續跳空上攻的窄幅股：含跳空的 ATR 才會判定「波動夠大」而發出買訊。

        舊式（TR=當日振幅、SMA）在這種盤面把 ATR 算得極小 ⇒ 濾網永遠不過、訊號全被吃掉。
        """
        closes, highs, lows = [], [], []
        px = 100.0
        for _ in range(30):                      # 30 根窄幅盤整（日振幅 0.2%）
            closes.append(px)
            highs.append(px * 1.001)
            lows.append(px * 0.999)
        for _ in range(20):                       # 20 根連續跳空 2% 上攻
            prev = px
            px = px * 1.02
            closes.append(px)
            highs.append(px * 1.001)
            lows.append(prev * 1.01)
        df = _df(highs, lows, closes)

        tr_old = df['high'] - df['low']                                   # 舊式：當日振幅
        atr_old = tr_old.rolling(14, min_periods=1).mean()
        atr_new = atr(df, 14)
        dh = df['high'].rolling(20, min_periods=1).max().shift(1)
        old_buys = ((df['close'] > dh) & (atr_old > df['close'] * 0.01)).sum()
        new_buys = ((df['close'] > dh) & (atr_new > df['close'] * 0.01)).sum()
        self.assertGreater(new_buys, old_buys, '含跳空的 ATR 應該看得到這段突破')
        self.assertGreater(int((breakout_strategy(df)['signal'] == 1).sum()), 0)


if __name__ == '__main__':
    unittest.main()
