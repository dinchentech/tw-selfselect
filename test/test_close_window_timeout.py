"""回歸測試：收盤前下單窗口的時間預算（2026-10-19）。

## 背景

日 K 策略只在 **13:25–13:30**（收盤前 5 分鐘）判定與下單（`core.live_utils.close_order_window_open`）。
實測正常每檔 1–2 秒，但 2026-10-19 有個 30 秒的卡單（8046）⇒ 每卡一檔就吃掉 30 秒。
玉山下單的外層等待上限 `ESUN_PLACE_ORDER_TIMEOUT`（`data/esun_provider.PLACE_ORDER_TIMEOUT`）
原本 30 秒 ⇒ 多檔同時卡住時，後面的標的會來不及在 13:30 前送出。
⇒ 預設維持 30（行為不變），但**可用 `.env` 調降**（現行 .env 用 15 秒）。

⚠️ 報價（`get_current_price`）的讀取逾時：原本是玉山 SDK 內建的 30 秒
   （現在由主程式的 `NET_TIMEOUT_SEC` 補上；2026-11-02 起報價改走較短的
   `NET_QUOTE_TIMEOUT_SEC`，見下方 `QuoteTimeoutBudgetTest`／`QuoteRetryTest`）。

✅ 缺價→恢復的紀錄（v1.1.41，2026-11-16）：成功的報價不留紀錄，只印「恢復」那一行
   （`QuoteRecoveryNoticeTest`）。
"""
import importlib
import io
import contextlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent


def _reload_timeout():
    try:
        import data.esun_provider as P
    except ModuleNotFoundError:      # 玉山 SDK 非公開套件 ⇒ 沒有它就略過這兩支測試（CI）
        raise unittest.SkipTest("需要玉山 SDK（esun_marketdata / esun_trade）")
    return importlib.reload(P).PLACE_ORDER_TIMEOUT


class PlaceOrderTimeoutKnobTest(unittest.TestCase):

    def test_env_value_honoured(self):
        with patch.dict(os.environ, {'ESUN_PLACE_ORDER_TIMEOUT': '15'}):
            self.assertEqual(_reload_timeout(), 15)

    def test_default_is_30_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != 'ESUN_PLACE_ORDER_TIMEOUT'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_reload_timeout(), 30)

    def test_env_example_documents_knob(self):
        src = (_ROOT / '.env.example.txt').read_text(encoding='utf-8')
        self.assertIn('ESUN_PLACE_ORDER_TIMEOUT', src, '.env.example.txt 必須說明這個旋鈕')

    def test_live_env_value_is_within_window_budget(self):
        """實盤 `.env`（若存在）不可把下單逾時設得比 30 秒還長——5 分鐘窗口塞不下。"""
        env_file = _ROOT / '.env'
        if not env_file.exists():
            self.skipTest('沒有 .env')
        for line in env_file.read_text(encoding='utf-8').splitlines():
            s = line.strip()
            if s.startswith('ESUN_PLACE_ORDER_TIMEOUT='):
                val = s.split('=', 1)[1].split('#')[0].strip()
                self.assertLessEqual(float(val), 30.0, f'逾時 {val}s 太長（窗口只有 5 分鐘）')


class CloseOrderFromEnvTest(unittest.TestCase):
    """`.env.example.txt` 長期寫著 `CLOSE_ORDER_FROM` 可調，但程式是寫死常數（改了沒反應）。

    2026-10-19 改成讀 env；預設值仍 13:25 ⇒ 沒設定的環境行為完全不變。
    """

    def _reload_from(self, value):
        import core.live_utils as L
        with patch.dict(os.environ, {'CLOSE_ORDER_FROM': value}):
            return importlib.reload(L).CLOSE_ORDER_FROM

    def test_env_overrides(self):
        self.assertEqual(self._reload_from('13:20'), '13:20')

    def test_default_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != 'CLOSE_ORDER_FROM'}
        with patch.dict(os.environ, env, clear=True):
            import core.live_utils as L
            self.assertEqual(importlib.reload(L).CLOSE_ORDER_FROM, '13:25')


