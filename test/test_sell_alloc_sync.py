"""回歸測試：賣出後分帳本必須同步扣減（與 add_stock_allocation 對稱）。

背景：logs/stock_allocation.json 曾被發現「無持股卻殘留成本」（3665/2886/2880，
合計 298,151），導致「現有資本(可買股)」被低估 ~29.8 萬。根因是舊賣出
（輪替清倉/trim 走 sell_with_fill_check、主迴圈內嵌扣減）未統一到一個
對稱的扣減函式，容易漂移失同步。

本測試鎖死「賣出 → 分帳本扣減」的不變式，作為回歸防線：
  - 整批賣出 → total_buy_cost/total_buy_shares 歸 0
  - 部分賣出 → 依加權均價按比例扣減
  - 超量賣出 → clamp 到 0（不為負）
  - 不在帳本 / 無持股 / 0 股 → 不動作（傳回 None、不改原檔）
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.live_utils import add_stock_allocation, sell_stock_allocation


class TestSellAllocSync(unittest.TestCase):
    def test_buy_then_full_sell_goes_to_zero(self):
        """2026-09-17 起：買進成本含手續費、賣出損益扣手續費＋證交稅（皆為淨額）。"""
        from core import fees
        alloc = {}
        add_stock_allocation(alloc, "2886", 74955.0, 1425)
        self.assertEqual(alloc["2886"]["total_buy_cost"],
                         74955.0 + fees.buy_fee(74955.0))
        self.assertEqual(alloc["2886"]["total_buy_shares"], 1425)
        profit, avg = sell_stock_allocation(alloc, "2886", 1425, 71962.5)
        self.assertEqual(alloc["2886"]["total_buy_cost"], 0.0)
        self.assertEqual(alloc["2886"]["total_buy_shares"], 0)
        self.assertAlmostEqual(avg, (74955.0 + fees.buy_fee(74955.0)) / 1425, places=2)
        self.assertAlmostEqual(
            profit, (71962.5 - fees.sell_cost(71962.5))
            - (74955.0 + fees.buy_fee(74955.0)), places=2)

    def test_partial_sell_decrements_proportionally(self):
        from core import fees
        alloc = {}
        add_stock_allocation(alloc, "2059", 252000.0, 18)
        total = 252000.0 + fees.buy_fee(252000.0)
        profit, avg = sell_stock_allocation(alloc, "2059", 6, 84000.0)  # 賣 6/18
        self.assertEqual(alloc["2059"]["total_buy_shares"], 12)
        self.assertAlmostEqual(alloc["2059"]["total_buy_cost"], total / 3 * 2, places=2)
        self.assertAlmostEqual(avg, total / 18, places=2)
        self.assertAlmostEqual(
            profit, (84000.0 - fees.sell_cost(84000.0)) - (total / 18 * 6), places=2)

    def test_sell_more_than_held_clamps_to_zero(self):
        alloc = {"3653": {"total_buy_cost": 175310.0, "total_buy_shares": 34}}
        profit, avg = sell_stock_allocation(alloc, "3653", 100, 0.0)
        self.assertEqual(alloc["3653"]["total_buy_shares"], 0)
        self.assertEqual(alloc["3653"]["total_buy_cost"], 0.0)
        self.assertIsNotNone(profit)

    def test_sell_symbol_not_in_alloc_is_noop(self):
        alloc = {"3008": {"total_buy_cost": 96915.0, "total_buy_shares": 13}}
        profit, avg = sell_stock_allocation(alloc, "9999", 10, 100.0)
        self.assertIsNone(profit)
        self.assertIsNone(avg)
        # 原檔未被動到
        self.assertEqual(alloc["3008"]["total_buy_shares"], 13)
        self.assertEqual(alloc["3008"]["total_buy_cost"], 96915.0)

    def test_sell_zero_or_negative_shares_is_noop(self):
        alloc = {"3017": {"total_buy_cost": 321930.0, "total_buy_shares": 94}}
        profit, avg = sell_stock_allocation(alloc, "3017", 0, 0.0)
        self.assertIsNone(profit)
        self.assertEqual(alloc["3017"]["total_buy_shares"], 94)

    def test_roundtrip_buy_then_sell_keeps_other_entries_intact(self):
        alloc = {
            "3017": {"total_buy_cost": 321930.0, "total_buy_shares": 94},
            "3653": {"total_buy_cost": 175310.0, "total_buy_shares": 34},
        }
        add_stock_allocation(alloc, "2059", 252000.0, 18)
        sell_stock_allocation(alloc, "2059", 18, 250200.0)  # 清倉 2059
        self.assertEqual(alloc["2059"]["total_buy_cost"], 0.0)
        self.assertEqual(alloc["2059"]["total_buy_shares"], 0)
        # 其他檔不受影響
        self.assertEqual(alloc["3017"]["total_buy_shares"], 94)
        self.assertEqual(alloc["3653"]["total_buy_shares"], 34)


if __name__ == "__main__":
    unittest.main()
