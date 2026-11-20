"""回歸測試：玉山取不到價 ⇒ 改抓 TWSE MIS（v1.1.42，2026-11-16）。

## 背景

2408 每天 09:00 開盤首圈必定逾時（8+8 秒），`get_current_price` 回 `0.0` ⇒ 那一分鐘的合成當日 K
不更新（v1.1.41 只加了「缺價→恢復」的診斷，看得出來但救不回來）。

MIS（TWSE 官方即時行情）是這個 repo **現成的**第二來源（持倉報告／儀表板走
`core.inst_data.fetch_intraday_quotes`）。⇒ 玉山全部失敗時改抓 MIS 當日最後成交價。

## 不變式（改動時不可破壞）

1. **永不退昨收（`y`）**。拿昨收當今天價格，停泊／買進股數會用錯價，比回 `0` 更糟。
   可用順序＝**`z`（當日最後成交價）→ 成形價（最佳買賣價中價）→ 不給**。
   （成形價是 2026-11-17 補的：`z` 只在「剛好有撮合到」的 snapshot 才有——實測抽 12 檔只有 3 檔
   有值，2615／2609／2603 連測 8 次全沒有、2408 是 8/8 ⇒ 只認 `z` 的備援對那三檔等於不存在；
   五檔 `b`/`a` 同期 12/12 都有值。）
2. MIS 也拿不到時，**行為與 v1.1.41 完全相同**：回 `0.0`。
3. 備援只在**失敗路徑**才打網路；玉山正常時 MIS 一次都不該被呼叫（下單窗口逐檔串行的時間預算）。
4. 任何例外都不可外拋（報價路徑不能因為備援而炸）。
"""
import contextlib
import io
import importlib
import os
import unittest
from unittest.mock import patch

try:
    import data.esun_provider as P
    from data.esun_provider import EsunProvider
except ModuleNotFoundError:               # CI 沒裝玉山 SDK
    P, EsunProvider = None, None


class _QuoteStub:
    """玉山行情樁：依序回傳／拋出 side_effects（dict＝回應、Exception＝拋）。"""

    def __init__(self, side_effects):
        self.side_effects = list(side_effects)
        self.calls = 0

    def __call__(self, symbol):
        self.calls += 1
        eff = self.side_effects.pop(0) if self.side_effects else {'lastPrice': 99.0}
        if isinstance(eff, Exception):
            raise eff
        return eff


def _make_provider(side_effects, cls=None):
    cls = cls or EsunProvider
    if cls is None:
        raise unittest.SkipTest("需要玉山 SDK（esun_marketdata / esun_trade）")
    import types
    p = cls.__new__(cls)                        # 繞過 __init__（需 keyring/config）
    p._login_failed = False
    p._session_date = cls._today()
    p.login = lambda: True
    stub = _QuoteStub(side_effects)
    p._marketdata = types.SimpleNamespace(
        rest_client=types.SimpleNamespace(
            stock=types.SimpleNamespace(intraday=types.SimpleNamespace(quote=stub))))
    return p, stub