class CloseOrderWindowBoundsTest(unittest.TestCase):
    """窗口本身只有起點（>= 13:25）；收盤 13:30 是硬邊界，這裡把語義釘住。"""

    def test_window_is_bounded_1325_to_1330(self):
        """窗口＝[13:25, 13:30]。

        🔧 **2026-11-04 更正**：本測試原本叫 `test_window_opens_at_1325_and_has_no_upper_bound`，
        並斷言 13:31 仍在窗口內（= 刻意沒有上限）。實盤證明那是錯的：
        沒有上限 ⇒ 13:45 收盤報告那一輪停泊單照樣送出 ⇒ 玉山 `000017: 非該盤別盤中或預約時間`
        （強制重登後重試同樣被退）。改成有上限，並保留 13:30 那一刻仍在窗口內。
        """
        # 明確帶 start：本測試驗「窗口語義」，不受其他測試改動模組常數影響
        from datetime import datetime
        from core.live_utils import close_order_window_open
        self.assertFalse(close_order_window_open(datetime(2026, 10, 19, 13, 24), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 25), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 29), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 30), start='13:25'))
        self.assertFalse(close_order_window_open(datetime(2026, 10, 19, 13, 31), start='13:25'),
                         '13:31 已收盤 ⇒ 不得再判定可下單（000017 的來源）')


