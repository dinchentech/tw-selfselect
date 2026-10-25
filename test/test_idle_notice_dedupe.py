"""迴歸測試：非交易時段的「休眠中」訊息只印一次（2026-09-22）。

實況（VM 日誌）：`💤 非交易時段，下次開盤 09/22 09:00，休眠中...`
原本**每一輪**（非交易時段每小時一輪）都印一次 ⇒ `docker logs --tail 50` 幾乎全是同一行，
真正的訊息（啟動 banner、報告、選股、錯誤）被洗掉。使用者要求：同一段非交易時段只印一次。

修法：`core/live_utils.should_emit_idle_notice(state, key)` 去重（key＝下次開盤時間），
在 `selfselect_trader.py` 用它包住該行 print。key 改變（跨日/換開盤時間）或行程重啟才會再印一次。
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_utils import should_emit_idle_notice  # noqa: E402


class TestIdleNoticeDedupe(unittest.TestCase):
    def test_prints_once_per_key(self):
        state = {}
        self.assertTrue(should_emit_idle_notice(state, "2026-09-22 09:00"))
        self.assertFalse(should_emit_idle_notice(state, "2026-09-22 09:00"))
        self.assertFalse(should_emit_idle_notice(state, "2026-09-22 09:00"))

    def test_prints_again_when_key_changes(self):
        state = {}
        self.assertTrue(should_emit_idle_notice(state, "2026-09-22 09:00"))
        self.assertTrue(should_emit_idle_notice(state, "2026-09-23 09:00"),
                        "跨日/換開盤時間應該重新提示一次")

    def test_state_is_reusable_dict(self):
        state = {"other": "x"}
        should_emit_idle_notice(state, "k1")
        self.assertEqual(state["other"], "x", "不得清掉同一個 state 的其他欄位")


class TestLiveTraderWiring(unittest.TestCase):
    """AST 檢查：`💤 非交易時段…` 的 print 必須被 should_emit_idle_notice 包住。"""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse((ROOT / "selfselect_trader.py").read_text(encoding="utf-8"))

    def test_idle_print_is_guarded(self):
        guarded = False
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (isinstance(test, ast.Call) and getattr(test.func, "id", "") == "should_emit_idle_notice"):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "print":
                    for arg in sub.args:
                        for const in ast.walk(arg):
                            if (isinstance(const, ast.Constant) and isinstance(const.value, str)
                                    and "非交易時段" in const.value):
                                guarded = True
        self.assertTrue(guarded, "selfselect_trader.py 的『非交易時段』print 沒有被去重包住")


if __name__ == "__main__":
    unittest.main(verbosity=2)