class MisFallbackTest(unittest.TestCase):
    """玉山失敗 → MIS 當日成交價備援。"""

    def setUp(self):
        if P is None:
            raise unittest.SkipTest("需要玉山 SDK（esun_marketdata / esun_trade）")
        P._quote_missing.clear()

    def tearDown(self):
        P._quote_missing.clear()

    def _mis(self, mapping):
        """把 MIS 換成樁；回傳 mock 以便斷言有沒有被呼叫。"""
        m = patch('core.inst_data.fetch_intraday_quotes', return_value=mapping)
        started = m.start()
        self.addCleanup(m.stop)
        return started

    def test_timeout_twice_falls_back_to_mis_price(self):
        import requests
        mis = self._mis({'2408': {'price': 377.0, 'date': '2026-11-16', 'time': '09:00:05'}})
        p, stub = _make_provider([requests.exceptions.ReadTimeout('t1'),
                                  requests.exceptions.ReadTimeout('t2')])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            px = p.get_current_price('2408')
        self.assertEqual(px, 377.0, '玉山兩次逾時 ⇒ 應該拿到 MIS 的當日成交價')
        self.assertEqual(stub.calls, 2, '玉山仍只重試一次，不可因備援多打')
        self.assertIn('🩹 2408 玉山取價失敗（逾時／斷線）⇒ 改用 TWSE MIS 備援價 377.00', buf.getvalue())
        self.assertEqual(P._quote_missing, {}, '備援拿到價 ⇒ 不再算缺價')
        mis.assert_called_once()
        self.assertFalse(mis.call_args.kwargs.get('allow_prev_close', True),
                         '備援必須禁止退回昨收')

    def test_mis_unavailable_keeps_old_behaviour(self):
        import requests
        self._mis({})                                  # MIS 也拿不到
        p, _ = _make_provider([requests.exceptions.ReadTimeout('t1'),
                               requests.exceptions.ReadTimeout('t2')])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            px = p.get_current_price('2408')
        self.assertEqual(px, 0.0, 'MIS 也沒有 ⇒ 與 v1.1.41 相同：回 0')
        self.assertNotIn('🩹', buf.getvalue())
        self.assertIn('2408', P._quote_missing, '仍算缺價，等下一圈（或恢復時印 ✅）')

    def test_mis_exception_is_swallowed(self):
        p, _ = _make_provider([ValueError('A00002 response parse Error')])
        with patch('core.inst_data.fetch_intraday_quotes', side_effect=RuntimeError('boom')):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(p.get_current_price('2408'), 0.0, '備援炸掉不可外拋')

    def test_mis_not_called_when_esun_works(self):
        mis = self._mis({'2408': {'price': 377.0}})
        p, stub = _make_provider([{'lastPrice': 376.5}])
        self.assertEqual(p.get_current_price('2408'), 376.5)
        mis.assert_not_called()
        self.assertEqual(stub.calls, 1)

    def test_missing_last_price_also_triggers_fallback(self):
        """玉山「有回應但沒有 lastPrice」＝靜默回 0 的老路徑，也要救。"""
        mis = self._mis({'2408': {'price': 377.0}})
        p, stub = _make_provider([{'lastPrice': 0}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            px = p.get_current_price('2408')
        self.assertEqual(px, 377.0)
        self.assertIn('回應沒有 lastPrice', buf.getvalue())
        mis.assert_called_once()

    def test_zero_mis_price_is_ignored(self):
        self._mis({'2408': {'price': 0}})
        p, _ = _make_provider([ValueError('x')])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.get_current_price('2408'), 0.0)

    def test_bid_ask_mid_fallback_is_labelled(self):
        """成形價（`z` 沒有、只有買賣價）要回得出價，且 log 講清楚不是成交價。"""
        self._mis({'2615': {'price': 109.25, 'date': '2026-11-17', 'time': '11:36:11',
                            'prev_close': False, 'source': 'bid_ask_mid'}})
        p, _ = _make_provider([ValueError('A00002 response parse Error')])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(p.get_current_price('2615'), 109.25)
        out = buf.getvalue()
        self.assertIn('🩹 2615 玉山取價失敗（其他錯誤）⇒ 改用 TWSE MIS 成形價 109.25', out)
        self.assertIn('最佳買賣價中價', out)
        self.assertNotIn('備援價 109.25', out, '成形價不可印成「成交價」')
        self.assertEqual(P._quote_missing, {}, '有價就不算缺價')


class MisFallbackKnobTest(unittest.TestCase):
    """`.env` 的 `ESUN_MIS_QUOTE_FALLBACK=0` 可以整支關掉。"""

    def test_knob_disables_fallback(self):
        if P is None:
            raise unittest.SkipTest("需要玉山 SDK（esun_marketdata / esun_trade）")
        try:
            with patch.dict(os.environ, {'ESUN_MIS_QUOTE_FALLBACK': '0'}):
                mod = importlib.reload(P)
                self.assertFalse(mod.MIS_QUOTE_FALLBACK)
                with patch('core.inst_data.fetch_intraday_quotes',
                           return_value={'2408': {'price': 377.0}}):
                    p, _ = _make_provider([ValueError('x')], cls=mod.EsunProvider)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(p.get_current_price('2408'), 0.0, '關掉後不可用 MIS')
        finally:
            importlib.reload(P)      # ⚠️ 必須在 patch 之外還原，否則模組會帶著 =0 留給其他測試
        self.assertTrue(P.MIS_QUOTE_FALLBACK, '還原後預設應為開啟')

    def test_env_example_documents_knob(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / '.env.example.txt').read_text(encoding='utf-8')
        self.assertIn('ESUN_MIS_QUOTE_FALLBACK', src, '.env.example.txt 必須說明這個旋鈕')


class MisParserTest(unittest.TestCase):
    """`core.inst_data._parse_mis_quotes`：`z`（當日成交）／成形價／`y`（昨收）三者不可混用。"""

    def _payload(self):
        return {'msgArray': [
            {'c': '2408', 'z': '377.0000', 'y': '372.0000', 'd': '20261116', 't': '09:00:05',
             'b': '376.0000_375.5000_', 'a': '377.5000_378.0000_'},
            {'c': '2615', 'z': '-', 'y': '107.5000', 'd': '20261116', 't': '09:00:02',
             'b': '109.0000_108.5000_', 'a': '109.5000_110.0000_'},
            {'c': '9999', 'z': '-', 'y': '-', 'd': '20261116', 't': '09:00:02'},
        ]}

    def test_prev_close_allowed_by_default(self):
        from core.inst_data import _parse_mis_quotes
        out = _parse_mis_quotes(self._payload(), ['2408', '2615', '9999'])
        self.assertEqual(out['2408']['price'], 377.0)
        self.assertFalse(out['2408']['prev_close'])
        self.assertEqual(out['2408']['source'], 'last')
        self.assertEqual(out['2615']['price'], 107.5, '預設行為：無成交退回昨收（報告端不變）')
        self.assertTrue(out['2615']['prev_close'])
        self.assertEqual(out['2615']['source'], 'prev_close')
        self.assertNotIn('9999', out)

    def test_prev_close_forbidden_uses_bid_ask_mid_then_drops(self):
        from core.inst_data import _parse_mis_quotes
        out = _parse_mis_quotes(self._payload(), ['2408', '2615', '9999'], allow_prev_close=False)
        self.assertEqual(sorted(out), ['2408', '2615'], '沒有成交價但有買賣價 ⇒ 用成形價')
        self.assertEqual(out['2408']['price'], 377.0, '有 z 就用 z，不看買賣價')
        self.assertEqual(out['2615']['price'], 109.25, '成形價＝(109.0+109.5)/2')
        self.assertFalse(out['2615']['prev_close'])
        self.assertEqual(out['2615']['source'], 'bid_ask_mid')
        self.assertNotIn('9999', out, '連買賣價都沒有 ⇒ 不給（絕不退昨收）')

    def test_single_sided_book_uses_the_side_that_exists(self):
        """漲跌停鎖死時只有單邊掛價——那仍是今天的價，可用。"""
        from core.inst_data import _parse_mis_quotes
        payload = {'msgArray': [{'c': '2603', 'z': '-', 'y': '257.0000', 'd': '20261117',
                                 'b': '261.0000_260.5000_', 'a': '-'}]}
        out = _parse_mis_quotes(payload, ['2603'], allow_prev_close=False)
        self.assertEqual(out['2603']['price'], 261.0)
        self.assertEqual(out['2603']['source'], 'bid_ask_mid')

    def test_real_2615_record_from_2026_11_17(self):
        """VM 當天真實 payload 形狀（`z='-'`、`v=9505`、五檔有值）⇒ 備援必須拿得到價。"""
        from core.inst_data import _parse_mis_quotes
        payload = {'msgArray': [{
            'c': '2615', 'n': '萬海', 'd': '20261117', 't': '11:36:11', 'v': '9505',
            'z': '-', 'y': '109.5000', 'o': '108.5000', 'h': '111.0000', 'l': '106.5000',
            'b': '109.0000_108.5000_108.0000_107.5000_107.0000_',
            'a': '109.5000_110.0000_110.5000_111.0000_111.5000_',
        }]}
        out = _parse_mis_quotes(payload, ['2615'], allow_prev_close=False)
        self.assertEqual(out['2615']['price'], 109.25)
        self.assertEqual(out['2615']['date'], '2026-11-17')

    def test_empty_payload_is_safe(self):
        from core.inst_data import _parse_mis_quotes
        self.assertEqual(_parse_mis_quotes({}, ['2408'], allow_prev_close=False), {})
        self.assertEqual(_parse_mis_quotes(None, [], allow_prev_close=False), {})


if __name__ == '__main__':
    unittest.main()
