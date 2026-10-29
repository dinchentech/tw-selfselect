#!/usr/bin/env python
"""三個新模組的回歸測試（2026-10-28）：口徑 profile、A/B 評估數學、point-in-time 月營收。

要守住的事：
1. `PROFILE` 只是**預設值**：使用者明示的環境變數必須優先（不然「公平版」會被 profile 蓋掉）。
2. `forward_return()`／`summarize()` 的算式要正確（等權、配對差、勝率、t 統計量、樣本不足的警語）。
3. **月營收的「當時看得到」**要用公告日（次月 10 日）判斷，不能用營收所屬月份——
   否則 1 月中就知道 1 月整月營收＝偷看未來。新聞沒有來源時必須回 `unavailable`。
"""
import json
import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.ai_pick_ab import basket_return, forward_return, summarize  # noqa: E402
from core.backtest_profiles import PROFILES, describe, expand, resolve  # noqa: E402
from core.pit_data import news_pack, revenue_available_from, revenue_pack  # noqa: E402


class TestProfiles(unittest.TestCase):
    def test_known_profiles_have_expected_keys(self):
        for name in ("default", "conservative", "fair", "legacy", "levered", "raw"):
            self.assertIn(name, PROFILES)
            for k in ("SCORING_MODEL", "MARKET_FILTER", "IDLE_CASH_ASSET", "SCALE_TO_UTIL", "LEVERAGE"):
                self.assertIn(k, PROFILES[name]["env"], f"{name} 缺 {k}")

    def test_default_profile_is_zscore_with_park(self):
        """2026-10-29 預設口徑：zscore 評分 ＋ 停泊 0050。"""
        env = PROFILES["default"]["env"]
        self.assertEqual(env["SCORING_MODEL"], "zscore")
        self.assertEqual(env["IDLE_CASH_ASSET"], "0050")
        self.assertEqual(env["MARKET_FILTER"], "1")

    def test_legacy_profile_restores_old_behaviour(self):
        env = PROFILES["legacy"]["env"]
        self.assertEqual(env["SCORING_MODEL"], "legacy")
        self.assertEqual(env["IDLE_CASH_ASSET"], "")

    def test_expand_uses_profile_defaults(self):
        env = expand("fair")
        self.assertEqual(env["IDLE_CASH_ASSET"], "0050")
        self.assertEqual(env["MARKET_FILTER"], "1")
        self.assertEqual(expand("conservative")["IDLE_CASH_ASSET"], "")

    def test_explicit_env_wins(self):
        """使用者明示 `IDLE_CASH_ASSET=00878` 時，profile 不得覆寫。"""
        env = expand("fair", {"IDLE_CASH_ASSET": "00878"})
        self.assertEqual(env["IDLE_CASH_ASSET"], "00878")
        self.assertEqual(env["MARKET_FILTER"], "1", "沒明示的仍用 profile 預設")

    def test_no_profile_means_no_change(self):
        self.assertEqual(expand(None), {})
        self.assertEqual(expand(""), {})
        self.assertIsNone(resolve(None))

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            resolve("does-not-exist")

    def test_describe_lists_all(self):
        txt = describe()
        for name in PROFILES:
            self.assertIn(name, txt)


