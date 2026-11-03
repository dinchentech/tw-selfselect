"""回歸測試：下單結果的回復機制（2026-10-19 實盤事故）。

## 事故 A：記帳價用「決策價」而非「實際送單價」

2026-10-19 換股：6505 決策價 123.0（選股日收盤），provider 送單前重新取價 123.50 ⇒
`performance.csv` 記 123.0、券商成交 123.50 ⇒ 成本少記 338 元，
`scripts/reconcile_broker_books.py` 每天報「CSV 價 123.0 ≠ 券商 123.5」。
⇒ provider 要把**實際送單價**回報給上層（`sent_price`，對稱於 `sent_qty`）。

## 事故 B：下單逾時（結果未明）可能造成隔天雙倍買進

`data/esun_provider.place_order` 逾時 30 秒只回 `{"error": ...}` 就放棄，但**下單執行緒仍在跑**，
稍後可能真的成交（2026-10-19 09:01 的 8046 就印了「下單成功」，只是最後沒撮合）。
若真的成交：帳本 0 股、券商有股 ⇒ 隔天「未持股的輪替標的每天重試補足」再買一次 ⇒ **2 倍部位**。
⇒ 逾時要落地一筆「結果未明」，下次要買該檔前先向券商校正，未校正前不得下單。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from core.live_utils import (broker_holding_qty, clear_unknown_order, load_unknown_orders,
                             order_fill_price, record_unknown_order, sell_with_fill_check,
                             unknown_order_blocks_buy)


class OrderFillPriceTest(unittest.TestCase):
    """A：記帳價優先用 provider 回報的實際送單價。"""

    def test_uses_sent_price_when_present(self):
        self.assertAlmostEqual(order_fill_price({'sent_price': 123.5}, 123.0), 123.5)

    def test_falls_back_to_decision_price(self):
        self.assertAlmostEqual(order_fill_price({}, 123.0), 123.0)
        self.assertAlmostEqual(order_fill_price(None, 123.0), 123.0)

    def test_ignores_bad_sent_price(self):
        self.assertAlmostEqual(order_fill_price({'sent_price': 0}, 123.0), 123.0)
        self.assertAlmostEqual(order_fill_price({'sent_price': 'abc'}, 123.0), 123.0)
        self.assertAlmostEqual(order_fill_price({'sent_price': None}, 123.0), 123.0)


class _FakeBroker:
    def __init__(self, rows=None, raises=False):
        self._rows = rows
        self._raises = raises

    def query_inventories(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._rows


class BrokerHoldingQtyTest(unittest.TestCase):
    """券商庫存股數一律取 `qty_b`（沿用對帳工具的單位陷阱規則）。"""

    def test_qty_b_used(self):
        b = _FakeBroker([{'stk_no': '8046', 'qty_b': '64', 'price_avg': '1305'},
                         {'stk_no': '1301', 'qty_b': '1000'}])
        self.assertEqual(broker_holding_qty(b, '8046'), 64)
        self.assertEqual(broker_holding_qty(b, '1301'), 1000)

    def test_missing_symbol_is_zero(self):
        self.assertEqual(broker_holding_qty(_FakeBroker([{'stk_no': '1301', 'qty_b': '1000'}]), '8046'), 0)

    def test_unknown_when_query_fails(self):
        self.assertIsNone(broker_holding_qty(_FakeBroker(raises=True), '8046'))
        self.assertIsNone(broker_holding_qty(_FakeBroker(None), '8046'))
        self.assertIsNone(broker_holding_qty(object(), '8046'))   # 沒有 query_inventories


class _FakeSellBroker:
    """賣單用：`place_order` 回傳 provider 的 `sent_price`（實際送單價）。"""

    def __init__(self, ret, fill=None):
        self._ret = ret
        self._fill = fill

    def place_order(self, symbol, action, quantity):
        return self._ret

    def check_fill(self, symbol, action, order_ret, requested):
        return self._fill


class SellWithFillCheckTest(unittest.TestCase):
    """`sell_with_fill_check()` 要把 provider 的下單回傳帶回去（2026-11-03）。

    孤兒清倉用它取 `sent_price` 記帳；不回傳就只能用「上層送單前取到的舊報價」
    （6505 實測：上層 99.9、實際送單 99.60）。
    """

    def test_returns_order_ret_with_sent_price(self):
        ret = {'sent_price': 99.6, 'status': 'filled'}
        filled, _notified, order_ret = sell_with_fill_check(
            _FakeSellBroker(ret), '6505', 2000, {}, '2026-11-03', None, '清倉')
        self.assertEqual(filled, 2000)
        self.assertIs(order_ret, ret)
        self.assertAlmostEqual(order_fill_price(order_ret, 99.9), 99.6)

    def test_partial_fill_still_returns_order_ret(self):
        ret = {'sent_price': 72.0}
        filled, _notified, order_ret = sell_with_fill_check(
            _FakeSellBroker(ret, fill=500), '1301', 2000, {}, '2026-11-03', None, '清倉')
        self.assertEqual(filled, 500)
        self.assertIs(order_ret, ret)

    def test_unfilled_returns_zero_and_order_ret(self):
        ret = {'error': 'boom'}
        filled, _notified, order_ret = sell_with_fill_check(
            _FakeSellBroker(ret), '6505', 2000, {}, '2026-11-03', None, '清倉')
        self.assertEqual(filled, 0)
        self.assertIs(order_ret, ret)


class UnknownOrderStateTest(unittest.TestCase):
    """B：逾時（結果未明）狀態的落地與判讀。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, 'order_unknown.json')

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_load_clear_roundtrip(self):
        self.assertEqual(load_unknown_orders(self.path), {})
        record_unknown_order('8046', 64, '2026-10-19', path=self.path)
        recs = load_unknown_orders(self.path)
        self.assertIn('8046', recs)
        self.assertEqual(recs['8046']['qty'], 64)
        self.assertEqual(recs['8046']['date'], '2026-10-19')
        clear_unknown_order('8046', path=self.path)
        self.assertEqual(load_unknown_orders(self.path), {})

    def test_same_day_blocks_buy(self):
        """逾時當天不可再買（當日已放棄那筆，重買一定重複）。"""
        record_unknown_order('8046', 64, '2026-10-19', path=self.path)
        recs = load_unknown_orders(self.path)
        self.assertTrue(unknown_order_blocks_buy('8046', recs, '2026-10-19'))
        self.assertFalse(unknown_order_blocks_buy('6505', recs, '2026-10-19'))

    def test_next_day_does_not_block_by_itself(self):
        """隔天要先去券商校正（券商查不到股數 ⇒ 視為未成交），不是無條件擋。"""
        record_unknown_order('8046', 64, '2026-10-19', path=self.path)
        recs = load_unknown_orders(self.path)
        self.assertFalse(unknown_order_blocks_buy('8046', recs, '2026-10-20'))

    def test_corrupt_file_is_treated_as_empty(self):
        Path(self.path).write_text('{not json', encoding='utf-8')
        self.assertEqual(load_unknown_orders(self.path), {})


