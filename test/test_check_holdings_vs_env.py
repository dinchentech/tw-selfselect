"""迴歸測試：`scripts/check_holdings_vs_env.py` 的孤兒持股判定（2026-09-22）。

為什麼要這支工具：picker 的「已持倉保留」曾因格式 bug 失效 ⇒ 照著它的「汰換」名單改 `.env`
會把持有中的股票從 `.env` 移除 ⇒ 實盤孤兒清倉在下一個交易日開盤賣掉。
本工具必須能明確分出三類：孤兒持股（危險）、汰換候選（安全）、正常。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "_check_holdings", ROOT / "scripts" / "check_holdings_vs_env.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestClassify(unittest.TestCase):
    def test_orphan_detected(self):
        env = {"3017": {"strategy": "keep_wait"}}
        held = {"3017": 94, "9999": 10}
        orphans, replaceable, _ = mod.classify(env, held)
        self.assertEqual(orphans, ["9999"], "有股數但不在 .env ⇒ 孤兒（開盤會被清倉）")

    def test_replaceable_only_when_flat(self):
        env = {"2006": {"strategy": "auto"}, "2464": {"strategy": "auto"},
               "3017": {"strategy": "keep_wait"}}
        held = {"2006": 689}
        orphans, replaceable, _ = mod.classify(env, held)
        self.assertEqual(orphans, [])
        self.assertEqual(replaceable, ["2464"], "0 股且非 keep_wait 才可安全移除")
        self.assertNotIn("3017", replaceable, "keep_wait（全輪替腿）不由自選股汰換")
        self.assertNotIn("2006", replaceable, "持有中的不可列為汰換")

    def test_empty_holdings_all_monitored_are_replaceable(self):
        env = {"2006": {"strategy": "auto"}, "3017": {"strategy": "keep_wait"}}
        orphans, replaceable, _ = mod.classify(env, {})
        self.assertEqual(orphans, [])
        self.assertEqual(replaceable, ["2006"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
