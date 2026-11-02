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
"""
import importlib
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

    def test_window_opens_at_1325_and_has_no_upper_bound(self):
        # 明確帶 start：本測試驗「窗口語義」，不受其他測試改動模組常數影響
        from datetime import datetime
        from core.live_utils import close_order_window_open
        self.assertFalse(close_order_window_open(datetime(2026, 10, 19, 13, 24), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 25), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 29), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 31), start='13:25'))


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


class QuoteRetryTest(unittest.TestCase):
    """`get_current_price` 對逾時／斷線重試一次（2026-11-02）。

    一次卡滿就吃掉下單窗口 1/10 ⇒ 重試一次（8+8=16 秒）換一個「不白白損失一輪」的機會；
    **只**對網路層錯誤重試——參數錯／token 失效重試無意義（那是別條路徑處理的）。
    """

    def _provider(self, side_effects):
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


if __name__ == '__main__':
    unittest.main()
