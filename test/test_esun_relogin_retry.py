"""回歸測試：E.Sun 下單失敗 → 強制重登 → 重試一次。

背景（2026-09-11 事件）：
    E.Sun `login()` 開頭是 `if self._logged_in: return`（no-op），
    session 一旦失效就不會重登，下單會持續回 `A00002: response parse Error`。
    當天 3515/2006 連 35 次下單全敗、0 成交，只能靠重啟 VM 恢復（同 08/31 的 3008）。

修復：`place_order` 的 `_do_place` 內改成兩次嘗試，
      第一次失敗就 `force_relogin()`（真正重建 SDK 並重登）後重試一次。

執行：
    python3 -m unittest discover -s test -p 'test_esun_relogin_retry.py'
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.esun_provider import EsunProvider  # noqa: E402


class _FakeTradeSDK:
    """前 n 次 place_order 失敗，之後成功。"""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def place_order(self, order):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("A00002: response parse Error")
        return {"order_no": "OK123", "stock_no": order.stock_no}


def _make_provider(fail_times):
    """繞過 __init__（需 keyring/config），只裝上測試所需的狀態。"""
    p = EsunProvider.__new__(EsunProvider)
    p._logged_in = True            # 模擬「自以為已登入」的失效 session
    p._login_failed = False
    p._trade_sdk = _FakeTradeSDK(fail_times)
    p._marketdata = None
    p.relogin_calls = 0

    def _fake_login():
        p._logged_in = True
        return True

    def _fake_force_relogin():
        p.relogin_calls += 1
        p._logged_in = False       # 真正重置後重登
        _fake_login()
        return True

    p.login = _fake_login
    p.force_relogin = _fake_force_relogin
    p.get_current_price = lambda sym: 100.0
    return p


class TestEsunReloginRetry(unittest.TestCase):

    def test_first_failure_triggers_relogin_and_retry_succeeds(self):
        """第一次失敗 → 呼叫 force_relogin → 第二次成功，回傳成功結果。"""
        p = _make_provider(fail_times=1)
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 1, "下單失敗後應強制重登一次")
        self.assertEqual(p._trade_sdk.calls, 2, "應重試一次（共兩次嘗試）")
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("order_no"), "OK123")
        self.assertNotIn("error", res)

    def test_success_on_first_try_does_not_relogin(self):
        """第一次就成功 → 不應重登、不應重試。"""
        p = _make_provider(fail_times=0)
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 0)
        self.assertEqual(p._trade_sdk.calls, 1)
        self.assertEqual(res.get("order_no"), "OK123")

    def test_both_attempts_fail_returns_error_and_only_one_relogin(self):
        """兩次都失敗 → 回傳 error，且只重登一次（不無限重試）。"""
        p = _make_provider(fail_times=99)
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 1, "只應重登一次，不可無限重試")
        self.assertEqual(p._trade_sdk.calls, 2, "最多兩次嘗試")
        self.assertIn("error", res)
        self.assertIn("A00002", res["error"])

    def test_relogin_exception_does_not_break_error_reporting(self):
        """重登本身爆掉時，仍要回傳原始下單錯誤，不可拋出例外。"""
        p = _make_provider(fail_times=99)

        def _boom():
            p.relogin_calls += 1
            raise RuntimeError("relogin explode")

        p.force_relogin = _boom
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 1)
        self.assertIn("error", res)
        self.assertIn("A00002", res["error"])

    # ── 行情取不到時也必須重登，不可直接放棄 ──────────────────────

    def test_price_failure_triggers_relogin_then_retries_price(self):
        """第一次取價回 0（行情 token 失效）→ 重登 → 第二次取價成功 → 照常下單。

        這條路徑原本會直接 return "cannot get current price"，
        把「下單失敗→重登→重試」整段繞過（等於白修）。
        """
        p = _make_provider(fail_times=0)
        prices = [0.0, 100.0]

        def _price(sym):
            return prices.pop(0) if prices else 0.0

        p.get_current_price = _price
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 1, "取不到報價時應強制重登一次")
        self.assertEqual(p._trade_sdk.calls, 1)
        self.assertEqual(res.get("order_no"), "OK123")

    def test_price_failure_twice_gives_up_without_ordering(self):
        """重登後仍取不到報價 → 回 error，且不可送出任何委託。"""
        p = _make_provider(fail_times=0)
        p.get_current_price = lambda sym: 0.0
        with mock.patch("time.sleep", return_value=None):
            res = p.place_order("3515", "BUY", 1000)
        self.assertEqual(p.relogin_calls, 1)
        self.assertEqual(p._trade_sdk.calls, 0, "取不到報價不可下單")
        self.assertIn("error", res)
        self.assertIn("current price", res["error"])


if __name__ == "__main__":
    unittest.main()
