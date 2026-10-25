#!/usr/bin/env python3
"""模組層參數必須在 `load_dotenv()` **之後**才讀（2026-10-23 修）。

**症狀**（2026-10-23 實測）：在本機 shell 直接跑
`python scripts/stock_selector_grid.py --recommend`，候選池是「市值前 **50**」而不是
`.env` 的 `ROTATE_STOCK_NO=100` ⇒ 本機手動選股會選出與 VM **不同的 3 檔**。
（重現 2026-10-17 B 腿選股時踩到：50 檔池完全看不到當天第 1／4／5 名的 6213／1303／2492。）

**根因**：`STOCK_NO`（L49）／`ROTATE_MODE`（L50）／`MIN_DAILY_AMOUNT`（L51）／
`LOOKBACK_DAYS`（L120）在 **import 當下** 就 `os.getenv`，而 `load_dotenv(override=True)`
寫在 L142 ⇒ 這幾個常數永遠拿不到 `.env` 的值（除非 shell 自己 export 過）。

**為何容器內看不出來**：docker-compose 的 `env_file` 在**建容器時**就把 `.env` 注入 process env；
`手動選股工具` 也是先 `load_dotenv()` 才叫子程序 ⇒ 這兩條路徑都讀得到。
⇒ 只有「本機直接跑 selector」會踩 —— 正是本專案最在意的「預覽 ≠ 實際」那類坑。
"""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELECTOR = ROOT / "scripts" / "stock_selector_grid.py"
ENV_FILE = ROOT / ".env"
DOTENV_CALL = "load_dotenv(override=True)"
ENV_READ_TOKENS = ("os.getenv(", "os.environ.get(", "os.environ[")
# 被測的模組層常數（`.env` 有設、且容器內靠 env_file 讀得到）
WATCHED = {
    "ROTATE_STOCK_NO": ("STOCK_NO", int),
    "ROTATE_MODE": ("ROTATE_MODE", int),
    "MIN_DAILY_AMOUNT": ("MIN_DAILY_AMOUNT", float),
}


def module_level_env_reads(src: str):
    """回傳 `(load_dotenv 行號或 None, [模組層 env 讀取的行號...])`。

    只看 `ast` 的**模組層**敘述（import 時就執行）——函式體裡的 `os.getenv` 是呼叫時才跑，
    與載入順序無關，不列入。
    """
    tree = ast.parse(src)
    dotenv_line, reads = None, []
    for node in tree.body:
        seg = ast.get_source_segment(src, node) or ""
        if dotenv_line is None and DOTENV_CALL in seg:
            dotenv_line = node.lineno
        if seg.lstrip().startswith("#"):
            continue
        if any(tok in seg for tok in ENV_READ_TOKENS):
            reads.append(node.lineno)
    return dotenv_line, reads


def early_env_reads(src: str):
    """模組層 env 讀取中，**早於** `load_dotenv()` 的行號清單（空 = 正確）。"""
    dotenv_line, reads = module_level_env_reads(src)
    if dotenv_line is None:
        return reads
    return [ln for ln in reads if ln < dotenv_line]


class TestHelperItself(unittest.TestCase):
    """先釘住偵測邏輯本身（否則測試可能「永遠綠」而失去意義）。"""

    def test_detects_violation(self):
        bad = ("import os\n"
               "A = int(os.getenv('X', '1'))\n"
               "from dotenv import load_dotenv\n"
               "load_dotenv(override=True)\n")
        self.assertEqual(early_env_reads(bad), [2])

    def test_accepts_correct_order(self):
        good = ("import os\n"
                "from dotenv import load_dotenv\n"
                "load_dotenv(override=True)\n"
                "A = int(os.getenv('X', '1'))\n")
        self.assertEqual(early_env_reads(good), [])

    def test_ignores_reads_inside_functions(self):
        src = ("import os\n"
               "from dotenv import load_dotenv\n"
               "load_dotenv(override=True)\n"
               "def f():\n"
               "    return os.getenv('X')\n")
        self.assertEqual(early_env_reads(src), [])

    def test_missing_dotenv_call_is_reported(self):
        src = "import os\nA = int(os.getenv('X', '1'))\nB = int(os.getenv('Y', '2'))\n"
        self.assertEqual(early_env_reads(src), [2, 3])


class TestSelectorEnvReadOrder(unittest.TestCase):
    def test_no_module_level_env_read_before_load_dotenv(self):
        src = SELECTOR.read_text(encoding="utf-8")
        dotenv_line, reads = module_level_env_reads(src)
        self.assertIsNotNone(dotenv_line, f"{SELECTOR.name} 找不到 `{DOTENV_CALL}`")
        self.assertTrue(reads, "找不到任何模組層 env 讀取 —— 測試已失效，請更新 WATCHED/SELECTOR")
        early = early_env_reads(src)
        self.assertEqual(
            early, [],
            f"{SELECTOR.name} 這些模組層 env 讀取早於 `{DOTENV_CALL}`（L{dotenv_line}）：{early}\n"
            f"它們會拿到「shell 的值或預設值」，而不是 `.env` ⇒ 本機跑的候選池／參數與 VM 不同。\n"
            f"修法：把 `from dotenv import load_dotenv` ＋ `{DOTENV_CALL}` 移到所有 `os.getenv` 之前。")

    def test_module_constants_match_dotenv_in_clean_env(self):
        """行為測試：清掉相關環境變數後 import，常數必須等於 `.env` 的值。"""
        if not ENV_FILE.exists():
            self.skipTest("沒有 .env（CI／全新環境）")
        from dotenv import dotenv_values
        env_vals = dotenv_values(ENV_FILE)
        want = {k: env_vals[k] for k in WATCHED if env_vals.get(k) not in (None, "")}
        if not want:
            self.skipTest(".env 沒有 WATCHED 的鍵")
        code = (
            "import scripts.stock_selector_grid as sg\n"
            "print('RESULT|' + '|'.join(f'{n}={getattr(sg, a)}' for n, a in %r))\n"
            % [(a, a) for a in (info[0] for info in WATCHED.values())]
        )
        env = {k: v for k, v in os.environ.items()
               if k not in set(WATCHED) | {"STOCK_NO", "PYTHONPATH"}}
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, f"import 失敗：{r.stderr[-800:]}")
        line = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT|")]
        self.assertTrue(line, f"取不到輸出：{r.stdout[-500:]}")
        got = dict(kv.split("=", 1) for kv in line[-1][len("RESULT|"):].split("|"))
        bad = {}
        for env_key, (attr, cast) in WATCHED.items():
            if env_key not in want:
                continue
            expected = cast(want[env_key])
            if cast(got[attr]) != expected:
                bad[env_key] = f".env={want[env_key]} 但模組內 {attr}={got[attr]}"
        self.assertEqual(bad, {}, f"模組層常數讀不到 `.env`：{bad}")


if __name__ == "__main__":
    unittest.main()
