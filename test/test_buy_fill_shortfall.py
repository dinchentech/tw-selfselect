"""測試：買入未補足檢查（BUY_AMOUNT_OFFSET + 3交易日逾時 TG）"""
import unittest
from datetime import date
from unittest.mock import MagicMock

from core.live_utils import check_buy_fill_shortfall


class TestBuyFillShortfall(unittest.TestCase):

    def test_held_below_target_after_3_days_notifies(self):
        """持倉 < 目標×(1-offset) 且逾 3 交易日 → TG 通知"""
        notify = MagicMock()
        out = check_buy_fill_shortfall(
            "2330", held=40, target_shares=100, buy_offset=0.02,
            last_buy_date="2026-08-25", today=date(2026, 9, 1),
            notify_fn=notify, notified={}, label="BOLLINGER")
        notify.assert_called_once()
        self.assertIn("2330", notify.call_args[0][0])
        self.assertIn("40", notify.call_args[0][0])
        self.assertIn("100", notify.call_args[0][0])
        self.assertIn("2026-08-25", notify.call_args[0][0])
        self.assertIn("2330", out)

    def test_held_within_offset_no_notify(self):
        """持倉 ≥ 目標×(1-offset)（如 98/100）→ 足額不通知"""
        notify = MagicMock()
        out = check_buy_fill_shortfall(
            "2330", held=98, target_shares=100, buy_offset=0.02,
            last_buy_date="2026-08-25", today=date(2026, 9, 1),
            notify_fn=notify, notified={})
        notify.assert_not_called()
        self.assertEqual(out, {})

    def test_within_3_days_no_notify(self):
        """逾時未滿 3 交易日 → 不通知"""
        notify = MagicMock()
        out = check_buy_fill_shortfall(
            "2330", held=40, target_shares=100, buy_offset=0.02,
            last_buy_date="2026-08-31", today=date(2026, 9, 1),
            notify_fn=notify, notified={})
        notify.assert_not_called()

    def test_same_day_dedup(self):
        """同檔同日不重複通知"""
        notify = MagicMock()
        notified = {}
        check_buy_fill_shortfall(
            "2330", held=40, target_shares=100, buy_offset=0.02,
            last_buy_date="2026-08-25", today=date(2026, 9, 1),
            notify_fn=notify, notified=notified)
        check_buy_fill_shortfall(
            "2330", held=40, target_shares=100, buy_offset=0.02,
            last_buy_date="2026-08-25", today=date(2026, 9, 1),
            notify_fn=notify, notified=notified)
        self.assertEqual(notify.call_count, 1)

    def test_no_hold_or_no_target_safe(self):
        """無持倉/無目標 → 不通知不崩潰"""
        notify = MagicMock()
        check_buy_fill_shortfall("2330", held=0, target_shares=100, buy_offset=0.02,
                                 last_buy_date="2026-08-25", today=date(2026, 9, 1),
                                 notify_fn=notify, notified={})
        check_buy_fill_shortfall("2330", held=50, target_shares=0, buy_offset=0.02,
                                 last_buy_date="2026-08-25", today=date(2026, 9, 1),
                                 notify_fn=notify, notified={})
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestCalcTopupNeed(unittest.TestCase):
    """方案 B 補足判定（v3.27）：僅補「已有持股但不足」；空倉等訊號不補"""

    def setUp(self):
        from core.live_utils import calc_topup_need
        self.calc_topup_need = calc_topup_need

    def test_empty_hold_no_topup(self):
        """空倉（held=0）→ 不補（等策略訊號，2026-09-02 修正）"""
        self.assertEqual(self.calc_topup_need(0, 100, 0.02, True), 0)

    def test_held_below_target_topup(self):
        """有持股但 < 目標×(1-offset) → 補差額"""
        self.assertEqual(self.calc_topup_need(40, 100, 0.02, True), 60)

    def test_held_within_offset_no_topup(self):
        """持倉 ≥ 目標×(1-offset) → 足額不補"""
        self.assertEqual(self.calc_topup_need(98, 100, 0.02, True), 0)

    def test_market_closed_no_topup(self):
        """盤外時段 → 不補（避免盤後下單失敗）"""
        self.assertEqual(self.calc_topup_need(40, 100, 0.02, False), 0)

    def test_zero_target_no_topup(self):
        """目標 0（價格抓取失敗等）→ 不補不崩潰"""
        self.assertEqual(self.calc_topup_need(40, 0, 0.02, True), 0)


class TestAddStockAllocation(unittest.TestCase):
    """方案 B 買入分帳本記錄（v3.29）：補買必須累加 cost/shares，否則成本失真"""

    def setUp(self):
        from core.live_utils import add_stock_allocation
        self.add_stock_allocation = add_stock_allocation

    def test_new_symbol_creates_entry(self):
        """2026-09-17 起分帳本成本**含買進手續費**（`core/fees.buy_fee`）。"""
        from core import fees
        alloc = {}
        self.add_stock_allocation(alloc, '6213', 57645.0, 105)
        self.assertEqual(alloc['6213']['total_buy_cost'],
                         57645.0 + fees.buy_fee(57645.0))
        self.assertEqual(alloc['6213']['total_buy_shares'], 105)

    def test_existing_symbol_accumulates(self):
        from core import fees
        alloc = {'6213': {'total_buy_cost': 2200.0, 'total_buy_shares': 4}}
        self.add_stock_allocation(alloc, '6213', 57645.0, 105)
        self.assertEqual(alloc['6213']['total_buy_cost'],
                         2200.0 + 57645.0 + fees.buy_fee(57645.0))
        self.assertEqual(alloc['6213']['total_buy_shares'], 109)

    def test_cost_is_net_of_fee_by_default(self):
        """反回歸：分帳本不可退回「不含費用」的毛成本（否則可買股虛高）。"""
        from core import fees
        alloc = {}
        self.add_stock_allocation(alloc, '6213', 57645.0, 105)
        self.assertGreater(alloc['6213']['total_buy_cost'], 57645.0)
        self.assertEqual(fees.buy_fee(57645.0), 82.0)   # 57,645 × 0.1425% = 82.1 → 82

    def test_empty_alloc_safe(self):
        self.add_stock_allocation(None, '2454', 79380.0, 18)
        self.add_stock_allocation({}, '2454', 79380.0, 18)
        # 不崩潰即通過（None 時無法寫入，僅安全返回）
