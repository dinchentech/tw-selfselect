"""回歸測試：selfselect_trader.py 的下單失敗（order_result 含 error）必須發 TG 警示（v3.18 修復）

背景（2026-08-31 VM 錯誤：`❌ E.Sun 下單失敗: A00002: response parse Error` 重複 30+ 次，
但 Telegram 完全沒收到警示）：
E.Sun place_order 的 A00002 是「回傳 {"error": ...} dict」而非拋例外。
主迴圈 `if ('error' in order_result):` 分支內，keep_wait 有 rollback 後 continue，
但**沒有呼叫 notify_order_failure**——TG 警示只覆蓋兩種路徑：
  1. `_filled <= 0`（委託送出但未成交）→ 有通知
  2. `except Exception`（拋例外）→ 有通知
A00002 剛好落在縫隙（error dict、非例外、非未成交）→ 使用者完全不知情。

修復：`if ('error' in order_result):` 分支內、continue 前補 notify_order_failure 呼叫（所有策略通用）。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _error_branch_nodes(tree):
    """找主迴圈中 `if ('error' in order_result):` 節點"""
    found = []

    class Walker(ast.NodeVisitor):
        def visit_If(self, node):
            src = ast.unparse(node.test) if hasattr(ast, 'unparse') else ast.dump(node.test)
            if "'error'" in src and "order_result" in src:
                found.append(node)
            self.generic_visit(node)

    Walker().visit(tree)
    return found


def _branch_calls_notify(node):
    """error 分支的 body 內是否直接呼叫 notify_order_failure（含 Assign/Expr 包裝）"""
    for stmt in node.body:
        targets = []
        if isinstance(stmt, ast.Assign):
            targets = [stmt.value]
        elif isinstance(stmt, ast.Expr):
            targets = [stmt.value]
        for t in targets:
            if isinstance(t, ast.Call):
                fname = t.func
                if isinstance(fname, ast.Name) and fname.id == 'notify_order_failure':
                    return True
                if isinstance(fname, ast.Attribute) and fname.attr == 'notify_order_failure':
                    return True
    return False


class TestOrderFailNotifyRegression(unittest.TestCase):
    def test_error_branch_must_call_notify(self):
        """回歸：error dict 分支必須發 TG 警示（v3.18 修復）"""
        for name in ('selfselect_trader.py', 'plans/selfselect_trader.py'):
            p = ROOT / name
            if not p.exists():
                continue
            src = p.read_text(encoding='utf-8')
            if "order_result" not in src or "notify_order_failure" not in src:
                continue
            tree = ast.parse(src)
            branches = _error_branch_nodes(tree)
            self.assertTrue(branches, f'{name}: 找不到 error in order_result 分支')
            ok = any(_branch_calls_notify(b) for b in branches)
            self.assertTrue(ok,
                            f'{name}: error 分支內必須直接呼叫 notify_order_failure'
                            f'（A00002 等 error dict 失敗才會有 TG 警示，2026-08-31 實盤漏報）')
            return
        self.fail('找不到含 order_result 的源碼（selfselect_trader.py 或 plans/selfselect_trader.py）')


if __name__ == '__main__':
    unittest.main()
