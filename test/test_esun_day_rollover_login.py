"""回歸測試：登入狀態必須以「日期」為界（跨日強制重登）。

背景（2026-09-11 事故根因）：
    玉山 session token 的效期只到**簽發當日 23:59:59**（由登入回應的 JWT `exp` 實測）。
    但 container 常跨夜執行，而 `login()` 原本是：

        if self._logged_in:
            return

    → 隔天開盤仍拿著**昨天的過期 token**，且永遠不會重登，下單持續回
      `A00002: response parse Error`，只能靠人工重啟恢復（2026-08-31、2026-09-11 各一次）。

同時修掉一個潛在 bug：
    原本 marketdata 登入成功、但 **trade SDK 登入失敗**時，程式仍然把
    `_logged_in = True` → `login()` 從此 no-op → 下單全部失敗卻看不出原因。

執行：
    python3 -m unittest discover -s test -p 'test_esun_day_rollover_login.py'
"""
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.esun_provider as ep  # noqa: E402
from data.esun_provider import EsunProvider  # noqa: E402

DAY1 = datetime(2026, 9, 10, 18, 20, 39)   # 前一天傍晚（實際事故的啟動時間）
DAY1_LATE = datetime(2026, 9, 10, 23, 30, 0)
DAY2 = datetime(2026, 9, 11, 9, 0, 0)      # 隔天開盤（token 已過期）


class _Counters:
    """記錄 SDK 被建構／登入的次數。"""

    def __init__(self):
        self.md = 0
        self.trade = 0


def _make_provider(counters, trade_login_fails=False):
    """繞過 __init__（需 keyring/config），只裝上登入狀態機所需的欄位。"""
    p = EsunProvider.__new__(EsunProvider)
    p.config = {}
    p._marketdata = None
    p._trade_sdk = None
    p._logged_in = False
    p._login_failed = False
    p._session_date = None
    p._md_date = None
    p._trade_date = None
    p._trade_failed_date = None

    class _FakeMD:
        def __init__(self, cfg):
            counters.md += 1

        def login(self):
            pass

    class _FakeTrade:
        def __init__(self, cfg):
            counters.trade += 1

        def login(self):
            if trade_login_fails:
                raise RuntimeError("trade login boom")

    return p, _FakeMD, _FakeTrade


@contextmanager
def _env(MD, TR):
    """把假 SDK 與可控時鐘裝上，yield 出 datetime mock（可設 .now.return_value）。"""
    with mock.patch.object(ep, "EsunMarketdata", MD), \
         mock.patch.object(ep, "EsunTrade", TR), \
         mock.patch.object(ep, "datetime") as mdt:
        yield mdt


class TestDayRolloverLogin(unittest.TestCase):

    # ── 同一天內：不可重複登入（避免每次報價都打一次 auth）──────

    def test_login_is_noop_within_same_day(self):
        c = _Counters()
        p, MD, TR = _make_provider(c)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY2
            p.login()
            p.login()
            p.login()
        self.assertEqual(c.md, 1, "同一天內 marketdata 只應登入一次")
        self.assertEqual(c.trade, 1, "同一天內 trade 只應登入一次")
        self.assertTrue(p._logged_in)

    # ── 跨日：必須強制重登（本次修復的核心行為）────────────────

    def test_login_reauthenticates_on_new_day(self):
        c = _Counters()
        p, MD, TR = _make_provider(c)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY1          # 前一天傍晚啟動、登入
            p.login()
            self.assertEqual((c.md, c.trade), (1, 1))

            mdt.now.return_value = DAY1_LATE     # 同一天稍晚 → no-op
            p.login()
            self.assertEqual((c.md, c.trade), (1, 1))

            mdt.now.return_value = DAY2          # 隔天開盤 → 必須重登
            p.login()
        self.assertEqual(c.md, 2, "跨日必須重新登入 marketdata（舊 token 已於前一日 23:59:59 失效）")
        self.assertEqual(c.trade, 2, "跨日必須重新登入 trade（否則下單會回 A00002）")
        self.assertTrue(p._logged_in)
        self.assertEqual(p._session_date, "2026-09-11")

    def test_trade_sdk_is_rebound_across_days(self):
        """跨日重登必須換掉舊的 SDK 物件（否則仍是壞 session）。"""
        c = _Counters()
        p, MD, TR = _make_provider(c)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY1
            p.login()
            old_trade = p._trade_sdk
            mdt.now.return_value = DAY2
            p.login()
        self.assertIsNot(p._trade_sdk, old_trade, "跨日重登應換成新的 trade SDK 實例")

    # ── trade 登入失敗：不可靜默標記為「已登入」─────────────────

    def test_trade_login_failure_does_not_claim_logged_in(self):
        c = _Counters()
        p, MD, TR = _make_provider(c, trade_login_fails=True)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY2
            p.login()
        self.assertFalse(p._logged_in,
                         "trade 登入失敗時不可宣稱已登入（舊版會設 True → login() 永久 no-op）")
        self.assertIsNone(p._trade_sdk, "trade 登入失敗後不應留著半死的 SDK 實例")

    def test_trade_login_failure_is_retried_next_day(self):
        c = _Counters()
        p, MD, TR = _make_provider(c, trade_login_fails=True)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY1
            p.login()
            self.assertEqual(c.trade, 1)
            mdt.now.return_value = DAY2
            p.login()
        self.assertEqual(c.trade, 2, "隔天必須重新嘗試 trade 登入（不可永久放棄）")

    # ── _ensure_available()：登入失敗也必須跨日恢復 ──────────────

    def test_ensure_available_recovers_next_day(self):
        p = _make_provider(_Counters())[0]
        p._login_failed = True
        p._session_date = "2026-09-10"
        with mock.patch.object(ep, "datetime") as mdt:
            mdt.now.return_value = DAY1
            self.assertFalse(p._ensure_available(), "同一天內登入失敗 → 不應再打 API")
            mdt.now.return_value = DAY2
            self.assertTrue(p._ensure_available(), "跨日必須重新給機會（舊版會永久回 False）")

    # ── force_relogin()：同一天內也要真的重登 ────────────────────

    def test_force_relogin_does_real_relogin_same_day(self):
        c = _Counters()
        p, MD, TR = _make_provider(c)
        with _env(MD, TR) as mdt:
            mdt.now.return_value = DAY2
            p.login()
            self.assertEqual((c.md, c.trade), (1, 1))
            p.force_relogin()
            self.assertEqual((c.md, c.trade), (2, 2),
                             "force_relogin() 必須在同一日內也真的重登")
            self.assertTrue(p._logged_in)


if __name__ == "__main__":
    unittest.main()
