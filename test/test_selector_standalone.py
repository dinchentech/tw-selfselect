#!/usr/bin/env python
"""`stock_selector_grid.py` 必須能「獨立執行」（2026-09-14 修）。

**症狀**：`python scripts/stock_selector_grid.py --recommend` 直接跑會
`ModuleNotFoundError: No module named 'core'`。

**根因**：`sys.path.insert(0, 專案根)` 寫在 `from core.rotate_scheduler import ...`
**之後**。以 `python 工具腳本` 執行時 `sys.path[0]` 是 `scripts/`（不是 CWD），
所以那行 import 先爆掉 —— 而這正是 bot 的 `run_rotation_selection()` 與
`manual_rotation_pick.py` 呼叫它的方式。

**為何容器內沒事**：image 建置時設了 `PYTHONPATH=/app` ⇒ 本機（與任何沒設該變數的
環境）才會踩到。⇒ 這類 bug 只在「換環境」時現形，必須有測試守。

本測試**刻意清掉 PYTHONPATH** 並以子行程執行，模擬乾淨環境。
"""
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = [
    "scripts/stock_selector_grid.py",
]


class TestScriptsRunStandalone(unittest.TestCase):
    def _run(self, rel):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(
            [sys.executable, rel, "--help"],
            cwd=_ROOT, env=env, capture_output=True, text=True, timeout=120,
        )

    def test_scripts_runn_from_stdin(self):
        """容器內常用 `docker exec -i ... python - < 腳本`（沒有 __file__、CWD=/app）。

        2026-09-14 踩到：腳本用 `__file__` 推專案根 → 以 stdin 執行時 NameError。
        """
        import glob
        bad = []
        for rel in ("scripts/append_selector_prices.py",):
            with open(os.path.join(_ROOT, rel), "rb") as f:
                src = f.read()
            r = subprocess.run([sys.executable, "-", "--help"], cwd=_ROOT,
                               input=src, capture_output=True, timeout=120)
            # --help 不會碰到 _ROOT 推導 → 另外用「真的跑一次」驗證路徑解析。
            # CWD 用專案根（實際用法就是如此：容器內 CWD=/app）；
            # 若 __file__='<stdin>' 被 abspath 成 '/app/<stdin>' ⇒ _ROOT 會多退一層 ⇒ import core 失敗 ✓ 測得到。
            if rel.endswith("append_selector_prices.py"):
                r2 = subprocess.run([sys.executable, "-", "--symbols", "9999"],
                                    cwd=_ROOT, input=src, capture_output=True, timeout=120)
                if r2.returncode != 0 or b"Traceback" in r2.stderr:
                    bad.append((rel + " (stdin 執行)", r2.stderr.decode()[-400:]))
            if r.returncode != 0:
                bad.append((rel, r.stderr.decode()[-400:]))
        self.assertEqual(bad, [], f"以下腳本無法以 stdin 執行：{bad}")

    def test_no_raw_file_based_paths_in_selector(self):
        """路徑一律走 `_ROOT`（stdin 執行時 __file__ 是 '<stdin>' ⇒ 相對推導會多退一層）。

        2026-09-14 事故：以 stdin 執行時 `CAP_RANKING` 被算成 `/cache/...`（不存在）
        ⇒ 候選池為空 ⇒ 舊碼掉進 range(1101,9999) 假池 ⇒ 狂抓 ~8900 檔把 VM 打掛。
        """
        with open(os.path.join(_ROOT, "scripts", "stock_selector_grid.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for bad in ('os.path.dirname(os.path.abspath(__file__)), ".."',
                    'os.path.dirname(__file__), ".."'):
            self.assertTrue(bad not in src, f"仍有以 __file__ 相對推導的路徑：{bad}")
        self.assertTrue('os.getcwd()' in src, "必須有 <stdin> 時改用 CWD 的判斷")



if __name__ == "__main__":
    unittest.main()


class TestCandidatePoolRobustness(unittest.TestCase):
    """候選池：容忍舊格式，但**絕不可**退回假池（2026-09-14 VM 事故）。

    事故：VM 上 `mcap_ranking.pkl` 讀不出池子時，舊碼退回 `range(1101, 9999)`
    （~8,900 個不存在/極冷門代號）⇒ 狂抓 yfinance，把 VM 打到 SSH 連不上，
    而且選出來的股票毫無意義。現在必須**大聲失敗**。
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util
        # 只載入原始碼做靜態檢查（import 本體會連 FinMind）
        cls.src = open(os.path.join(_ROOT, "scripts", "stock_selector_grid.py"),
                       encoding="utf-8").read()

    def test_no_bogus_range_fallback_in_source(self):
        # 比對「實際程式碼模式」而非字串存在與否（註解裡也會提到那個 range）
        self.assertTrue("CANDIDATE_POOL = [str(i) for i in range(" not in self.src,
                        "不可用 range(1101,9999) 假池填候選池")
        self.assertTrue("raise SystemExit(3)" in self.src,
                        "讀不到候選池必須明確中止（不可靜默用假池）")

    def test_pool_builder_accepts_list_and_dict_payloads(self):
        import types
        ns = {"os": os, "sys": sys}
        # 取出 build_candidate_pool 與其依賴，避免 import 整個模組（會連 FinMind）
        start = self.src.index("def build_candidate_pool(")
        end = self.src.index("CANDIDATE_POOL = []")
        exec(compile(self.src[start:end], "<pool>", "exec"), ns)
        build = ns["build_candidate_pool"]
        names = ["2330", "2454", "abc", "12", "2317", "9999"]
        self.assertEqual(build(names, 2), ["2330", "2454"])
        self.assertEqual(build({"data": names}, 2), ["2330", "2454"])   # 舊 payload
        self.assertEqual(build({"meta": {}}, 2), [])                     # 認不出 → 空
        self.assertEqual(build(None, 2), [])
        self.assertEqual(build("junk", 2), [])