class TestAbMath(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range("2024-01-01", periods=300, freq="B")
        self.series = pd.Series([100 * (1.001 ** i) for i in range(300)], index=self.idx)

    def test_forward_return_matches_manual(self):
        r = forward_return(self.series, self.idx[0], None, 21)
        self.assertAlmostEqual(r, self.series.iloc[21] / self.series.iloc[0] - 1, places=10)

    def test_forward_return_snaps_to_next_trading_day(self):
        got = forward_return(self.series, "2024-01-06", None, 5)   # 週六
        want = forward_return(self.series, self.idx[3], None, 5)   # 下一個交易日
        self.assertAlmostEqual(got, want, places=10)

    def test_basket_is_equal_weight_and_skips_missing(self):
        px = {"A": self.series, "B": self.series * 2}
        r, used = basket_return(px, ["A", "B", "ZZZ"], self.idx[0], None, 21)
        self.assertEqual(used, 2)
        self.assertAlmostEqual(r, forward_return(self.series, self.idx[0], None, 21), places=10)

    def test_summarize_basic(self):
        s = summarize([(0.10, 0.05), (0.02, 0.03), (0.08, 0.01)])
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["diff_mean"], (0.05 - 0.01 + 0.07) / 3, places=10)
        self.assertAlmostEqual(s["win_rate"], 2 / 3, places=10)
        self.assertIn("樣本不足", s["verdict"])

    def test_summarize_empty(self):
        s = summarize([(None, 0.1), (0.1, None)])
        self.assertEqual(s["n"], 0)
        self.assertIsNone(s["diff_mean"])

    def test_summarize_identical_pairs_have_no_t(self):
        s = summarize([(0.1, 0.1)] * 12)
        self.assertIsNone(s["t_stat"], "差為 0 時不該除以 0")
        self.assertEqual(s["diff_mean"], 0.0)


class TestRevenuePointInTime(unittest.TestCase):
    ROWS = [
        {"revenue_year": 2022, "revenue_month": 1, "revenue": 100e8, "create_time": ""},
        {"revenue_year": 2021, "revenue_month": 1, "revenue": 80e8, "create_time": ""},
        {"revenue_year": 2021, "revenue_month": 12, "revenue": 90e8, "create_time": ""},
    ]

    def test_available_from_is_next_month_10th(self):
        self.assertEqual(revenue_available_from(2022, 1), "2022-02-10")
        self.assertEqual(revenue_available_from(2021, 12), "2022-01-10")
        self.assertEqual(revenue_available_from(2022, 1, "2022-02-08"), "2022-02-08")

    def test_december_revenue_hidden_until_jan_10(self):
        """1/2 選股時，2021/12 的營收還沒公布（1/10 才公布）→ 只看得到 2021/01（不能偷看 12 月）。"""
        p = revenue_pack(self.ROWS, "2022-01-02")
        self.assertTrue(p["available"])
        latest = p["items"][-1]
        self.assertEqual((latest["year"], latest["month"]), (2021, 1),
                         "2021/12 的營收在 2022-01-10 才公布，1/2 不得看到")

    def test_january_pack_visible_after_feb_10(self):
        p = revenue_pack(self.ROWS, "2022-02-11")
        self.assertTrue(p["available"])
        latest = p["items"][-1]
        self.assertEqual((latest["year"], latest["month"]), (2022, 1))
        self.assertAlmostEqual(latest["yoy"], 0.25, places=6)     # 100/80 - 1
        self.assertAlmostEqual(latest["mom"], round(100 / 90 - 1, 4), places=6)

    def test_provenance_never_after_as_of(self):
        p = revenue_pack(self.ROWS, "2022-02-11")
        self.assertLessEqual(pd.Timestamp(p["provenance"]), pd.Timestamp("2022-02-11"))


