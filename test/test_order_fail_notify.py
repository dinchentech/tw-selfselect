"""測試：notify_order_failure — 交易失敗 TG 警示（每日每檔一次）"""
import os
import unittest
from unittest.mock import MagicMock

from core.live_utils import notify_order_failure


class TestNotifyOrderFailure(unittest.TestCase):
    def test_sends_once_per_symbol_per_day(self):
        sent = []
        notified = {}
        notified = notify_order_failure("2330", "test error", notified, "2026-08-23", sent.append, action="買入")
        notified = notify_order_failure("2330", "test error 2", notified, "2026-08-23", sent.append, action="買入")
        self.assertEqual(len(sent), 1, '同檔同日只發一次')
        self.assertEqual(notified, {"2330": "2026-08-23"})
        self.assertIn("2330", sent[0])
        self.assertIn("買入失敗", sent[0])

    def test_sends_again_next_day(self):
        sent = []
        notified = {}
        notified = notify_order_failure("2330", "e1", notified, "2026-08-23", sent.append)
        notified = notify_order_failure("2330", "e2", notified, "2026-08-24", sent.append)
        self.assertEqual(len(sent), 2, '次日重新警示')

    def test_different_symbols_independent(self):
        sent = []
        notified = {}
        notify_order_failure("2330", "e", notified, "2026-08-23", sent.append)
        notify_order_failure("2317", "e", notified, "2026-08-23", sent.append)
        self.assertEqual(len(sent), 2)

    def test_buy_hint(self):
        sent = []
        notify_order_failure("2330", "e", {}, "2026-08-23", sent.append, action="買入")
        self.assertIn("自動重試至收盤", sent[0])

    def test_sell_hint(self):
        sent = []
        notify_order_failure("2330", "e", {}, "2026-08-23", sent.append, action="清倉賣出")
        self.assertIn("下一個交易日 09:00", sent[0])

    def test_custom_hint(self):
        sent = []
        notify_order_failure("2330", "e", {}, "2026-08-23", sent.append, action="交易", retry_hint="請檢查券商帳戶。")
        self.assertIn("請檢查券商帳戶", sent[0])

    def test_notify_fn_exception_safe(self):
        bad = MagicMock(side_effect=Exception("tg down"))
        notified = notify_order_failure("2330", "e", {}, "2026-08-23", bad)
        self.assertEqual(notified, {"2330": "2026-08-23"}, 'TG 失敗不影響去重狀態')


if __name__ == '__main__':
    unittest.main()


class TestResolveFill(unittest.TestCase):
    def test_error_dict_means_zero(self):
        from core.live_utils import resolve_fill
        r = resolve_fill(MagicMock(), "2330", "buy", {"error": "timeout"}, 100)
        self.assertEqual(r, 0)

    def test_mock_filled_dict(self):
        from core.live_utils import resolve_fill
        r = resolve_fill(MagicMock(), "2330", "buy", {"status": "filled", "order_id": 1}, 100)
        self.assertEqual(r, 100)

    def test_broker_check_fill_partial(self):
        from core.live_utils import resolve_fill
        broker = MagicMock()
        broker.check_fill.return_value = 40
        r = resolve_fill(broker, "2330", "buy", {"order_id": 1}, 100)
        self.assertEqual(r, 40)

    def test_broker_check_fill_zero(self):
        from core.live_utils import resolve_fill
        broker = MagicMock()
        broker.check_fill.return_value = 0
        self.assertEqual(resolve_fill(broker, "2330", "buy", {}, 100), 0)

    def test_no_check_fill_returns_none(self):
        from core.live_utils import resolve_fill
        r = resolve_fill(MagicMock(spec=[]), "2330", "buy", {}, 100)
        self.assertIsNone(r)

    def test_check_fill_returns_none(self):
        from core.live_utils import resolve_fill
        broker = MagicMock()
        broker.check_fill.return_value = None
        self.assertIsNone(resolve_fill(broker, "2330", "buy", {}, 100))

    def test_check_fill_raises_returns_none(self):
        from core.live_utils import resolve_fill
        broker = MagicMock()
        broker.check_fill.side_effect = Exception("query down")
        self.assertIsNone(resolve_fill(broker, "2330", "buy", {}, 100))

    def test_esun_check_fill_parses_transactions(self):
        from data.esun_provider import EsunProvider
        p = EsunProvider.__new__(EsunProvider)
        p._trade_sdk = MagicMock()
        tx = {"stock_no": "2330", "match_quantity": 50}
        p._trade_sdk.get_transactions_by_date.return_value = [tx, {"stock_no": "2317", "match_quantity": 30}]
        self.assertEqual(p.check_fill("2330", "buy", {}, 100), 50)

    def test_esun_check_fill_unknown_format_safe(self):
        from data.esun_provider import EsunProvider
        p = EsunProvider.__new__(EsunProvider)
        p._trade_sdk = MagicMock()
        p._trade_sdk.get_transactions_by_date.return_value = [{"foo": 1}]
        self.assertIsNone(p.check_fill("2330", "buy", {}, 100), '格式不明 → None 維持原行為')


