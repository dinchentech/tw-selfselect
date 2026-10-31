#!/usr/bin/env python
"""`core/scoring.py`（選股評分共用實作）回歸測試（2026-10-29）。

`SCORING_MODEL=zscore` 已成為**預設**（使用者裁定：預設組合＝zscore·停泊0050），
所以這份算式同時決定回測與實盤選股，必須有測試釘住：
1. PER 資格門檻 `0 < PER <= 40`（缺 PER 不得入選）。
2. 權重方向：63 日動能／20 日動能／貼近 52 週高／低 PER 都是加分。
3. 缺值（None）以 0 計，不得讓整個選股日變空。
4. 同分時以 sid 升冪（可重現）。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.scoring import (WEIGHTS, eligible, nonmom_picks, pick_sleeves,  # noqa: E402
                          picks_from_rows, prerank, score_rows)


def row(sid, r63=0.1, r20=0.05, dist=-0.05, per=15.0):
    return {"sid": sid, "r63": r63, "r20": r20, "dist": dist, "per": per}


class TestEligible(unittest.TestCase):
    def test_per_bounds(self):
        self.assertTrue(eligible(row("A", per=15)))
        self.assertFalse(eligible(row("A", per=0)))
        self.assertFalse(eligible(row("A", per=-3)))
        self.assertFalse(eligible(row("A", per=40.01)))
        self.assertTrue(eligible(row("A", per=40)))
        self.assertFalse(eligible({"sid": "A", "per": None}))
        self.assertFalse(eligible({"sid": "A"}))


class TestScoreRows(unittest.TestCase):
    def test_weights_are_the_documented_ones(self):
        self.assertEqual(WEIGHTS, {"r63": 0.40, "r20": 0.25, "dist": 0.20, "per": 0.15})

    def test_directions(self):
        """動能高、貼近高點、PER 低 ⇒ 分數高。"""
        rows = [row("GOOD", r63=0.30, r20=0.15, dist=-0.01, per=10),
                row("BAD", r63=-0.20, r20=-0.10, dist=-0.30, per=35)]
        got = picks_from_rows(rows, top_n=2)
        self.assertEqual(got[0], "GOOD")
        self.assertEqual(got[1], "BAD")

    def test_per_filter_applied(self):
        rows = [row("CHEAP", per=10), row("RICH", per=90), row("NA", per=None)]
        self.assertEqual(picks_from_rows(rows, top_n=5), ["CHEAP"])

    def test_missing_values_do_not_empty_the_date(self):
        """r63 全缺（暖機）時仍要能排序，不得回空。"""
        rows = [row("A", r63=None, r20=0.1), row("B", r63=None, r20=0.2)]
        got = picks_from_rows(rows, top_n=2)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], "B", "r63 無資訊時，20 日動能高的勝出")

    def test_tie_break_is_deterministic(self):
        rows = [row("B"), row("A")]          # 完全同分
        self.assertEqual([s for s, _ in score_rows(rows)], ["A", "B"])

    def test_empty_input(self):
        self.assertEqual(score_rows([]), [])
        self.assertEqual(picks_from_rows([], top_n=5), [])

    def test_scores_sorted_desc(self):
        rows = [row("A", r63=0.1), row("B", r63=0.5), row("C", r63=0.3)]
        scores = [s for _sid, s in score_rows(rows)]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestRevenueFactorAndSectorCap(unittest.TestCase):
    """2026-10-29 新增：營收成長因子（`use_revenue`）與產業分散上限（`apply_sector_cap`）。"""

    def _rows(self):
        return [
            {"sid": "HI", "r63": 0.2, "r20": 0.1, "dist": -0.02, "per": 12, "rev": 0.50},
            {"sid": "LO", "r63": 0.2, "r20": 0.1, "dist": -0.02, "per": 12, "rev": -0.30},
        ]

    def test_revenue_factor_changes_order(self):
        from core.scoring import score_rows
        plain = [s for s, _ in score_rows(self._rows())]
        withrev = [s for s, _ in score_rows(self._rows(), use_revenue=True)]
        self.assertEqual(set(plain), {"HI", "LO"})
        self.assertEqual(withrev[0], "HI", "營收 YoY 高的要在有營收因子時排前面")

    def test_revenue_missing_is_neutral(self):
        from core.scoring import score_rows
        rows = [{"sid": "A", "r63": 0.1, "r20": 0.1, "dist": -0.02, "per": 12, "rev": None},
                {"sid": "B", "r63": 0.1, "r20": 0.1, "dist": -0.02, "per": 12, "rev": None}]
        self.assertEqual(len(score_rows(rows, use_revenue=True)), 2, "缺營收不得把標的踢掉")

    def test_weights_sum_to_one(self):
        from core.scoring import WEIGHTS, WEIGHTS_REVENUE
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)
        self.assertAlmostEqual(sum(WEIGHTS_REVENUE.values()), 1.0, places=9)

    def test_sector_cap_limits_and_backfills(self):
        from core.scoring import apply_sector_cap
        ranked = ["A", "B", "C", "D"]
        ind = {"A": "半導體", "B": "半導體", "C": "半導體", "D": "金融"}
        self.assertEqual(apply_sector_cap(ranked, ind, 2), ["A", "B", "D"],
                         "同產業最多 2 檔，超過的略過、由後面的產業遞補")
        self.assertEqual(apply_sector_cap(ranked, ind, 0), ranked, "0＝不限")

    def test_sector_cap_unknown_industry_grouped(self):
        from core.scoring import apply_sector_cap
        self.assertEqual(apply_sector_cap(["A", "B"], {}, 1), ["A"])


class TestPrerank(unittest.TestCase):
    """`prerank()`：先依動能排名縮小池子（降低追高），預設不得改變任何行為。"""

    def setUp(self):
        self.rows = [row(f"S{i}", r63=0.01 * i, per=15) for i in range(1, 11)]   # r63 1%~10%

    def test_disabled_is_identity(self):
        for kw in (None, 0, 0.0, 100, 150):
            got = prerank(self.rows, "r63", kw)
            self.assertEqual([r["sid"] for r in got], [r["sid"] for r in self.rows], kw)

    def test_keeps_top_pct(self):
        got = prerank(self.rows, "r63", 30)     # 前 30% ⇒ r63 >= 7% 左右
        self.assertTrue(all(r["r63"] >= 0.07 for r in got))
        self.assertLess(len(got), len(self.rows))
        self.assertIn("S10", [r["sid"] for r in got])
        self.assertNotIn("S1", [r["sid"] for r in got])

    def test_missing_key_is_dropped(self):
        rows = self.rows + [{"sid": "NO", "per": 15}]
        got = prerank(rows, "r63", 50)
        self.assertNotIn("NO", [r["sid"] for r in got])

    def test_empty_input(self):
        self.assertEqual(prerank([], "r63", 30), [])


class TestNonmomPicks(unittest.TestCase):
    """`nonmom_picks()`：低基期（r63 後段）＋營收 YoY 正成長，越落後越前面。"""

    def setUp(self):
        self.rows = [row("A", r63=0.50, per=15), row("B", r63=0.02, per=15),
                     row("C", r63=-0.20, per=12), row("D", r63=-0.35, per=10)]
        self.rows[0]["rev"] = 0.30      # 動能強、營收也強 ⇒ 不該進非動能名單
        self.rows[1]["rev"] = 0.05
        self.rows[2]["rev"] = 0.40
        self.rows[3]["rev"] = 0.10

    def test_only_lagged_with_growing_revenue(self):
        got = [sid for sid, _s in nonmom_picks(self.rows, quantile=0.5, rev_min=0.0)]
        self.assertNotIn("A", got)                       # 動能不在後段
        self.assertIn("C", got)
        self.assertIn("D", got)

    def test_negative_revenue_excluded(self):
        rows = [dict(r) for r in self.rows]
        rows[2]["rev"] = -0.05
        got = [sid for sid, _s in nonmom_picks(rows, quantile=0.5, rev_min=0.0)]
        self.assertNotIn("C", got)

    def test_missing_revenue_excluded(self):
        rows = [dict(r) for r in self.rows]
        rows[3].pop("rev")
        got = [sid for sid, _s in nonmom_picks(rows, quantile=0.5, rev_min=0.0)]
        self.assertNotIn("D", got)

    def test_empty_when_no_revenue_data(self):
        rows = [{"sid": "X", "r63": -0.3, "r20": -0.1, "dist": -0.4, "per": 10}]
        self.assertEqual(nonmom_picks(rows), [])


class TestPickSleeves(unittest.TestCase):
    """`pick_sleeves()`：動能名單 + 非動能名額的組成，不得重複、不得超過 N。"""

    def test_disabled_is_pure_momentum(self):
        mom = [("A", 3.0), ("B", 2.0), ("C", 1.0)]
        self.assertEqual(pick_sleeves(mom, [], 2, 0), [("A", 3.0), ("B", 2.0)])

    def test_reserves_slots(self):
        mom = [("A", 3.0), ("B", 2.0), ("C", 1.0)]
        non = [("X", 9.0), ("Y", 8.0)]
        got = pick_sleeves(mom, non, 3, 1)
        self.assertEqual([x[0] for x in got], ["A", "B", "X"])

    def test_no_duplicates(self):
        mom = [("A", 3.0), ("B", 2.0)]
        non = [("B", 9.0), ("X", 8.0)]
        got = pick_sleeves(mom, non, 2, 2)
        sids = [x[0] for x in got]
        self.assertEqual(len(sids), len(set(sids)))
        self.assertIn("X", sids)

    def test_caps_at_top_n(self):
        mom = [(f"M{i}", 10 - i) for i in range(5)]
        non = [(f"N{i}", 10 - i) for i in range(5)]
        self.assertEqual(len(pick_sleeves(mom, non, 5, 2)), 5)
        self.assertEqual(len(pick_sleeves(mom, non, 5, 9)), 5)