class WiringTest(unittest.TestCase):
    """確認主程式／provider 真的接上了（純文字守門，防只改 helper 沒接線）。"""

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        self.main = (self.root / 'selfselect_trader.py').read_text(encoding='utf-8')
        self.provider = (self.root / 'data' / 'esun_provider.py').read_text(encoding='utf-8')
        self.live_utils = (self.root / 'core' / 'live_utils.py').read_text(encoding='utf-8')

    def test_provider_reports_sent_price_and_unknown_timeout(self):
        self.assertIn('result_holder["sent_price"]', self.provider)
        self.assertIn('"unknown": True', self.provider)

    def test_main_records_unknown_and_reconciles_before_buy(self):
        self.assertIn('order_fill_price(order_result, px)', self.main)
        self.assertIn('record_unknown_order(symbol, position_size, today_str', self.main)
        self.assertIn('unknown_order_blocks_buy(symbol, _unk, today_str)', self.main)
        self.assertIn('broker_holding_qty(broker, symbol)', self.main)
        self.assertIn('clear_unknown_order(symbol)', self.main)

    def test_all_bookkeeping_paths_use_sent_price(self):
        """2026-11-03：孤兒清倉／加碼／補足／停泊 都用實際送單價記帳（不只策略訊號那條）。"""
        self.assertIn('return shares, notified, order_ret', self.live_utils,
                      'sell_with_fill_check() 要回傳 order_ret（孤兒清倉靠它取 sent_price）')
        self.assertIn('def book_price(', self.main)
        for call in ('sell_with_fill_check(', 'place_buy(symbol, buy_shares',
                     "place_buy(symbol, _need", "broker.place_order(sym, 'sell', sh)"):
            self.assertIn(call, self.main)
        for site in ('book_price(_order_ret, old_px', 'book_price(_kw_ret, px',
                     'book_price(_order_ret, px', 'book_price(ret, px'):
            self.assertIn(site, self.main, f'缺少記帳價修正：{site}')



if __name__ == '__main__':
    unittest.main()
