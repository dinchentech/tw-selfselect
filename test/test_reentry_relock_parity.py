"""回歸測試：自選股(auto)「賣出後釋放鎖定」的**實盤 vs 回測口徑一致**（2026-09-22）。

事故（回答使用者「自選股訊號是不是有點少」時查獲）：
- **實盤**：部位歸零（賣出）後會 `AUTO_FIXED_CACHE.pop(symbol)` 釋放鎖定
  ⇒ 下次進場時 `route_strategy(acd)` **重新路由**（2006 實例：9/16 由 ma_cross 賣出、9/18 由 breakout 買回）。
- **回測**：賣出只把 `shares` 設 0，`strat` 仍留著舊值 ⇒ 同月內再次進場時**沿用舊策略**、
  不會重新路由 ⇒ 回測低估了「出場後換策略重進」的效果（實測 2015-2025 正常組 +257.5% → +291.0%）。

修法：把「賣出後釋放鎖定」抽成 `core/backtest_rules.strategy_after_exit()`（純函式、可測），
回測賣出分支呼叫它；本檔同時用 AST 檢查兩邊的接線沒有被改回去。
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.backtest_rules import strategy_after_exit  # noqa: E402


class TestStrategyAfterExit(unittest.TestCase):
    def test_lock_released_when_flat(self):
        self.assertIsNone(strategy_after_exit("breakout", 0.0),
                          "部位歸零必須釋放鎖定（否則再次進場會沿用舊策略）")
        self.assertIsNone(strategy_after_exit("breakout", -1.0))
        self.assertIsNone(strategy_after_exit(None, 0.0))

    def test_lock_kept_while_holding(self):
        self.assertEqual(strategy_after_exit("breakout", 5), "breakout")
        self.assertEqual(strategy_after_exit(None, 5), None, "未鎖定者維持未鎖定（每日重路由）")


class TestWiring(unittest.TestCase):
    def test_backtest_releases_lock_on_sell(self):
        src = (ROOT / "scripts" / "backtest_plan2_monthly_3group.py").read_text(encoding="utf-8")
        self.assertIn("strategy_after_exit", src, "回測賣出分支必須釋放鎖定")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "do_sell" in ast.dump(node.test)[:200]:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "strategy_after_exit":
                        found = True
        self.assertTrue(found, "賣出分支（do_sell）內沒有呼叫 strategy_after_exit")

    def test_live_releases_lock_when_flat(self):
        """實盤那一側的對應行為：holdings<=0 時 pop AUTO_FIXED_CACHE（不可被改掉）。"""
        src = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("AUTO_FIXED_CACHE.pop(symbol, None)", src)
        self.assertIn("holdings.get(symbol, 0) <= 0", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
