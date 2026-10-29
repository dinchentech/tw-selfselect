#!/usr/bin/env python
"""選股口徑 preset（`core/selection_presets.py`）＋實盤因子開關的迴歸測試。

背景（2026-10-29 使用者裁定）：**不能替使用者決定全部**，但也不能什麼都不做——
「總報酬超過 0050 的組合都必須開營收因子的大池」，代價是回撤 −40~−53%、夏普最多打平。
所以做成**可選 preset**：預設 `current`（＝行為不變），要更高歷史報酬的人自己切，
而且切換時一定要把後果講清楚（`warning_text()`）。

守住的規則：
1. `current` 必須等於「舊行為」（池 100、營收因子關、產業上限 0）——預設不能偷偷變強。
2. 個別環境變數**一律優先**於 preset（文件寫的「明示優先」不能是假的）。
3. `aggressive` 的回撤／夏普代價必須留在 `warning_text()` 裡（避免有人日後把它刪掉、變成無聲推薦）。
"""
import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.selection_presets import (DEFAULT_PRESET, PRESETS, active_name, apply_to_env,  # noqa: E402
                                    describe, expand, resolve, warning_text)

_PRESET_KEYS = ("POOL_N", "FACTOR_REVENUE", "MAX_PER_SECTOR")


class TestPresetDefinitions(unittest.TestCase):
    def test_default_preset_is_revenue(self):
        """2026-10-29 使用者裁定：預設改成 revenue（池 100＋營收因子）。"""
        self.assertEqual(DEFAULT_PRESET, "revenue")

    def test_default_preset_numbers(self):
        knobs = PRESETS[DEFAULT_PRESET]["knobs"]
        self.assertEqual((knobs["POOL_N"], knobs["FACTOR_REVENUE"], knobs["MAX_PER_SECTOR"]),
                         ("100", "1", "0"))

    def test_current_still_available_as_old_behaviour(self):
        knobs = PRESETS["current"]["knobs"]
        self.assertEqual(knobs["POOL_N"], "100")
        self.assertEqual(knobs["FACTOR_REVENUE"], "0")
        self.assertEqual(knobs["MAX_PER_SECTOR"], "0")

    def test_revenue_and_aggressive_are_the_high_return_options(self):
        self.assertEqual(PRESETS["revenue"]["knobs"]["FACTOR_REVENUE"], "1")
        ag = PRESETS["aggressive"]["knobs"]
        self.assertEqual((ag["POOL_N"], ag["FACTOR_REVENUE"], ag["MAX_PER_SECTOR"]), ("150", "1", "2"))

    def test_resolve_unknown_raises(self):
        with self.assertRaises(ValueError):
            resolve("nope")

    def test_resolve_empty_is_none(self):
        self.assertIsNone(resolve(""))
        self.assertIsNone(resolve(None))

    def test_active_name_prefers_selfselect_then_preset_then_default(self):
        env = {"SELFSELECT_PRESET": "aggressive", "PRESET": "current"}
        self.assertEqual(active_name(env), "aggressive")
        self.assertEqual(active_name({"PRESET": "current"}), "current")
        self.assertEqual(active_name({}), "revenue")

    def test_active_name_falls_back_when_unknown(self):
        self.assertEqual(active_name({"SELFSELECT_PRESET": "亂打"}), "revenue")


class TestPresetExpansion(unittest.TestCase):
    def test_explicit_env_wins(self):
        out = expand("aggressive", {"MAX_PER_SECTOR": "0", "POOL_N": "50"})
        self.assertEqual(out["MAX_PER_SECTOR"], "0")
        self.assertEqual(out["POOL_N"], "50")
        self.assertEqual(out["FACTOR_REVENUE"], "1")      # 沒明示的才吃 preset

    def test_apply_to_env_only_fills_unset(self):
        env = {"POOL_N": "30"}
        applied = apply_to_env("aggressive", env=env)
        self.assertEqual(env["POOL_N"], "30")             # 不被覆寫
        self.assertEqual(env["FACTOR_REVENUE"], "1")
        self.assertEqual(env["MAX_PER_SECTOR"], "2")
        self.assertEqual(applied["POOL_N"], "30")

    def test_describe_mentions_every_preset(self):
        text = describe()
        for name in PRESETS:
            self.assertIn(f"`{name}`", text)


class TestHonestDisclosure(unittest.TestCase):
    def test_warning_keeps_the_costs(self):
        """後果必須寫在程式裡，不能只寫在文件（文件會漂移，程式不會）。"""
        w = warning_text()
        for must in ("回撤", "夏普", "walk-forward"):
            self.assertIn(must, w)

    def test_aggressive_desc_states_drawdown_and_caveat(self):
        """必須寫出回撤、與 0050 的比較、以及「事後挑選／未驗證」的警語（不能只寫好處）。"""
        desc = PRESETS["aggressive"]["desc"]
        self.assertIn("−40.2%", desc)
        self.assertIn("0050", desc)
        self.assertIn("walk-forward", desc)


