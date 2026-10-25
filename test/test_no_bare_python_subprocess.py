#!/usr/bin/env python
"""硬規則測試：**不得用裸 `python`／`python3` 呼叫子程序**（要用 `sys.executable`）。

為什麼（2026-10-17 實測事故）：`手動選股工具` 用
`subprocess.run(["python", "scripts/stock_selector_grid.py", ...])` 呼叫選股；
容器內剛好有 `python` 所以一直沒炸，但**本機沒有 `python`**（只有 `python3`／`.venv/bin/python`）
⇒ 使用手冊叫使用者「在本機補跑選股」時直接
`FileNotFoundError: [Errno 2] No such file or directory: 'python'`。
同一類問題也在 `core/rotate_scheduler.run_rotation_selection()`（主程式自動選股）裡。

正確寫法：`[sys.executable, "scripts/..."]`（本機與容器都成立）。
"""
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ('scripts', 'core', 'plans', 'utils', 'data', 'strategies')
# 只看「程式碼裡把 python 當執行檔」的寫法；註解、字串說明不算
_PATTERN = re.compile(r"""\[\s*["']python3?["']\s*,""")


class NoBarePythonTest(unittest.TestCase):
    def test_no_bare_python_in_subprocess_calls(self):
        offenders = []
        for d in _SCAN_DIRS:
            base = _ROOT / d
            if not base.is_dir():
                continue
            for f in sorted(base.rglob('*.py')):
                if '__pycache__' in f.parts:
                    continue
                for i, line in enumerate(f.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
                    code = line.split('#', 1)[0]
                    if _PATTERN.search(code):
                        offenders.append(f'{f.relative_to(_ROOT)}:{i}: {line.strip()[:100]}')
        self.assertEqual(offenders, [],
                         '不得用裸 python 呼叫子程序（容器內有、本機沒有）⇒ 改用 sys.executable：\n'
                         + '\n'.join(offenders))



if __name__ == '__main__':
    unittest.main()
