# test/test_backtest_finmind_compare.py — 模式二（backtest_finmind.py）比較口徑
"""
`backtest_finmind.compute_backtest` 是「多策略損益比較」的計算核心，口徑必須固定：

1. 單一部位：空手才買（+1 在持倉時忽略，對應實盤「滿倉不重複買」）；
   賣訊（−1）全數出清。
2. 每次買訊投入當下現金 100%；期末仍有持股以最後一根收盤平倉，並**計入賣出**。
3. 手續費：買 0.1425%、賣 0.4425%（含證交稅）。
4. 回傳 dict：final_equity／buys／sells／win_rate／total_return。
"""
import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backtest_finmind import compute_backtest  # noqa: E402


def _df(closes, signals):
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1000] * len(closes),
        "signal": signals,
    })


class TestComputeBacktest(unittest.TestCase):

    def test_buy_only_once_while_holding(self):
        """連續三個 +1 只會建立一個部位（滿倉不重複買）。"""
        m = compute_backtest(_df([100, 110, 120], [1, 1, 1]))
        self.assertEqual(m["buys"], 1)
        self.assertEqual(m["sells"], 1)          # 期末平倉
        self.assertGreater(m["final_equity"], 500_000)

    def test_round_trip_and_fees(self):
        """一次完整來回：買 100 賣 110，手續費吃掉一部分；勝率 1/1。"""
        m = compute_backtest(_df([100, 110, 0], [1, -1, 0]))
        self.assertEqual((m["buys"], m["sells"]), (1, 1))
        self.assertEqual(m["win_rate"], 1.0)
        # 4992 股（500,000/(100×1.001425) 取整）→ 110 賣出含 0.4425% 費用
        self.assertAlmostEqual(m["final_equity"], 88.64 + 4992 * 110 * (1 - 0.004425), delta=2)

    def test_second_entry_uses_remaining_cash(self):
        """賣出後可以再買一次；第二筆以「當下現金」計算股數。"""
        m = compute_backtest(_df([100, 110, 105], [1, -1, 1]))
        self.assertEqual((m["buys"], m["sells"]), (2, 2))   # 第二次是期末平倉
        self.assertGreater(m["final_equity"], 500_000)

    def test_win_rate_counts_closed_positions(self):
        """勝率以「平倉筆數」為分母（期末平倉也算一筆）。"""
        m = compute_backtest(_df([100, 110, 105, 120], [1, -1, 1, -1]))
        self.assertEqual((m["buys"], m["sells"]), (2, 2))
        self.assertAlmostEqual(m["win_rate"], 1.0)

    def test_empty_or_flat_signals(self):
        """沒有訊號 → 權益不變、無交易。"""
        m = compute_backtest(_df([100, 101, 102], [0, 0, 0]))
        self.assertEqual((m["buys"], m["sells"]), (0, 0))
        self.assertEqual(m["final_equity"], 500_000)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["total_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
