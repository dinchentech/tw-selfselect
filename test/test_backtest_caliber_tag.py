#!/usr/bin/env python
"""`core.backtest_rules.caliber_tag()`：結果檔名的口徑後綴（2026-11-05 新增 `strat_mode`）。

## 事故（2026-11-05 實際踩到）

比較「輪替四策略口徑（`STRAT_MODE=group`）」與「實盤口徑（`STRAT_MODE=form`）」時，
兩者跑同一窗口會寫出**完全相同的檔名**（`results/plan2_monthly_3group_<窗口>_...pool100.json`
與 `results/exposure_normal_<窗口>_...csv`）⇒ 後跑的把先跑的蓋掉。當時是靠「跑一組先複製到
`TMP/`」才救回檔案；若沒發現，就會拿 A 組的曲線去解釋 B 組的數字。

## 規則

- **`form`（實盤路徑、文件引用的基準）不加註** ⇒ 既有文件名與文件引用不變。
- **其他 `strat_mode` 一律加在後綴最後**（例：`..._pool100_group`）。
- 其他旋鈕仍只帶「非基準值」（legacy 評分／池 50／TOP5／`fill`／不加槓桿／`proportional`…）。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import caliber_tag  # noqa: E402

HARNESS = Path(_ROOT) / "scripts" / "backtest_plan2_monthly_3group.py"

#: 文件與既有結果檔用的實盤口徑（`PRESET=revenue`、停泊 0050、年線開）
FORM_BASE = dict(market_filter=True, mf_window=200, idle_cash_asset="0050",
                 scoring_model="zscore", factor_revenue=True, pool_n=100)


class TestCaliberTag(unittest.TestCase):
    def test_form_keeps_legacy_name(self):
        """實盤口徑（form）**不加** `_group`，既有檔名與文件引用不變。"""
        self.assertEqual(caliber_tag("immediate", strat_mode="form", **FORM_BASE),
                         "immediate_mf200_park0050_scorezscore_pool100")

    def test_group_gets_group_suffix(self):
        self.assertEqual(caliber_tag("immediate", strat_mode="group", **FORM_BASE),
                         "immediate_mf200_park0050_scorezscore_pool100_group")

    def test_group_suffix_is_last(self):
        tag = caliber_tag("immediate", strat_mode="group", market_filter=True,
                          idle_cash_asset="0050", scoring_model="zscore", factor_revenue=False,
                          max_per_sector=2, pool_n=150, delisted=False)
        self.assertTrue(tag.endswith("_group"), tag)
        self.assertIn("_norev", tag)
        self.assertIn("_sec2", tag)
        self.assertIn("_surv", tag)
        self.assertIn("_pool150", tag)

    def test_default_is_form_baseline(self):
        """省略 `strat_mode` 時等於 form（不因忘記傳而產生 `_None`／`_group`）。"""
        self.assertEqual(caliber_tag("immediate", **FORM_BASE), caliber_tag("immediate", strat_mode="form", **FORM_BASE))

    def test_baseline_values_add_nothing(self):
        """基準值（legacy 評分、池 50、TOP5、fill、不加槓桿、不停泊）都不加註。"""
        self.assertEqual(caliber_tag("signal", strat_mode="form"), "signal")

    def test_other_knobs_still_suffixed(self):
        tag = caliber_tag("immediate", dca=10000, lock_at="selection", rebal_months=3, top_n=6,
                          fixed_n=8, leverage=1.26, scale_to_util=100, market_filter=True,
                          mf_window=200, fill_mode="topup", scoring_model="zscore",
                          factor_revenue=True, pool_n=20, strat_mode="form")
        for part in ("immediate", "_dca10000", "_selection", "_rebal3", "_top6", "_fixed8",
                     "_lev1.26", "_scale100", "_mf200", "_filltopup", "_scorezscore", "_pool20"):
            self.assertIn(part, tag)

    def test_group_and_form_never_collide(self):
        for kwargs in (dict(), dict(pool_n=100), dict(market_filter=True, idle_cash_asset="0050"),
                       dict(scoring_model="zscore", factor_revenue=True, max_per_sector=2, pool_n=150)):
            self.assertNotEqual(caliber_tag("immediate", strat_mode="form", **kwargs),
                                caliber_tag("immediate", strat_mode="group", **kwargs), kwargs)


class TestHarnessWiring(unittest.TestCase):
    """回測腳本必須**共用**這支函式（不能自己再拼一份、再一次漏掉旋鈕）。"""

    @classmethod
    def setUpClass(cls):
        cls.src = HARNESS.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def test_script_imports_and_uses_helper(self):
        imported = {a.name for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)
                    and node.module == "core.backtest_rules" for a in node.names}
        self.assertIn("caliber_tag", imported)

    def test_both_output_paths_use_it(self):
        """`results/*.json` 與 `daily_*`／`exposure_*` CSV 都要走同一份後綴。"""
        self.assertIn('_suffix = _caliber_suffix()', self.src)
        self.assertIn('_tag = f"{START}_{END}_{_caliber_suffix()}"', self.src)
        self.assertNotIn('_suffix = f"{EXEC}" + (f"_dca', self.src, "舊的手工拼接又回來了")


if __name__ == "__main__":
    unittest.main()
