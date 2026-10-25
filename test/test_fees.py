#!/usr/bin/env python
"""費用模型回歸測試（2026-09-17 新增）。

背景：實盤與儀表板**完全沒有手續費/證交稅** —— 全 codebase 只有法人動能回測裡
一個 `BUY_COST` 常數。`log_trade` 只記 `價 × 股數`、`sell_stock_allocation` 用
`px × shares` 當收入 ⇒ 儀表板的「累積損益 +5,516」是**毛額**；
按玉山牌告 0.1425%（最低 NT$20）＋ 證交稅 0.3% 估算，實際約 **−7,800**。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import fees  # noqa: E402


class TestFeeMath(unittest.TestCase):
    def test_buy_fee_is_proportional_above_floor(self):
        # 100,000 × 0.1425% = 142.5 → 143（四捨五入至元）
        self.assertEqual(fees.buy_fee(100_000), 143)

    def test_buy_fee_hits_the_minimum_on_small_orders(self):
        # 1 股 3653 @5,975 = 5,975 → 比例 8.5 元 → 收最低 20 元（實效 0.33%）
        self.assertEqual(fees.buy_fee(5_975), 20)
        # 4 股 6213 @550 = 2,200 → 最低 20 元（實效 0.91%）
        self.assertEqual(fees.buy_fee(2_200), 20)

    def test_sell_side_includes_tax(self):
        # 賣 100,000：手續費 143 + 證交稅 300 = 443
        self.assertEqual(fees.sell_tax(100_000), 300)
        self.assertEqual(fees.sell_fee(100_000), 143)
        self.assertEqual(fees.sell_cost(100_000), 443)

    def test_tx_cost_dispatches_by_action(self):
        self.assertEqual(fees.tx_cost("BUY", 100_000), 143)
        self.assertEqual(fees.tx_cost("SELL", 100_000), 443)
        self.assertEqual(fees.tx_cost("buy", 100_000), 143)

    def test_zero_or_negative_amount_is_free(self):
        for amt in (0, -1, None):
            self.assertEqual(fees.tx_cost("BUY", amt), 0)
            self.assertEqual(fees.tx_cost("SELL", amt), 0)

    def test_sell_always_costs_at_least_the_minimum(self):
        # 賣 1 股 6213 @550 = 550 → 最低 20 + 稅 2 = 22
        self.assertEqual(fees.sell_cost(550), 22)

    def test_rates_come_from_env(self):
        """費率可調（玉山有折扣戶）；改了要立刻生效，不要被 import 時快取住。"""
        old = {k: os.environ.get(k) for k in ("FEE_RATE", "MIN_FEE", "SELL_TAX_RATE")}
        try:
            os.environ["FEE_RATE"] = "0.000855"     # 6 折
            self.assertEqual(fees.buy_fee(100_000), 86)
            os.environ["MIN_FEE"] = "1"
            self.assertEqual(fees.buy_fee(1_000), 1)
            os.environ["SELL_TAX_RATE"] = "0.001"   # ETF
            self.assertEqual(fees.sell_tax(100_000), 100)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_effective_rate_helper(self):
        """低於門檻的小單實效費率遠高於牌告 —— 這是「1 股單很浪費」的量化依據。"""
        self.assertAlmostEqual(fees.effective_rate("BUY", 100_000), 0.00143, places=5)
        self.assertGreater(fees.effective_rate("BUY", 2_200), 0.008)

    def test_breakeven_amount_is_min_fee_over_rate(self):
        """最低手續費的損益兩平金額：20 / 0.1425% ≈ 14,035 —— 全輪替補足門檻的依據。"""
        self.assertAlmostEqual(fees.breakeven_amount(), 20 / 0.001425, delta=1)

    def test_portfolio_totals(self):
        """整批交易的費用合計（給對帳腳本/報告用）。"""
        rows = [{"action": "BUY", "price": "100.0", "quantity": "1000"},
                {"action": "SELL", "price": "110.0", "quantity": "1000"}]
        tot = fees.total_for_rows(rows)
        self.assertEqual(tot, fees.buy_fee(100_000) + fees.sell_cost(110_000))

    def test_row_cost_prefers_recorded_value(self):
        """CSV 有記錄就用記錄值（歷史真實），沒有才用費率推定。"""
        self.assertEqual(fees.row_cost({"action": "BUY", "price": "100.0",
                                        "quantity": "1000", "cost": "137"}), 137.0)
        self.assertEqual(fees.row_cost({"action": "BUY", "price": "100.0",
                                        "quantity": "1000", "cost": ""}), 143)
        self.assertEqual(fees.row_cost({"action": "BUY", "price": "100.0",
                                        "quantity": "1000"}), 143)


if __name__ == "__main__":
    unittest.main()