class TestNewsPack(unittest.TestCase):
    def test_unavailable_by_default(self):
        p = news_pack("2330", "2022-01-03")
        self.assertTrue(p["unavailable"])
        self.assertIn("沒有新聞來源", p["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestRequireFull(unittest.TestCase):
    """`--require-full`：兩邊都要選滿 N 檔才算等量比較。"""

    def test_full_both_sides_ok(self):
        from core.ai_pick_ab import eligible_for_compare
        ok, why = eligible_for_compare(["a", "b"], ["c", "d"], 2, require_full=True)
        self.assertTrue(ok, why)

    def test_rule_side_short_is_excluded_when_strict(self):
        from core.ai_pick_ab import eligible_for_compare
        ok, why = eligible_for_compare(["a", "b"], ["c"], 2, require_full=True)
        self.assertFalse(ok)
        self.assertIn("檔數不符", why)

    def test_rule_side_short_allowed_when_not_strict(self):
        from core.ai_pick_ab import eligible_for_compare
        ok, _ = eligible_for_compare(["a", "b"], ["c"], 2, require_full=False)
        self.assertTrue(ok, "非嚴格模式比的是「實際會持有的籃子」")

    def test_ai_missing(self):
        from core.ai_pick_ab import eligible_for_compare
        ok, why = eligible_for_compare(None, ["c"], 2)
        self.assertFalse(ok)
        self.assertIn("AI 組缺席", why)


class TestNewsPointInTime(unittest.TestCase):
    """新聞只採用到選股日 13:30（決策時點）以前；來源壞掉一律留空。"""

    class _Fake:
        name = "fake"

        def __init__(self, items):
            self.items = items

        def fetch(self, sid, as_of):
            return list(self.items)

    def _with_provider(self, items, fn):
        from core.pit_data import register_news_provider, NEWS_PROVIDERS
        old = NEWS_PROVIDERS.get("fake")
        register_news_provider("fake", self._Fake(items))
        try:
            return fn()
        finally:
            if old is None:
                NEWS_PROVIDERS.pop("fake", None)
            else:
                register_news_provider("fake", old)

    def test_cutoff_filters_same_day_evening_news(self):
        from core.pit_data import news_pack
        items = [{"ts": "2022-01-03 09:05:00", "title": "早盤利多", "url": "u1"},
                 {"ts": "2022-01-03 20:00:00", "title": "收盤後消息", "url": "u2"},
                 {"ts": "2022-01-04 08:00:00", "title": "隔天消息", "url": "u3"}]
        p = self._with_provider(items, lambda: news_pack("2330", "2022-01-03", provider="fake"))
        self.assertTrue(p["available"], p)
        titles = [x["title"] for x in p["items"]]
        self.assertIn("早盤利多", titles)
        self.assertNotIn("收盤後消息", titles, "13:30 之後發布的新聞對這次決策是未來資訊")
        self.assertNotIn("隔天消息", titles)

    def test_empty_when_source_returns_nothing(self):
        from core.pit_data import news_pack
        p = self._with_provider([], lambda: news_pack("2330", "2022-01-03", provider="fake"))
        self.assertTrue(p["unavailable"])

    def test_ts_ok_helper(self):
        from core.pit_news import _ts_ok
        self.assertTrue(_ts_ok("2022-01-03 09:00:00", "2022-01-03"))
        self.assertFalse(_ts_ok("2022-01-03 14:00:00", "2022-01-03"))


class TestPickDates(unittest.TestCase):
    """選股日的產生（2026-10-28 踩過：`--start` 不是月初時會靜默 0 個日期）。"""

    def setUp(self):
        self.cal = pd.date_range("2021-12-01", "2022-12-31", freq="B")

    def test_start_not_month_start_gives_dates(self):
        from scripts.ai_pick_ab import pick_dates
        got = pick_dates("2022-01-03", "2022-03-31", 1, calendar=self.cal)
        self.assertEqual(len(got), 3, got)
        self.assertEqual(got[0], "2022-01-03")
        self.assertTrue(all(d >= "2022-01-03" for d in got))

    def test_single_day_range_still_yields_one(self):
        from scripts.ai_pick_ab import pick_dates
        got = pick_dates("2022-01-03", "2022-01-31", 1, calendar=self.cal)
        self.assertEqual(got, ["2022-01-03"])

    def test_weekend_snaps_to_next_trading_day(self):
        from scripts.ai_pick_ab import pick_dates
        got = pick_dates("2022-01-01", "2022-01-31", 1, calendar=self.cal)
        self.assertEqual(got, ["2022-01-03"], "1/1 是週六 ⇒ 對齊到 1/3")
