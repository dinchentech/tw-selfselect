#!/usr/bin/env python
"""`core.backtest_rules.leverage_for_target()` 的回歸測試（2026-10-28）。

需求：自選股腿的平均曝險通常 < 100%（等訊號、剛換股空倉）⇒ 要一個參數把「平均資本」
等效拉大到 100% 再算報酬%。`LEVERAGE`（固定倍數）／`SCALE_TO_UTIL`（自動兩段式）
就是用它把量到的 `util_avg` 換成部位倍數。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.backtest_rules import leverage_for_target  # noqa: E402


class TestLeverageForTarget(unittest.TestCase):
    def test_measured_util_to_100pct(self):
        # 實測正常組 2022-2025 平均曝險 79.1% ⇒ 要放大 ~1.264 倍才用滿
        self.assertAlmostEqual(leverage_for_target(0.791, 100), 100 / 79.1, places=6)
        self.assertAlmostEqual(leverage_for_target(0.579, 100), 100 / 57.9, places=6)

    def test_never_shrinks_positions(self):
        """目標低於實際曝險（或本來就 >100%）⇒ 不做任何縮小，回 1.0。"""
        self.assertEqual(leverage_for_target(0.9, 50), 1.0)
        self.assertEqual(leverage_for_target(1.0, 100), 1.0)
        self.assertEqual(leverage_for_target(1.2, 100), 1.0)

    def test_clamped_to_max(self):
        """曝險極低（例如 5%）時不要算出 20 倍這種荒謬槓桿。"""
        self.assertEqual(leverage_for_target(0.05, 100), 5.0)
        self.assertEqual(leverage_for_target(0.2, 100, max_leverage=3.0), 3.0)

    def test_bad_inputs_return_one(self):
        for util, target in [(0, 100), (-0.1, 100), (0.8, 0), (None, 100), (0.8, None),
                             ("x", 100), (0.8, "y")]:
            self.assertEqual(leverage_for_target(util, target), 1.0, (util, target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
