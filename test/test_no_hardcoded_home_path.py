"""硬規則測試：程式碼**不得寫死作者的家目錄**（`/home/frank/...`）。

為什麼（2026-09-22 實測事故）：`scripts/monthly_rebalance_picker.py` 在模組層做
`sys.path.insert(0, "/home/frank/tw-autotrader")` ＋ `os.chdir("/home/frank/tw-autotrader")`，
本機（WSL）跑沒問題，但 **container 內根本沒有這個路徑** ⇒ `docker exec tw_selfselect_bot python
scripts/monthly_rebalance_picker.py …` 會在 import 時 FileNotFoundError／ModuleNotFoundError
（新工具 `check_holdings_vs_env.py` 就是這樣在 VM 上炸掉的：`No module named 'core'`）。
而 `使用手冊` 的自選股 SOP 正是叫使用者在 container 內跑它。

正確寫法（同時適用本機與容器，container 的 cwd 已是 `/app`）：
    _f = globals().get("__file__", "")
    _ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
             if _f and not str(_f).startswith("<") else os.getcwd())
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    if os.path.isdir(_ROOT):
        os.chdir(_ROOT)
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["scripts", "core", "strategies", "data", "utils", "config"]
SCAN_ROOT_FILES = ["selfselect_trader.py", "backtest.py", "backtest_finmind.py",
                   "simulate_portfolio.py", "user_strategies.py"]

# 允許出現家目錄的地方：文件字串中提到路徑範例不算（本測試只看程式碼行）
PATTERN = re.compile(r'/home/[A-Za-z0-9_.-]+/')


def iter_sources():
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p
    for name in SCAN_ROOT_FILES:
        p = ROOT / name
        if p.exists():
            yield p


class TestNoHardcodedHomePath(unittest.TestCase):
    def test_no_home_path_in_code(self):
        offenders = []
        for p in iter_sources():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if PATTERN.search(line):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "不得寫死家目錄（容器內不存在）：\n" + "\n".join(offenders))

    def test_container_critical_scripts_use_repo_root(self):
        """會被 `docker exec` 呼叫的腳本必須用動態推導的 `_ROOT`。"""
        for rel in ["scripts/monthly_rebalance_picker.py",
                    "scripts/check_holdings_vs_env.py",
                    "scripts/reconcile_total_assets.py",
                    "scripts/monthly_selfselect_run.py"]:
            p = ROOT / rel
            if not p.exists():
                continue
            src = p.read_text(encoding="utf-8")
            # 兩種可接受的寫法：動態 _ROOT，或以 __file__ 推導（manual_rotation_pick.py 屬後者）
            self.assertTrue(
                "_ROOT" in src or "os.path.abspath(__file__)" in src,
                f"{rel} 應以動態路徑（_ROOT 或 __file__）推導專案根")
            self.assertNotIn('os.chdir("/home', src, f"{rel} 不該 chdir 到寫死路徑")


if __name__ == "__main__":
    unittest.main(verbosity=2)
