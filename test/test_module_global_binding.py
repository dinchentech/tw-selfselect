#!/usr/bin/env python3
"""回歸測試：函式內對「模組層變數」賦值時，必須宣告 `global`（否則整支函式都當它是區域變數）。

## 事故（2026-10-25 拆專案後冒煙測試發現；原 tw-autotrader 亦有）

`main()` 裡有

    if (BROKER == 'esun'):
        USE_REAL_API = True

Python 在**編譯期**就決定名字的綁定：只要函式內任何地方對 `USE_REAL_API` 賦值，整個 `main()`
內的它都是**區域變數**。於是 `BROKER != 'esun'` 時那行永遠不執行，之後在
`... broker.get_minute_bars(...) if USE_REAL_API ...` 讀取時就
`UnboundLocalError: cannot access local variable 'USE_REAL_API' where it is not associated with a value`
⇒ **紙上/mock 券商（`BROKER=kgi`）啟動即崩**。

原專案的 `.env` 一直寫 `BROKER=esun`，所以這條路徑從來沒被執行過（典型潛伏 bug）。

## 規則

`selfselect_trader.py` 是「模組層常數 + 單一 `main()`」的結構。任何函式若對模組層的
**值**（非 import／非函式／非 class）賦值，必須在該函式內宣告 `global <name>`；否則一旦
那行賦值在某條路徑上被跳過，讀取端就會 UnboundLocalError。

`globals()['x'] = ...` 這種寫法不受影響（不是名字綁定），本測試不檢查。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "selfselect_trader.py"


def _target_names(target):
    """只收「裸名字」目標。`D[k] = v`／`obj.attr = v` 是**就地修改**，不會遮蔽模組名（不算）。"""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out = set()
        for el in target.elts:
            out |= _target_names(el)
        return out
    return set()


def module_value_names(tree):
    """模組層的「值」名稱（Assign／AnnAssign／AugAssign／For 的目標），排除 import／def／class。"""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                names |= _target_names(t)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names |= _target_names(node.target)
        elif isinstance(node, (ast.If, ast.Try, ast.While)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    for t in targets:
                        names |= _target_names(t)
    return names


def _assigned_names(fn):
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                out |= _target_names(t)
    return out


def functions_missing_global(src):
    tree = ast.parse(src)
    module_names = module_value_names(tree)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        declared = {n for g in ast.walk(node)
                    if isinstance(g, ast.Global) for n in g.names}
        # 也是 nested def 的名字（區域函式／回呼）→ 不算「模組層賦值」
        local_defs = {sub.name for sub in node.body if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in sorted(_assigned_names(node) & module_names):
            if name in declared or name in local_defs:
                continue
            bad.append((node.name, name, node.lineno))
    return bad


class GlobalBindingTest(unittest.TestCase):
    def test_no_function_shadows_module_value_without_global(self):
        offenders = functions_missing_global(TARGET.read_text(encoding="utf-8"))
        self.assertEqual(
            offenders, [],
            "這些函式對模組層變數賦值卻沒有宣告 global（會在沒執行到賦值時 UnboundLocalError）：\n"
            + "\n".join(f"  {fn}() 的 {name}（def 在 L{line}）" for fn, name, line in offenders))

    def test_checker_catches_the_known_pattern(self):
        """自驗：原事故的寫法必須被抓到（否則這條規則等於沒在檢查）。"""
        src = (
            "USE_REAL_API = False\n"
            "BROKER = 'kgi'\n"
            "def main():\n"
            "    if BROKER == 'esun':\n"
            "        USE_REAL_API = True\n"
            "    return USE_REAL_API\n"
        )
        self.assertEqual(functions_missing_global(src), [("main", "USE_REAL_API", 3)])

    def test_global_declaration_clears_the_pattern(self):
        src = (
            "USE_REAL_API = False\n"
            "BROKER = 'kgi'\n"
            "def main():\n"
            "    global USE_REAL_API\n"
            "    if BROKER == 'esun':\n"
            "        USE_REAL_API = True\n"
            "    return USE_REAL_API\n"
        )
        self.assertEqual(functions_missing_global(src), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