class TestLiveFactorKnobs(unittest.TestCase):
    """實盤 picker 的因子開關（模組層讀 env；用 reload 驗證）。"""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("SELFSELECT_PRESET", "PRESET", "SELFSELECT_FACTOR_REVENUE", "FACTOR_REVENUE",
                        "SELFSELECT_MAX_PER_SECTOR", "MAX_PER_SECTOR", "SELFSELECT_POOL_N",
                        "POOL_N")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from unittest import mock
        import scripts.monthly_rebalance_picker as picker
        with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
            importlib.reload(picker)      # 回到乾淨狀態，避免汙染其他測試

    _LIVE_KEYS = ("SELFSELECT_PRESET", "PRESET", "SELFSELECT_FACTOR_REVENUE", "FACTOR_REVENUE",
                  "SELFSELECT_MAX_PER_SECTOR", "MAX_PER_SECTOR", "SELFSELECT_POOL_N", "POOL_N")

    def _reload(self, **env):
        """重載 picker，並在沒有任何 `.env` 影響的環境下驗證模組層設定。

        `importlib.reload` 只會重跑 picker 自己；但它依賴的 `scripts.stock_selector_grid`
        也會 `load_dotenv(override=True)`，所以先把 picker／ssg 都匯入一次（讓它們進快取），
        之後重載時就不會再被 `.env` 蓋回真實設定。
        """
        from unittest import mock

        import scripts.monthly_rebalance_picker as picker
        import scripts.stock_selector_grid  # noqa: F401  ← 先匯入，避免重載時又讀 .env
        for k in self._LIVE_KEYS:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = str(v)
        with mock.patch("dotenv.load_dotenv", lambda *a, **k: None), \
                mock.patch("dotenv.main.load_dotenv", lambda *a, **k: None):
            return importlib.reload(picker)

    def test_default_is_revenue(self):
        p = self._reload()
        self.assertEqual(p.SELECTION_PRESET, "revenue")
        self.assertTrue(p.FACTOR_REVENUE, "預設（revenue）應開啟營收因子")
        self.assertEqual(p.MAX_PER_SECTOR, 0)
        self.assertEqual(p.PRESET_KNOBS.get("POOL_N"), "100")

    def test_current_opt_out_turns_factor_off(self):
        p = self._reload(SELFSELECT_PRESET="current")
        self.assertFalse(p.FACTOR_REVENUE)
        self.assertEqual(p.MAX_PER_SECTOR, 0)

    def test_backtest_only_keys_do_not_leak_into_live(self):
        """`FACTOR_REVENUE` / `POOL_N`（回測旋鈕）躺在同一份 .env 時，不能偷改實盤設定。"""
        p = self._reload(FACTOR_REVENUE="0", POOL_N="20", MAX_PER_SECTOR="2")
        self.assertTrue(p.FACTOR_REVENUE, "實盤只看 preset 與 SELFSELECT_*，不看回測旋鈕")
        self.assertEqual(p.MAX_PER_SECTOR, 0)
        self.assertEqual(p.PRESET_KNOBS.get("POOL_N"), "100")

    def test_preset_current_turns_factor_off(self):
        p = self._reload(SELFSELECT_PRESET="current")
        self.assertEqual(p.SELECTION_PRESET, "current")
        self.assertFalse(p.FACTOR_REVENUE)
        self.assertEqual(p.MAX_PER_SECTOR, 0)

    def test_preset_aggressive_sets_cap_and_pool(self):
        p = self._reload(SELFSELECT_PRESET="aggressive")
        self.assertEqual(p.MAX_PER_SECTOR, 2)
        self.assertEqual(p.PRESET_KNOBS.get("POOL_N"), "150")
        self.assertTrue(p.FACTOR_REVENUE)

    def test_explicit_factor_env_beats_preset(self):
        p = self._reload(SELFSELECT_PRESET="revenue", SELFSELECT_FACTOR_REVENUE="0")
        self.assertFalse(p.FACTOR_REVENUE, "明示 SELFSELECT_FACTOR_REVENUE=0 必須優先")

    def test_explicit_pool_env_beats_preset_pool(self):
        p = self._reload(SELFSELECT_PRESET="aggressive", SELFSELECT_POOL_N="50")
        self.assertEqual(p.PRESET_KNOBS.get("POOL_N"), "50")


class TestOrchestratorPoolN(unittest.TestCase):
    def test_pool_n_from_preset(self):
        from scripts.monthly_selfselect_run import resolve_pool_n
        self.assertEqual(resolve_pool_n(env={"SELFSELECT_PRESET": "aggressive"}), 150)
        self.assertEqual(resolve_pool_n(env={"SELFSELECT_PRESET": "revenue"}), 100)
        self.assertEqual(resolve_pool_n(env={"SELFSELECT_PRESET": "current"}), 100)

    def test_explicit_pool_n_wins(self):
        from scripts.monthly_selfselect_run import resolve_pool_n
        self.assertEqual(resolve_pool_n(env={"SELFSELECT_PRESET": "aggressive",
                                             "SELFSELECT_POOL_N": "50"}), 50)
        self.assertEqual(resolve_pool_n(60, env={"SELFSELECT_PRESET": "aggressive"}), 60)

    def test_no_env_gives_default_preset_pool(self):
        from scripts.monthly_selfselect_run import resolve_pool_n
        self.assertEqual(resolve_pool_n(env={}), 100)   # 預設 preset revenue 的池就是 100


class TestOverrideKeysCoverSelectionKnobs(unittest.TestCase):
    def test_knobs_are_snapshotted(self):
        """不進 `ENV_OVERRIDE_KEYS` 的話，preset/profile 會蓋掉使用者明示的值（文件說的反過來）。"""
        from core.backtest_rules import ENV_OVERRIDE_KEYS
        for k in ("SCORING_MODEL", "FACTOR_REVENUE", "MAX_PER_SECTOR", "UNIVERSE_DELISTED",
                  "PRESET", "SELFSELECT_PRESET"):
            self.assertIn(k, ENV_OVERRIDE_KEYS)


if __name__ == "__main__":
    unittest.main()
