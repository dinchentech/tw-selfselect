#!/usr/bin/env python
"""`scripts/walk_forward.py` 的純函式迴歸測試（不跑回測）。

守住的規則：
1. 測試年份必須連續遞增，而且**訓練迄日一定早於測試年**（否則就是偷看未來）。
2. 挑參數只能看訓練段指標；同分時要可重現（字典序），不能靠 dict 插入順序。
3. 逐年報酬串接必須是「複利相乘」，不是相加（相加會高估）。
4. 退化幅度 = OOS − in-sample，方向不能反（負值代表 OOS 較差）。
5. 鄰居表要能正確讀出 16 組網格並依 (池, 營收, 上限) 排序。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.walk_forward import (PRESET_COMBOS, anchored_windows, chain,  # noqa: E402
                                 degradation, neighbor_grid, pick_best, oos_years)


class TestWindows(unittest.TestCase):
    def test_test_years_inclusive_and_ordered(self):
        self.assertEqual(oos_years(2020, 2023), [2020, 2021, 2022, 2023])

    def test_test_years_rejects_reverse(self):
        with self.assertRaises(ValueError):
            oos_years(2023, 2020)

    def test_anchored_train_ends_before_test_year(self):
        """訓練段的迄日永遠是「測試年前一年年底」＝不可能看到測試年的資料。"""
        for year, tr_start, tr_end in anchored_windows(oos_years(2020, 2025)):
            self.assertEqual(tr_start, "2016-01-01")
            self.assertEqual(tr_end, f"{year - 1}-12-31")
            self.assertLess(tr_end, f"{year}-01-01")

    def test_anchored_windows_expand(self):
        """擴張式：每一輪的訓練窗都比前一輪長。"""
        prev = None
        for year, tr_start, tr_end in anchored_windows(oos_years(2020, 2025)):
            if prev is not None:
                self.assertGreater(tr_end, prev)
            prev = tr_end


class TestPickBest(unittest.TestCase):
    def test_picks_highest_metric(self):
        res = {"a": {"sharpe": 1.0}, "b": {"sharpe": 1.2}, "c": {"sharpe": 0.5}}
        self.assertEqual(pick_best(res, "sharpe"), ("b", 1.2))

    def test_tie_is_deterministic(self):
        res = {"b": {"sharpe": 1.0}, "a": {"sharpe": 1.0}}
        self.assertEqual(pick_best(res, "sharpe")[0], "a")

    def test_skips_missing_metric(self):
        res = {"a": {}, "b": {"sharpe": 0.3}}
        self.assertEqual(pick_best(res, "sharpe"), ("b", 0.3))

    def test_raises_when_empty(self):
        with self.assertRaises(ValueError):
            pick_best({}, "sharpe")
        with self.assertRaises(ValueError):
            pick_best({"a": {}}, "sharpe")


class TestChainAndDegradation(unittest.TestCase):
    def test_chain_is_compounded(self):
        self.assertAlmostEqual(chain([0.10, 0.10]), 0.21)
        self.assertAlmostEqual(chain([]), 0.0)

    def test_chain_differs_from_sum(self):
        """−50% 再 +50% 不等於 0（避免把串接報酬寫成相加）。"""
        self.assertAlmostEqual(chain([-0.5, 0.5]), -0.25)

    def test_degradation_sign(self):
        self.assertAlmostEqual(degradation(1.20, 0.75), -0.45)
        self.assertAlmostEqual(degradation(0.5, 0.9), 0.4)


class TestNeighborGrid(unittest.TestCase):
    def _write(self, tmp: Path, name: str, *, pool: int, rev: bool, cap: int,
               tr: float, sharpe: float) -> Path:
        p = tmp / name
        p.write_text(json.dumps({
            "pool_n": pool, "factor_revenue": rev, "max_per_sector": cap,
            "groups": {"normal": {"total_return": tr, "annualized": tr / 10,
                                  "sharpe": sharpe, "max_drawdown": -0.4}},
            "benchmark_0050": {"total_return": 4.776},
        }), encoding="utf-8")
        return p

    def test_reads_and_sorts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            paths = [
                self._write(tmp, "a.json", pool=150, rev=True, cap=2, tr=13.236, sharpe=1.15),
                self._write(tmp, "b.json", pool=20, rev=False, cap=0, tr=3.951, sharpe=0.92),
                self._write(tmp, "c.json", pool=150, rev=False, cap=2, tr=3.642, sharpe=0.71),
                self._write(tmp, "d.json", pool=100, rev=True, cap=0, tr=7.624, sharpe=0.95),
            ]
            rows = neighbor_grid(paths)
            self.assertEqual(len(rows), 4)
            self.assertEqual([(r["pool"], r["revenue"], r["cap"]) for r in rows],
                             [(20, 0, 0), (100, 1, 0), (150, 1, 2), (150, 0, 2)])
            best = max(r["total_return"] for r in rows)
            self.assertAlmostEqual(best, 13.236)
            self.assertAlmostEqual(rows[0]["bench_total_return"], 4.776)

    def test_skips_files_without_group(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad = tmp / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            empty = tmp / "empty.json"
            empty.write_text(json.dumps({"pool_n": 100}), encoding="utf-8")
            good = self._write(tmp, "ok.json", pool=50, rev=True, cap=0, tr=4.4, sharpe=0.87)
            rows = neighbor_grid([bad, empty, good])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pool"], 50)


class TestPresetCombos(unittest.TestCase):
    def test_preset_combos_match_selection_presets(self):
        """walk-forward 的候選前 3 組必須就是三個 preset 的實際旋鈕，不能各寫一套。"""
        from core.selection_presets import PRESETS
        for name, pool, rev, cap in PRESET_COMBOS[:3]:
            knobs = PRESETS[name]["knobs"]
            self.assertEqual(int(knobs["POOL_N"]), pool, name)
            self.assertEqual(int(knobs["FACTOR_REVENUE"]), rev, name)
            self.assertEqual(int(knobs["MAX_PER_SECTOR"]), cap, name)

    def test_combo_names_unique(self):
        names = [c[0] for c in PRESET_COMBOS]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
