#!/usr/bin/env python
"""`core/park_asset.py`（實盤閒置資金停泊）的純函式回歸測試。

守住的規則（使用者 2026-10-31 裁定）：
1. **預設開啟、停泊 `0050`**；只有明確寫 `SELFSELECT_PARK_ASSET=`（空字串）才是「不用停泊」。
2. 只在 **immediate** 模式、且名單每一檔都「已持有或今天已嘗試買進」時才停泊（signal 模式不停泊）。
3. 停泊金額不得把「已停泊的市值」再算成閒置（避免重複買）。
4. 太小的金額不做（< MIN_PARK_NTD）；以整股買進。
5. 要買股時賣出剛好夠用的股數（向上取整、不超過持有）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.park_asset import (DEFAULT_SYMBOL, MIN_PARK_NTD, can_park_after_build,  # noqa: E402
                             enabled, idle_amount, is_build_attempted, load_state,
                             park_shares, park_symbol, release_shares, save_state)


class TestSymbolAndEnabled(unittest.TestCase):
    def test_default_is_enabled_with_0050(self):
        """2026-10-31 第二版：未設定 ⇒ **預設停泊 0050**。"""
        self.assertEqual(park_symbol({}), "0050")
        self.assertTrue(enabled({}))
        self.assertEqual(DEFAULT_SYMBOL, "0050")

    def test_explicit_empty_turns_it_off(self):
        """`SELFSELECT_PARK_ASSET=`（明確留空）＝使用者關閉停泊。"""
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": ""}), "")
        self.assertFalse(enabled({"SELFSELECT_PARK_ASSET": ""}))
        self.assertFalse(enabled({"SELFSELECT_PARK_ASSET": "   "}))

    def test_user_can_specify(self):
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": "0050"}), "0050")
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": "00878"}), "00878")
        self.assertTrue(enabled({"SELFSELECT_PARK_ASSET": "00878"}))

    def test_reads_real_env(self):
        old = os.environ.pop("SELFSELECT_PARK_ASSET", None)
        try:
            self.assertTrue(enabled())                       # 未設定 ⇒ 預設停泊 0050
            self.assertEqual(park_symbol(), "0050")
            os.environ["SELFSELECT_PARK_ASSET"] = "0056"
            self.assertTrue(enabled())
            self.assertEqual(park_symbol(), "0056")
            os.environ["SELFSELECT_PARK_ASSET"] = ""
            self.assertFalse(enabled())                      # 明確留空 ⇒ 關閉
        finally:
            os.environ.pop("SELFSELECT_PARK_ASSET", None)
            if old is not None:
                os.environ["SELFSELECT_PARK_ASSET"] = old


class TestIdleAmount(unittest.TestCase):
    def test_subtracts_stock_and_parked_value(self):
        # 腿額度 100 萬、股票市值 60 萬、已停泊 30 萬 ⇒ 閒置 10 萬（不能把停泊的再算一次）
        self.assertAlmostEqual(idle_amount(1_000_000, 600_000, 300_000), 100_000)
        self.assertAlmostEqual(idle_amount(1_000_000, 600_000), 400_000)

    def test_never_negative(self):
        self.assertEqual(idle_amount(1_000_000, 1_200_000), 0.0)
        self.assertEqual(idle_amount(None, 1), 0.0)


class TestParkShares(unittest.TestCase):
    def test_whole_shares_round_down(self):
        self.assertEqual(park_shares(100_000, 105.5), 947)      # 947 × 105.5 = 99,908
        self.assertEqual(park_shares(1_000_000, 200), 5000)

    def test_too_small_is_skipped(self):
        self.assertEqual(park_shares(MIN_PARK_NTD - 1, 50), 0)   # 金額不足門檻
        self.assertEqual(park_shares(5_000, 50), 0)              # 也不足 1 張的錢

    def test_bad_price(self):
        self.assertEqual(park_shares(100_000, 0), 0)
        self.assertEqual(park_shares(100_000, -5), 0)

    def test_boundary_exactly_min(self):
        self.assertEqual(park_shares(MIN_PARK_NTD, 100), int(MIN_PARK_NTD // 100))


class TestReleaseShares(unittest.TestCase):
    def test_rounds_up_and_clamps(self):
        self.assertEqual(release_shares(10_000, 100, 200), 100)   # 剛好 100 股
        self.assertEqual(release_shares(10_050, 100, 200), 101)   # 向上取整
        self.assertEqual(release_shares(10_000, 100, 50), 50)     # 不足則賣光

    def test_zero_cases(self):
        self.assertEqual(release_shares(0, 100, 200), 0)
        self.assertEqual(release_shares(10_000, 0, 200), 0)
        self.assertEqual(release_shares(10_000, 100, 0), 0)


class TestCanParkAfterBuild(unittest.TestCase):
    def test_immediate_all_settled(self):
        self.assertTrue(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100},
                                             {"2317": "2026-11-02"}, "0050"))

    def test_immediate_someone_pending(self):
        self.assertFalse(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100}, {}, "0050"))

    def test_signal_mode_never_parks(self):
        self.assertFalse(can_park_after_build("signal", ["2330"], {"2330": 100}, {"2330": "x"}, "0050"))

    def test_park_symbol_excluded_from_watchlist(self):
        # 名單含停泊標的時，它自己不算「還沒建倉」
        self.assertTrue(can_park_after_build("immediate", ["2330", "0050"], {"2330": 100}, {}, "0050"))

    def test_empty_watchlist(self):
        self.assertFalse(can_park_after_build("immediate", [], {}, {}, "0050"))

    # ── 2026-11-02：選到但買不到（過熱閘門擋／下單失敗）也算建倉已處理 ──
    def test_attempted_today_counts_as_settled(self):
        """昨天之前沒成交的買單，讓停泊可以接手（否則那筆錢既不買股也不停泊）。"""
        self.assertTrue(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100}, {},
                                            "0050", attempted={"2317": "2026-11-02"},
                                            today="2026-11-02"))

    def test_attempted_yesterday_does_not_count(self):
        """只認當天：隔天要再試一次買進，不能拿舊紀錄擋掉。"""
        self.assertFalse(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100}, {},
                                             "0050", attempted={"2317": "2026-11-01"},
                                             today="2026-11-02"))

    def test_attempted_without_today_is_ignored(self):
        """沒給 today ⇒ 視為舊行為（attempted 一律不算），避免呼叫端忘記傳日期就默默放行。"""
        self.assertFalse(can_park_after_build("immediate", ["2330"], {}, {}, "0050",
                                             attempted={"2330": "2026-11-02"}))

    def test_is_build_attempted_rules(self):
        self.assertTrue(is_build_attempted("2330", {"2330": 1}, {}, {}, "2026-11-02"))
        self.assertTrue(is_build_attempted("2330", {}, {"2330": "2026-10-01"}, {}, "2026-11-02"))
        self.assertTrue(is_build_attempted("2330", {}, {}, {"2330": "2026-11-02"}, "2026-11-02"))
        self.assertFalse(is_build_attempted("2330", {}, {}, {"2330": "2026-11-01"}, "2026-11-02"))
        self.assertFalse(is_build_attempted("2330", {}, {}, {}, "2026-11-02"))


class TestStateIO(unittest.TestCase):
    def test_roundtrip_and_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "park.json"
            self.assertEqual(load_state(path)["shares"], 0)
            st = {"symbol": "0050", "shares": 100, "cost": 10_000.0, "opened": "2026-11-02",
                  "updated": "2026-11-02T13:30:00", "last_park_date": "2026-11-02"}
            save_state(st, path)
            got = load_state(path)
            self.assertEqual(got["symbol"], "0050")
            self.assertEqual(got["shares"], 100)
            self.assertAlmostEqual(got["cost"], 10_000.0)
            self.assertEqual(got["last_park_date"], "2026-11-02")

    def test_corrupt_state_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_state(path)["shares"], 0)


class TestLastParkTsRoundTrip(unittest.TestCase):
    """2026-11-04：`last_park_ts` 必須能讀回來。

    `selfselect_trader.park_idle_if_due()` 用它做「5 分鐘內不重複下單」，但舊版 `load_state()`
    漏掉這個鍵 ⇒ 永遠讀到 `None` ⇒ 防護失效 ⇒ 停泊每 60 秒重複下同一筆單
    （VM 實例：0050 282 股 @100.60 連 4 筆）。
    """

    def test_saved_ts_is_returned(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            save_state({"symbol": "0050", "shares": 282, "cost": 28369.2,
                        "updated": "2026-11-04T13:26:00", "last_park_ts": 1770000000.5}, path)
            st = load_state(path)
            self.assertAlmostEqual(st["last_park_ts"], 1770000000.5)
            self.assertEqual(st["shares"], 282)

    def test_missing_ts_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            save_state({"symbol": "0050", "shares": 0, "cost": 0.0}, path)
            self.assertEqual(load_state(path)["last_park_ts"], 0.0)

    def test_broken_ts_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            path.write_text('{"symbol": "0050", "shares": 5, "last_park_ts": "oops"}', encoding="utf-8")
            self.assertEqual(load_state(path)["last_park_ts"], 0.0)

    def test_absent_file_has_ts_key(self):
        self.assertEqual(load_state("/nonexistent/park_position.json")["last_park_ts"], 0.0)


class TestCashAvailable(unittest.TestCase):
    """停泊不得超過可用現金（2026-11-05）。

    實例：腿額度 100 萬、持股市值 69.4 萬 ⇒ 「額度」idle 30.6 萬，但實際現金只有十幾萬
    （買進 98.6 萬）⇒ 照額度停泊 3,000 股（約 29 萬）會下單超過現金。
    刻意保守：買進的回款不加回（模擬帳查不到現金餘額）。
    """

    def test_cash_is_capital_minus_open_cost(self):
        from core.park_asset import cash_available
        self.assertAlmostEqual(cash_available(1_000_000, 987_177), 12_823)

    def test_already_parked_cost_is_subtracted(self):
        from core.park_asset import cash_available
        self.assertAlmostEqual(cash_available(1_000_000, 500_000, 300_000), 200_000)

    def test_2026_11_05_case_caps_below_idle(self):
        """真例：books_audit 的 cost_open_csv = 987,177 ⇒ 現金約 1.28 萬 < idle 30.6 萬。"""
        from core.park_asset import cash_available
        cash = cash_available(1_000_000, 987_177.0)
        self.assertLess(cash, 305_689, "現金必須小於額度 idle（這正是要修的情境）")
        self.assertGreaterEqual(cash, 0)

    def test_never_negative(self):
        from core.park_asset import cash_available
        self.assertEqual(cash_available(1_000_000, 1_500_000), 0.0)

    def test_broken_input_returns_zero(self):
        from core.park_asset import cash_available
        self.assertEqual(cash_available("abc", 0), 0.0)
        self.assertEqual(cash_available(1_000_000, "abc"), 0.0)


class TestStatusFormatting(unittest.TestCase):
    """2026-11-05：停泊要「看得見」——成功、失敗、沒做都要能講清楚。"""

    def test_format_position_with_price(self):
        from core.park_asset import format_position
        got = format_position("0050", 1000, 97.15, 98.0)
        self.assertIn("0050 1,000 股", got)
        self.assertIn("均價 97.15", got)
        self.assertIn("98,000", got)
        # 2026-11-09（v1.1.40）：停泊也要看得見自己的損益（1,000 股 @97.15 → 98.00 ⇒ +850）
        self.assertIn("損益 +850（+0.87%）", got)
        self.assertNotIn("））", got, "不可出現嵌套括號")

    def test_format_position_loss(self):
        from core.park_asset import format_position
        got = format_position("0050", 2000, 97.60, 95.00)
        self.assertIn("損益 -5,200（-2.66%）", got)

    def test_format_position_without_price(self):
        from core.park_asset import format_position
        got = format_position("0050", 1000, 97.15, None)
        self.assertNotIn("市值", got)
        self.assertIn("均價", got)

    def test_format_position_empty(self):
        from core.park_asset import format_position
        self.assertEqual(format_position("0050", 0), "無停泊部位")
        self.assertEqual(format_position("0050", None), "無停泊部位")

    def test_skip_reason_order_of_checks(self):
        from core.park_asset import MIN_PARK_NTD, skip_reason
        self.assertIn("冷卻", skip_reason(cooldown=True))
        self.assertIn("窗口", skip_reason(window_open=False))
        self.assertIn("尚未建倉", skip_reason(build_done=False))
        self.assertIn(f"最低門檻 NT${MIN_PARK_NTD:,.0f}", skip_reason(idle=5000.0))
        self.assertIn("可用現金", skip_reason(cash=100.0))

    def test_skip_reason_empty_when_all_normal(self):
        from core.park_asset import skip_reason
        self.assertEqual(skip_reason(shares=1000, cash=500_000, idle=500_000), "",
                         "有停泊部位且條件正常時不需要理由")

    def test_skip_reason_default_when_nothing_triggered(self):
        from core.park_asset import skip_reason
        self.assertIn("沒有觸發", skip_reason(shares=0, cash=500_000, idle=500_000))


class TestFormatPlanVsActual(unittest.TestCase):
    """使用者 2026-11-05 要求：要能區分「應該停泊」與「實際停泊」。"""

    def _plan(self, **kw):
        base = {"idle": 305_689.0, "cash": 12_823.0, "cap": 12_823.0, "price": 97.15,
                "target_shares": 131, "actual_shares": 0, "status": "SKIP",
                "reason": "可用現金 NT$12,823 不足", "unknown": False}
        base.update(kw)
        return base

    def test_skip_case(self):
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan())
        self.assertIn("應該停泊", lines[0])
        self.assertIn("305,689", lines[0], "要顯示額度")
        self.assertIn("12,823", lines[0], "要顯示現金上限")
        self.assertIn("131 股", lines[0])
        # 2026-11-09（v1.1.39）：legacy Markdown 只有 `*粗體*`（`**` 是 MarkdownV2），
        # 舊寫法 `**無**` 在 Telegram 上會顯示字面的星號
        self.assertIn("實際停泊：*無*", lines[1])
        self.assertIn("少停泊 131 股", lines[2])

    def test_buy_case_no_diff_line(self):
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(status="BUY", actual_shares=131))
        self.assertIn("買進 131 股", lines[1])
        self.assertEqual(len(lines), 2, "應該＝實際時不該有差額行")

    def test_unknown_fill_is_marked(self):
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(status="BUY", actual_shares=131, unknown=True))
        self.assertIn("成交未確認", lines[1])

    def test_fail_case(self):
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(status="FAIL", reason="000017: 非該盤別盤中"))
        self.assertIn("送單未成交", lines[1])
        self.assertIn("000017", lines[1])

    def test_zero_target_has_no_diff(self):
        """目標 0（可用金額低於最低門檻）⇒ 不該冒出「差額」行，且原因寫「最低門檻」。"""
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(target_shares=0, cash=5_000.0, cap=5_000.0))
        self.assertEqual(len(lines), 2)
        self.assertIn("最低門檻", lines[0])

    def test_inconsistent_plan_says_cannot_size(self):
        """金額看起來夠、卻算出 0 張（計畫本身不一致）⇒ 老實說算不出張數，不亂指原因。"""
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(target_shares=0))
        self.assertIn("算不出可買張數", lines[0])

    def test_zero_cash_is_printed(self):
        """現金上限 0 必須印出來（舊版 `if cash:` 會把它藏起來，只剩「額度 ⇒ 目標 0」要人猜）。"""
        from core.park_asset import format_plan_vs_actual
        plan = self._plan(idle=19_980.0, cash=0.0, cap=0.0, target_shares=0, price=97.45,
                          reason="可用金額 NT$0 不足（最低門檻 NT$10,000）")
        lines = format_plan_vs_actual(plan)
        self.assertIn("現金上限 NT$0", lines[0])
        self.assertIn("已用盡", lines[0], "目標 0 的原因要說對（不是『取不到報價』）")
        self.assertNotIn("取不到報價", lines[0])

    def test_missing_price_reason(self):
        """真的取不到報價時才說取不到報價。"""
        from core.park_asset import format_plan_vs_actual
        lines = format_plan_vs_actual(self._plan(price=0.0, target_shares=0))
        self.assertIn("取不到報價", lines[0])

    def test_reason_is_escaped_for_markdown(self):
        """失敗原因會直接進 Telegram：底線等字元必須轉義（v1.1.39）。"""
        from core.park_asset import format_plan_vs_actual
        from utils.telegram import md_ok
        lines = format_plan_vs_actual(self._plan(status="FAIL", reason="park_shares 回 0（broker_mismatch）"))
        text = "\n".join(lines)
        self.assertIn(r"park\_shares", text)
        self.assertTrue(md_ok(text), text)


if __name__ == "__main__":
    unittest.main()
