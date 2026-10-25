#!/usr/bin/env python
"""回歸測試：實盤主程式**不得有未定義的名稱**（2026-10-12 事故後新增）

## 事故（V4.45 埋下、V4.52 引爆、2026-10-12 換股日爆掉）

`plans/selfselect_trader.py` 從 V4.45（2026-10-05 腿別閘門）起寫成
`_rotation_leg_ok(...)`（**多了底線**），但 import 進來的是 `rotation_leg_ok` ⇒ 這個名稱**從來沒被定義**。

為什麼潛伏 7 天沒被發現：
  · 它只在**換股日**才會被求值（`elif _is_rotation_day and ... and _rotation_leg_ok(...)`）
  · 10/05 之後到 10/12 之間**沒有任何換股日** ⇒ 第一次執行就是 2026-10-12（我們排定做 trim 的那天）
  · 既有的回歸測試從不執行 `main()`；V4.42 的 AST 檢查器只抓「區域變數綁定前使用」
    （`TestNoUseBeforeLocalBinding`），抓不到「模組層根本沒定義」

後果：容器**啟動即崩**、docker 依 restart policy 每分鐘重啟 ⇒ 一小時內 13 次，
崩潰守門員在 11:35 止血（`--restart=no`）。**當天 09:30–11:39 的交易時段全數沒跑**，
排定的 A 腿 trim 直到人工熱修補後才在 11:39 完成。

## 本測試釘住的兩件事

① **pyflakes 靜態檢查**（若環境有裝）：`selfselect_trader.py` 不得有任何 `undefined name`
   （同時檢查 root 部署版與 `plans/` 源碼版，兩者必須一致 ⇒ 順便守住「改一份忘了另一份」）；
② **不依賴外部套件的 AST 檢查**：檔案中用到的 `_rot*` / `_rotation*` 這類底線開頭的輔助名稱，
   必須在模組層被綁定（import／賦值／def）⇒ 即使沒裝 pyflakes 也能抓到同型錯誤。
"""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SRC_PATHS = [Path(_ROOT) / "plans" / "selfselect_trader.py",
              Path(_ROOT) / "selfselect_trader.py"]


def _sources():
    out = []
    for p in _SRC_PATHS:
        if p.exists():
            out.append((str(p.relative_to(_ROOT)), p.read_text(encoding="utf-8")))
    return out


def _bound_names(scope_node):
    """收集一個 scope（模組／函式）內被綁定的名稱：import、賦值、參數、except as、def/class、global。"""
    names = set()
    for n in ast.walk(scope_node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name.split(".")[0]) for a in n.names}
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
    return names


class TestNoUndefinedNames(unittest.TestCase):
    def test_files_exist(self):
        self.assertTrue(_sources(), "找不到 selfselect_trader.py（root 或 plans/）")

    def test_pyflakes_undefined(self):
        """pyflakes：不得有 undefined name（沒裝 pyflakes 就略過，但會提示）。"""
        try:
            from pyflakes.api import check
            from pyflakes.reporter import Reporter
        except ImportError:                     # pragma: no cover
            self.skipTest("未安裝 pyflakes ⇒ 只跑 AST 檢查（建議 .venv/bin/pip install pyflakes）")
        import io
        problems = []
        for rel, src in _sources():
            out = io.StringIO()
            check(src, rel, Reporter(out, out))
            bad = [ln for ln in out.getvalue().splitlines() if "undefined name" in ln]
            problems += bad
        self.assertEqual(problems, [], "實盤主程式出現未定義名稱（啟動即崩的等級）：\n" + "\n".join(problems))

    def test_underscore_helpers_are_bound(self):
        """AST：`_rot*` 這類底線輔助名稱，在**使用它的那個 scope**（模組或函式）必須有綁定。

        不依賴 pyflakes ⇒ 即使環境沒裝也能抓到同型錯誤（2026-10-12 的 `_rotation_leg_ok`）。
        """
        for rel, src in _sources():
            tree = ast.parse(src)
            module_bound = _bound_names(tree)
            for fn in [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                local_bound = _bound_names(fn)
                used = {n.id for n in ast.walk(fn)
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                        and re.match(r"^_(rot|rotation)\w*$", n.id)}
                unbound = sorted(used - local_bound - module_bound)
                self.assertEqual(unbound, [],
                                 f"{rel}::{fn.name}: 這些名稱在該 scope 沒有綁定 ⇒ 執行到就 NameError: {unbound}")

    def test_regression_name_cannot_return(self):
        """事故名稱的具體防線：不得再出現 `_rotation_leg_ok(`（正確名稱是 `rotation_leg_ok`）。"""
        for rel, src in _sources():
            self.assertEqual(src.count("_rotation_leg_ok("), 0,
                             f"{rel}: `_rotation_leg_ok` 是 2026-10-12 崩潰的元凶"
                             f"（import 的名稱沒有底線，正確是 `rotation_leg_ok`）")



if __name__ == "__main__":
    unittest.main()