class QuoteTimeoutBudgetTest(unittest.TestCase):
    """報價用「較短的獨立上限」（2026-11-02）。

    事故：2026-11-02 09:00 開盤首圈，第一筆報價（`api.fugle.tw`）**30 秒無回應**才被
    全域 `NET_TIMEOUT_SEC=30` 切掉。13:25–13:30 下單窗口是**逐檔串行**取價 ⇒ 一檔卡 30 秒
    就吃掉窗口 1/10、五檔全卡就沒了 150 秒。⇒ 報價端點改走 `NET_QUOTE_TIMEOUT_SEC`（預設 8）。
    """

    def _mod(self):
        try:
            import selfselect_trader as T
        except ModuleNotFoundError as e:     # 玉山 SDK 非公開套件 ⇒ CI 略過
            raise unittest.SkipTest(f"需要玉山 SDK：{e}")
        return T

    def test_quote_urls_get_short_timeout_and_others_keep_default(self):
        f = self._mod().request_timeout_for
        with patch.dict(os.environ, {'NET_TIMEOUT_SEC': '30', 'NET_QUOTE_TIMEOUT_SEC': '8'}):
            self.assertEqual(f('https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/1802'), 8.0)
            self.assertEqual(f('https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/TSE'), 8.0)
            # 非報價（歷史 K／下單 API／FinMind）不受影響
            self.assertEqual(f('https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/1802'), 30.0)
            self.assertEqual(f('https://api.finmindtrade.com/api/v4/data'), 30.0)

    def test_default_quote_timeout_is_8(self):
        env = {k: v for k, v in os.environ.items() if k != 'NET_QUOTE_TIMEOUT_SEC'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(self._mod().request_timeout_for('/stock/intraday/quote/1101'), 8.0)

    def test_zero_disables_the_cap(self):
        with patch.dict(os.environ, {'NET_QUOTE_TIMEOUT_SEC': '0'}):
            self.assertIsNone(self._mod().request_timeout_for('/stock/intraday/quote/1101'))

    def test_garbage_value_falls_back_to_30(self):
        with patch.dict(os.environ, {'NET_QUOTE_TIMEOUT_SEC': 'abc'}):
            self.assertEqual(self._mod().request_timeout_for('/stock/intraday/quote/1101'), 30.0)

    def test_env_is_read_at_call_time_so_hot_reload_applies(self):
        f = self._mod().request_timeout_for
        with patch.dict(os.environ, {'NET_QUOTE_TIMEOUT_SEC': '8'}):
            self.assertEqual(f('/stock/intraday/quote/1802'), 8.0)
        with patch.dict(os.environ, {'NET_QUOTE_TIMEOUT_SEC': '5'}):
            self.assertEqual(f('/stock/intraday/quote/1802'), 5.0)

    def test_patch_injects_the_timeout_into_requests(self):
        """monkey patch 真的把 timeout 送進 requests，且不覆寫呼叫端自己指定的值。"""
        T = self._mod()
        seen = {}

        def _recorder(self, method, url, **kwargs):
            seen['url'] = url
            seen['timeout'] = kwargs.get('timeout')
            return 'ok'

        orig = T._orig_session_request
        T._orig_session_request = _recorder
        try:
            with patch.dict(os.environ, {'NET_TIMEOUT_SEC': '30', 'NET_QUOTE_TIMEOUT_SEC': '8'}):
                T._session_request_with_timeout(None, 'GET', 'https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/1802')
                self.assertEqual(seen['timeout'], 8.0, '報價應帶 8 秒上限')
                T._session_request_with_timeout(None, 'GET', 'https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/1802')
                self.assertEqual(seen['timeout'], 30.0, '其他呼叫維持 30 秒')
                T._session_request_with_timeout(None, 'GET', 'https://api.fugle.tw/x/intraday/quote/1', timeout=3)
                self.assertEqual(seen['timeout'], 3, '呼叫端指定的 timeout 不可被覆寫')
        finally:
            T._orig_session_request = orig


try:
    from data.esun_provider import EsunProvider
except ModuleNotFoundError:              # CI 沒裝玉山 SDK
    EsunProvider = None


class _QuoteStub:
    """依序回傳／拋出 side_effects 裡的值（dict＝成功回應、Exception＝拋）。"""

    def __init__(self, side_effects):
        self.side_effects = list(side_effects)
        self.calls = 0

    def __call__(self, symbol):
        self.calls += 1
        eff = self.side_effects.pop(0) if self.side_effects else {'lastPrice': 99.0}
        if isinstance(eff, Exception):
            raise eff
        return eff


def _make_provider(side_effects):
    """建一個不碰 keyring／config 的 provider，`quote()` 依 `side_effects` 回應。"""
    if EsunProvider is None:
        raise unittest.SkipTest("需要玉山 SDK（esun_marketdata / esun_trade）")
    import types
    p = EsunProvider.__new__(EsunProvider)      # 繞過 __init__（需 keyring/config）
    p._login_failed = False
    p._session_date = EsunProvider._today()     # 已有今日 session ⇒ 不觸發跨日重登
    p.login = lambda: True
    stub = _QuoteStub(side_effects)
    p._marketdata = types.SimpleNamespace(
        rest_client=types.SimpleNamespace(
            stock=types.SimpleNamespace(intraday=types.SimpleNamespace(quote=stub))))
    return p, stub


class QuoteRetryTest(unittest.TestCase):
    """`get_current_price` 對逾時／斷線重試一次（2026-11-02）。

    一次卡滿就吃掉下單窗口 1/10 ⇒ 重試一次（8+8=16 秒）換一個「不白白損失一輪」的機會；
    **只**對網路層錯誤重試——參數錯／token 失效重試無意義（那是別條路徑處理的）。
    """

    def _provider(self, side_effects):
        return _make_provider(side_effects)

    def setUp(self):
        import data.esun_provider as P
        P._quote_missing.clear()      # 缺價狀態是模組級 ⇒ 每個測試都從乾淨狀態開始
        # v1.1.42 起失敗會走 MIS 備援 ⇒ 這裡把它關掉（回空 dict＝備援也拿不到價），
        # 才驗得到「兩次都失敗就回 0」這個原始契約；備援本身由 test_quote_mis_fallback.py 驗。
        self._mis = patch('core.inst_data.fetch_intraday_quotes', return_value={})
        self._mis.start()

    def tearDown(self):
        self._mis.stop()
        import data.esun_provider as P
        P._quote_missing.clear()

    def test_timeout_then_success_returns_price(self):
        import requests
        p, stub = self._provider([requests.exceptions.ReadTimeout('read timeout=8.0'),
                                  {'lastPrice': 123.5}])
        self.assertEqual(p.get_current_price('1802'), 123.5)
        self.assertEqual(stub.calls, 2, '逾時後應重試一次')

    def test_timeout_twice_gives_up_with_zero(self):
        import requests
        p, stub = self._provider([requests.exceptions.ReadTimeout('t1'),
                                  requests.exceptions.ReadTimeout('t2')])
        self.assertEqual(p.get_current_price('1802'), 0.0)
        self.assertEqual(stub.calls, 2, '最多兩次，不可無限重試')

    def test_connection_error_is_also_retried(self):
        import requests
        p, stub = self._provider([requests.exceptions.ConnectionError('reset'),
                                  {'lastPrice': 88.0}])
        self.assertEqual(p.get_current_price('1802'), 88.0)
        self.assertEqual(stub.calls, 2)

    def test_non_network_error_is_not_retried(self):
        p, stub = self._provider([ValueError('A00002 response parse Error'),
                                  {'lastPrice': 88.0}])
        self.assertEqual(p.get_current_price('1802'), 0.0)
        self.assertEqual(stub.calls, 1, '非網路錯誤不重試')

    def test_success_on_first_try_calls_once(self):
        p, stub = self._provider([{'lastPrice': 50.0}])
        self.assertEqual(p.get_current_price('1802'), 50.0)
        self.assertEqual(stub.calls, 1)


class QuoteRecoveryNoticeTest(unittest.TestCase):
    """缺價 → 恢復時印**一行**（v1.1.41，2026-11-16）。

    事故形狀（VM 實測）：2408 每天 09:00 開盤首圈逾時一次、下一圈恢復；但**成功的報價不落紀錄**
    ⇒ 只能靠「沒有第二筆 ⚠️」反推，而 `get_current_price` 還有兩條靜默回 0 的路徑
    （`_ensure_available()` 為 False、回應沒有 `lastPrice`）⇒ 沒辦法回答「後來到底查到沒有」。
    做法：只印恢復那一行（正常盤零輸出、不洗版）。
    """

    def setUp(self):
        import data.esun_provider as P
        self.P = P
        P._quote_missing.clear()
        # v1.1.42：MIS 備援關掉（回空 dict）才驗得到「恢復」這條純玉山路徑
        self._mis = patch('core.inst_data.fetch_intraday_quotes', return_value={})
        self._mis.start()

    def tearDown(self):
        self._mis.stop()
        self.P._quote_missing.clear()

    def _call(self, side_effects):
        """回傳 (價格, stdout)；side_effects 用完就用預設成功值。"""
        p, stub = _make_provider(side_effects)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            px = p.get_current_price('1802')
        return px, buf.getvalue(), stub

    def test_no_line_when_always_ok(self):
        px, out, _ = self._call([{'lastPrice': 50.0}])
        self.assertEqual(px, 50.0)
        self.assertNotIn('報價已恢復', out, '沒有缺過價就不該印')

    def test_line_printed_when_price_comes_back(self):
        import requests
        p, stub = _make_provider([requests.exceptions.ReadTimeout('t1'),
                                  requests.exceptions.ReadTimeout('t2'),
                                  {'lastPrice': 123.5},
                                  {'lastPrice': 124.0}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(p.get_current_price('1802'), 0.0)   # 兩次逾時 ⇒ 缺價
            self.assertIn('1802', self.P._quote_missing)
            self.assertEqual(p.get_current_price('1802'), 123.5)  # 下一圈恢復
            self.assertEqual(p.get_current_price('1802'), 124.0)  # 之後正常
        out = buf.getvalue()
        self.assertEqual(out.count('報價已恢復'), 1, '恢復只印一次，不可每圈重印')
        self.assertIn('✅ 1802 報價已恢復（123.50，缺價', out)
        self.assertEqual(self.P._quote_missing, {}, '恢復後狀態要清掉')

    def test_zero_price_is_not_a_recovery(self):
        """回應沒有 `lastPrice` ⇒ 回 0，看起來像「成功」但其實還是沒價。"""
        import requests
        p, _ = _make_provider([requests.exceptions.ReadTimeout('t1'),
                               requests.exceptions.ReadTimeout('t2'),
                               {'lastPrice': 0}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(p.get_current_price('1802'), 0.0)
            self.assertEqual(p.get_current_price('1802'), 0.0)
        self.assertNotIn('報價已恢復', buf.getvalue())
        self.assertIn('1802', self.P._quote_missing, '沒有正價格 ⇒ 仍算缺價')

    def test_non_network_error_also_leaves_a_mark(self):
        p, _ = _make_provider([ValueError('A00002 response parse Error'),
                               {'lastPrice': 77.0}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(p.get_current_price('1802'), 0.0)
            self.assertEqual(p.get_current_price('1802'), 77.0)
        self.assertIn('✅ 1802 報價已恢復（77.00', buf.getvalue())

    def test_retry_success_prints_recovery_line(self):
        """⚠️ 之後**重試就成功**（每天 09:00 的形狀）也要留下「已恢復」的正面證據。

        2026-11-17：v1.1.41 只記「兩次都失敗」，於是這種最常見的形狀一句 ✅ 都不會印——
        VM 上只能靠「沒有 ❌」反推（當天 09:00:12／09:00:24 兩檔真實案例）。
        """
        import requests
        px, out, stub = self._call([requests.exceptions.ReadTimeout('t1'),
                                    {'lastPrice': 109.5}])
        self.assertEqual(px, 109.5)
        self.assertEqual(stub.calls, 2, '仍只重試一次')
        self.assertIn('⚠️ 1802 報價逾時／斷線，第 1/1 次重試', out)
        self.assertIn('✅ 1802 報價已恢復（109.50，缺價', out)
        self.assertEqual(self.P._quote_missing, {}, '恢復後狀態要清掉，不可留在缺價名單')


class QuoteDiagnosticTimestampTest(unittest.TestCase):
    """報價診斷行要有**台北時間**前綴（2026-11-17 使用者要求）。

    為什麼：這些 print 原本沒有時間戳，貼出來的 log 看起來永遠像「啟動就出事」——
    11/16 與 11/17 兩次都得回頭跑 `docker logs -t`（UTC）再換算成台北時間才敢下結論。
    """

    PAT = r'^\[\d{2}:\d{2}:\d{2}\] '

    def setUp(self):
        import data.esun_provider as P
        self.P = P
        P._quote_missing.clear()
        self._mis = patch('core.inst_data.fetch_intraday_quotes', return_value={})
        self._mis.start()

    def tearDown(self):
        self._mis.stop()
        self.P._quote_missing.clear()

    def test_tpe_ts_is_utc_plus_8(self):
        from datetime import datetime, timedelta, timezone
        s = self.P._tpe_ts()
        self.assertRegex(s, r'^\d{2}:\d{2}:\d{2}$')
        self.assertEqual(s, datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S'))

    def test_retry_line_has_prefix(self):
        import requests
        p, _ = _make_provider([requests.exceptions.ReadTimeout('t1'),
                               {'lastPrice': 109.5}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            p.get_current_price('1802')
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        self.assertTrue(lines)
        for ln in lines:
            self.assertRegex(ln, self.PAT, f'這行沒有台北時間前綴：{ln}')

    def test_failure_and_recovery_lines_have_prefix(self):
        import requests
        p, _ = _make_provider([requests.exceptions.ReadTimeout('t1'),
                               requests.exceptions.ReadTimeout('t2'), {}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            p.get_current_price('1802')                    # 兩次都失敗 ⇒ ⚠️ + ❌
        for ln in [l for l in buf.getvalue().splitlines() if l.strip()]:
            self.assertRegex(ln, self.PAT, f'這行沒有台北時間前綴：{ln}')


if __name__ == '__main__':
    unittest.main()
