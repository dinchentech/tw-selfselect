"""迴歸測試：picker 必須自己發現「這台機器的 logs/holdings.json 不是實盤的最新狀態」。

事故（2026-09-22，使用者點出）：我在**本機**跑 `monthly_rebalance_picker.py` 時，
本機 `logs/holdings.json` 是 9/14 的舊資料（空）⇒ picker 把**實際有持倉**的 2006／3515
也列進「賣出（汰換未持倉且未選中）」名單。若照著更新 `.env`，實盤會在下一個交易日
把這兩檔當「孤兒」清倉（`selfselect_trader.py` 的孤兒清倉路徑）——繞過策略賣訊直接賣掉。

使用者要求：「這個應該要由程式把控」⇒ 由 `core/live_utils.holdings_context_check()` 判斷，
picker 在算「賣出/維持/買入」之前先檢查，不可信就**中止**（除非 `--allow-stale-holdings`）。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_utils import holdings_context_check  # noqa: E402
from scripts.monthly_rebalance_picker import read_actual_holdings  # noqa: E402


def _write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


class TestHoldingsContextCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "logs").mkdir(parents=True, exist_ok=True)
        self.env = self.dir / ".env"
        self.env.write_text(
            'PC_2006={"strategy":"auto","alloc":5.0}\n'
            'PC_3017={"strategy":"keep_wait","alloc":26.7,"max_entry_price":-1}\n',
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _touch_all(self, age_days=0.0):
        for name in ("holdings.json", "performance.csv", "report_state.json", "daily_trades.json"):
            p = self.dir / "logs" / name
            p.write_text(p.read_text(encoding="utf-8") if p.exists() else "{}", encoding="utf-8")
            ts = time.time() - age_days * 86400
            os.utime(p, (ts, ts))

    def test_ok_when_holdings_present_and_logs_fresh(self):
        # ⚠️ 用實盤真實格式（{sym: int}）；舊測試用 {"qty": N} 掩蓋了格式 bug
        _write(self.dir / "logs" / "holdings.json", {"2006": 689, "3515": 286})
        self._touch_all(0)
        ok, msg, detail = holdings_context_check(log_dir=self.dir / "logs", env_path=self.env)
        self.assertTrue(ok, msg)
        self.assertEqual(detail["held_count"], 2)

    def test_fail_when_holdings_empty_but_env_has_auto(self):
        """本機常見情況：holdings.json 空／不存在，但 .env 有 auto 監控 ⇒ 不可信。"""
        _write(self.dir / "logs" / "holdings.json", {})
        self._touch_all(0)
        ok, msg, detail = holdings_context_check(log_dir=self.dir / "logs", env_path=self.env)
        self.assertFalse(ok)
        self.assertIn("不可信", msg)
        self.assertEqual(detail["held_count"], 0)

    def test_fail_when_logs_are_stale(self):
        """logs 全部是好幾天前的 ⇒ 這台不是實盤機（今天本機 9/14 vs 實盤 9/22）。"""
        _write(self.dir / "logs" / "holdings.json", {"2006": 689})
        self._touch_all(age_days=8)
        ok, msg, detail = holdings_context_check(log_dir=self.dir / "logs", env_path=self.env)
        self.assertFalse(ok)
        self.assertIn("不可信", msg)
        self.assertGreaterEqual(detail["idle_days"], 7)

    def test_fail_when_holdings_missing_entirely(self):
        self._touch_all(0)
        ok, msg, _ = holdings_context_check(log_dir=self.dir / "logs", env_path=self.env)
        self.assertFalse(ok)


class TestHoldingsFormatCompat(unittest.TestCase):
    """2026-09-22 修掉的格式 bug：實盤寫 `{sym: int}`，picker 原本只認 `{sym: {"qty": N}}`。"""

    def test_int_format(self):
        from core.live_state import held_quantities
        self.assertEqual(held_quantities({"2006": 689, "2362": 0, "6213": 0}), {"2006": 689})

    def test_dict_format_still_works(self):
        from core.live_state import held_quantities
        self.assertEqual(held_quantities({"2006": {"qty": 689}, "x": {"qty": 0}}), {"2006": 689})

    def test_books_and_picker_share_one_implementation(self):
        from core.live_state import held_quantities
        import core.books as books
        import scripts.monthly_rebalance_picker as picker
        data = {"2006": 689}
        self.assertEqual(books.load_holdings(path=str(self._tmp_path(data))), {"2006": 689})
        # picker 的實作必須是共用函式（不得再自己寫一份）
        src = (ROOT / "scripts" / "monthly_rebalance_picker.py").read_text(encoding="utf-8")
        self.assertIn("held_quantities", src)

    def _tmp_path(self, data):
        import json, tempfile
        f = Path(tempfile.mkdtemp()) / "holdings.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        return f


class TestPickerWiring(unittest.TestCase):
    def test_picker_calls_guard_and_has_override(self):
        src = (ROOT / "scripts" / "monthly_rebalance_picker.py").read_text(encoding="utf-8")
        self.assertIn("holdings_context_check", src, "picker 必須呼叫 holdings 脈絡檢查")
        self.assertIn("--allow-stale-holdings", src, "必須提供明確的覆寫旗標")
        self.assertIn("sys.exit(2)", src, "不可信時必須中止（非只警告）")
        self.assertIn("def read_actual_holdings", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
