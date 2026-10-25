"""迴歸測試：累積型舊快取的提示只印**一行**（2026-09-22 使用者反映 VM_pick 洗出 16 行）。

`load_cache_or_raw` 原本會先由 `load_cache()` 印「版本不符」、再自己印「為舊格式…原樣讀入」
⇒ 同一個檔案兩行、看起來像兩個問題（使用者實際提問「前面那些警告有問題嗎？」）。
現在合併成一行，且**行為不變**（舊檔照樣原樣讀入、不重建）。
"""
import io
import pickle
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cache_io import load_cache, load_cache_or_raw  # noqa: E402


class TestLegacyCacheMessage(unittest.TestCase):
    def _legacy(self, td):
        p = Path(td) / "old.pkl"
        p.write_bytes(pickle.dumps({"2330": 1}))          # 裸資料＝舊格式
        return p

    def test_one_line_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._legacy(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                data, meta = load_cache_or_raw(p)
            lines = [l for l in buf.getvalue().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1, f"應該只有一行訊息，實際 {len(lines)}：{lines}")
            self.assertIn("原樣讀入", lines[0])
            self.assertEqual(data, {"2330": 1}, "舊檔仍要原樣讀入（不重建）")
            self.assertEqual(meta, {})

    def test_load_cache_direct_still_warns(self):
        """可重建型快取的呼叫端（直接呼叫 load_cache）仍要看得到版本不符訊息。"""
        with tempfile.TemporaryDirectory() as td:
            p = self._legacy(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                data, meta = load_cache(p)
            self.assertIsNone(data)
            self.assertIn("版本不符", buf.getvalue())

    def test_quiet_suppresses(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._legacy(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                load_cache(p, quiet=True)
            self.assertEqual(buf.getvalue(), "")

    def test_v2_cache_prints_nothing(self):
        from core.cache_io import dump_cache
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "new.pkl"
            dump_cache(p, {"2330": 1}, {"source": "test"})
            buf = io.StringIO()
            with redirect_stdout(buf):
                data, meta = load_cache_or_raw(p)
            self.assertEqual(buf.getvalue(), "")
            self.assertEqual(data, {"2330": 1})
            self.assertEqual(meta["source"], "test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
