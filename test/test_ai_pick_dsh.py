#!/usr/bin/env python
"""`scripts/ai_pick_dsh.py`（DSH 對話內選股）的回歸測試（2026-10-28）。

流程是兩步、中間用 `logs/ai_pick/<日期>/pack.json` 銜接，所以測試不需要網路、不需要模型：
1. 沒有封包就要**大聲失敗**（避免選股日與封包不一致）。
2. 合格回答 → 落地 `response.json`＋`audit.json`（含 model 標記）。
3. 不合格回答（池外標的）→ 離開碼 2，且**不得**寫出 response。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(_ROOT, "scripts", "ai_pick_dsh.py")
DAY = "2022-01-03"
POOL = ["2330", "2454", "2881"]


def make_pack_dir(root):
    d = os.path.join(root, DAY)
    os.makedirs(d, exist_ok=True)
    packs = [{"sid": s, "as_of": DAY, "price": {"close": 100.0}, "provenance": {"price": DAY}}
             for s in POOL]
    with open(os.path.join(d, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "as_of": DAY, "model": "dsh:test",
                   "packs": packs, "extra": {"quarter_point": "2021-11"}}, f)
    with open(os.path.join(d, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write("(prompt)")
    return d


def run(args, root):
    return subprocess.run([sys.executable, SCRIPT] + args + ["--audit-dir", root],
                          capture_output=True, text=True, timeout=120)


class TestDshPick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_pack_dir(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _picks(self, sids):
        return json.dumps({"as_of": DAY, "picks": [
            {"sid": s, "reasons": ["資料 [R1]"], "citations": ["R1"]} for s in sids]},
            ensure_ascii=False)

    def test_missing_pack_fails_loudly(self):
        with tempfile.TemporaryDirectory() as other:
            r = run(["--as-of", DAY, "--top-n", "2", "--picks", self._picks(["2330", "2454"])], other)
        self.assertEqual(r.returncode, 1)
        self.assertIn("找不到封包", r.stdout)

    def test_valid_picks_are_written(self):
        r = run(["--as-of", DAY, "--top-n", "2", "--picks", self._picks(["2330", "2454"]),
                 "--model", "dsh:test"], self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        resp = os.path.join(self.root, DAY, "response.json")
        self.assertTrue(os.path.exists(resp))
        audit = json.load(open(os.path.join(self.root, DAY, "audit.json"), encoding="utf-8"))
        self.assertEqual(audit["model"], "dsh:test")
        self.assertEqual(json.load(open(resp, encoding="utf-8"))["picks"][0]["sid"], "2330")

    def test_pick_outside_pool_rejected(self):
        r = run(["--as-of", DAY, "--top-n", "2", "--picks", self._picks(["2330", "9999"])], self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("不在候選池內", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.root, DAY, "response.json")),
                         "不合格的回答不得落地成 response.json")

    def test_wrong_count_rejected(self):
        r = run(["--as-of", DAY, "--top-n", "3", "--picks", self._picks(["2330", "2454"])], self.root)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
