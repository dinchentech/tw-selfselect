"""回歸測試：08:40 熱重載 .env 必須「一天一次」，不得每循環重複（2026-09-07 VM 實盤發現）

背景：VM log 顯示 `🔄 08:40 熱重載 .env 完成` 在開盤前重複出現十幾次——
主迴圈 `if (is_weekday and h == 8 and m >= 40):` 的條件在 08:40~08:59 內每分鐘都成立，
且該區塊**沒有一天一次防呆**（對照同層級 `_cleanup_date`/`_rotate_key` 皆有
`globals().get(_key) != today_str` 守衛）。→ 每個循環都重跑 `_reload(override=True)`、
`load_portfolio_config()`、甚至對新標的重抓歷史資料，浪費且可能重啟 tracker。

修復：用 `globals().get('_hot_reload_date') != today_str` 當一天一次鍵，執行後寫入。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _hotreload_if_nodes(tree):
    """找 `if (is_weekday and h == 8 and m >= 40):` 節點（08:40 熱重載區塊）"""
    found = []

    class Walker(ast.NodeVisitor):
        def visit_If(self, node):
            s = ast.unparse(node.test)
            if 'h == 8' in s and 'm >= 40' in s and 'is_weekday' in s:
                found.append(node)
            self.generic_visit(node)

    Walker().visit(tree)
    return found


class TestHotReloadDailyGuard(unittest.TestCase):
    def test_hotreload_block_has_once_per_day_guard(self):
        """回歸：08:40 熱重載區塊內必須含一天一次防呆（globals().get(...) != today_str）"""
        checked = False
        for name in ('selfselect_trader.py',):
            p = ROOT / name
            if not p.exists():
                continue
            src = p.read_text(encoding='utf-8')
            # V4.36 起 08:40 的重載內文抽成共用的 `_reload_env_config()`（即時偵測也用它），
            # 所以字面訊息改成 f-string；這裡改用「呼叫點」當錨點（守衛仍必須在同一個 if 區塊內）。
            if '08:40 熱重載' not in src:
                continue
            tree = ast.parse(src)
            blocks = _hotreload_if_nodes(tree)
            self.assertTrue(blocks, f'{name}: 找不到 08:40 熱重載區塊')
            for b in blocks:
                body = ast.unparse(b)
                # 一天一次守衛的兩個特徵：globs 鍵對比 today_str
                self.assertIn('globals().get(', body,
                              f'{name}: 08:40 熱重載區塊必須有一天一次防呆'
                              f'（否則 08:40–08:59 每循環都重複 reload .env）')
                self.assertIn("today_str", body,
                              f'{name}: 08:40 熱重載區塊需以 today_str 作為一天一次鍵')
            checked = True
        self.assertTrue(checked, '找不到含 08:40 熱重載的源碼')


if __name__ == '__main__':
    unittest.main()
