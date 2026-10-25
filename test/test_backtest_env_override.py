#!/usr/bin/env python
"""回歸測試：回測工具的「明確環境變數覆寫」不可被 `.env` 蓋掉（2026-10-05 實測到的事故）。

## 事故

`scripts/backtest_plan2_monthly_3group.py` 支援用環境變數覆寫參數（`POOL_N/TOP_N/START/END/…`）。但它在讀參數**之前**就 `import stock_selector_grid`，
而 `scripts/stock_selector_grid.py` 在 **import 時**執行 `load_dotenv(override=True)`
（2026-10-01 為了讓 `docker exec` 的工具讀到「現行 `.env`」而刻意如此）⇒ **`.env` 的值會蓋掉呼叫端傳入的值**。

實測症狀：`MIN_DRAW_BACK=0 ... backtest_rotation_historical.py` 的輸出裡卻是 `"min_drawback": 30.0`
（`.env` 的 `MIN_DRAW_BACK=30`），而且 `skipped_quarters` 照樣跳過 4 季 —— 也就是**該維度的掃描整批無效**，
但表面上完全看不出來（數字漂亮、無錯誤訊息）。

## 修法

回測腳本在 import（會載 `.env`）**之前**先快照呼叫端明確設定的鍵，import 之後再套回去
⇒ 語義變成「**明確指定的 CLI/env 參數 > `.env`**」，與一般 CLI 工具直覺一致（`.env` 只是預設值來源）。

⚠️ 專案的 MDB 掃描工具（`backtest_mindrawback_sweep.py`／`backtest_rotation_grid_sweep.py`）
是**以函式參數**傳 `min_drawback=`（不是環境變數）⇒ 不受此事故影響，既有定案結論仍有效。
"""
import os
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import (ENV_OVERRIDE_KEYS, apply_env_overrides,  # noqa: E402
                                 snapshot_env_overrides)

HARNESS = Path(_ROOT) / "scripts" / "backtest_plan2_monthly_3group.py"


class TestEnvOverrideSnapshot(unittest.TestCase):
    def test_snapshot_keeps_only_known_keys_that_are_set(self):
        env = {"MIN_DRAW_BACK": "0", "PATH": "/bin", "CW": "0.5"}
        snap = snapshot_env_overrides(env=env)
        self.assertEqual(snap, {"MIN_DRAW_BACK": "0", "CW": "0.5"})
        self.assertNotIn("PATH", snap, "不可把整個環境都抓進來")

    def test_snapshot_ignores_unset_keys(self):
        self.assertEqual(snapshot_env_overrides(env={}), {})

    def test_apply_restores_clobbered_value(self):
        env = {"MIN_DRAW_BACK": "0"}
        snap = snapshot_env_overrides(env=env)
        env["MIN_DRAW_BACK"] = "30"          # 模擬 load_dotenv(override=True) 蓋掉
        env["OTHER"] = "keep"
        apply_env_overrides(snap, env=env)
        self.assertEqual(env["MIN_DRAW_BACK"], "0")
        self.assertEqual(env["OTHER"], "keep", "不該動其他鍵")

    def test_apply_does_not_inject_absent_keys(self):
        env = {}
        apply_env_overrides({"CW": "0.5"}, env=env)
        self.assertEqual(env, {"CW": "0.5"})


class TestHarnessWiring(unittest.TestCase):
    """回測腳本必須「import 前快照、import 後套回」，否則上面的修法等於沒接上。"""

    def test_harness_snapshots_before_importing_selector(self):
        src = HARNESS.read_text(encoding="utf-8")
        self.assertIn("snapshot_env_overrides", src, "回測腳本未使用快照函式")
        self.assertIn("apply_env_overrides", src, "回測腳本未把快照套回（事故會重演）")
        i_snap = src.index("snapshot_env_overrides()")
        i_import = src.index("import scripts.stock_selector_grid as ssg")
        i_apply = src.index("apply_env_overrides(_ENV_OVERRIDES)", i_snap + 1)
        self.assertLess(i_snap, i_import,
                        "快照必須在 import stock_selector_grid 之前（該 import 會載 .env 並蓋掉）")
        self.assertLess(i_import, i_apply, "套回必須在 import 之後")
        self.assertLess(i_apply, src.index('POOL_N = int(os.getenv("POOL_N"'),
                        "套回必須在讀取參數（POOL_N 等）之前")


class TestOverrideKeyCoverage(unittest.TestCase):
    def test_harness_params_are_covered(self):
        for k in ("MW", "TW", "SW", "MAF", "MP", "MOM_DAYS", "CW", "M2D", "M2W",
                  "AUTO", "MODE", "INST_CONFIRM", "INST_DAYS", "MIN_DRAW_BACK",
                  "MIN_DRAW_BACK_UNLIMITED", "STOP_LOSS_PCT", "MAX_PROFIT"):
            self.assertIn(k, ENV_OVERRIDE_KEYS, f"{k} 未納入快照清單（仍會被 .env 蓋掉）")

    def test_min_draw_back_is_the_known_collision(self):
        """`.env` 真的有 MIN_DRAW_BACK ⇒ 這就是事故鍵；清單必須含它。"""
        envfile = Path(_ROOT) / ".env"
        if envfile.exists():
            txt = envfile.read_text(encoding="utf-8")
            if "MIN_DRAW_BACK=" in txt:
                self.assertIn("MIN_DRAW_BACK", ENV_OVERRIDE_KEYS)


if __name__ == "__main__":
    unittest.main()
