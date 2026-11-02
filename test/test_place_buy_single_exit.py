#!/usr/bin/env python
"""回歸測試：所有買單都必須走 `place_buy()` 這個唯一出口（2026-11-02）。

## 為什麼

實盤的閒置資金會**停泊在 0050**（v1.1.15 起預設）。停泊的錢就是「還沒買到股票」的錢，
所以真正要買股票時，**那筆錢必須先賣掉換回現金**，否則下單會因為現金不足而整筆失敗。

原本只有「策略訊號」那條買單路徑會先釋出停泊部位，其他三條漏掉：

| 買單路徑 | 原本 |
|---|---|
| 策略／auto 訊號（主流程） | ✅ 有釋出 |
| mock 路徑（`USE_REAL_API` 關） | ❌ 漏 |
| 資金加碼（`capital.txt` 有新增額度時的 keep_wait 加碼） | ❌ 漏 |
| 買入補足（`BUY_AMOUNT_OFFSET` 的 top-up） | ❌ 漏 |

⇒ 統一由 `selfselect_trader.place_buy()` 出口：它會先 `ensure_park_released_for_buy()` 再下單。

## 釘住的兩件事

① 直接呼叫 `broker.place_order(..., 'buy', ...)` 的地方，**只准**出現在
   `place_buy()`（唯一出口本身）與 `park_idle_if_due()`（買 0050 就是停泊本身，不能再釋出）；
② `place_buy()` 至少被 4 條買單路徑呼叫（少於 4 條 ⇒ 有人把它改回去直接呼叫 `broker.place_order`）。

執行：python3 -m unittest discover -s test -p 'test_place_buy_single_exit.py'
"""
import ast
import os
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "selfselect_trader.py"


def _load_ast():
    return ast.parse(_SRC.read_text(encoding="utf-8"), filename=str(_SRC))


def _enclosing_functions(tree):
    """回傳 {id(Call node): 最內層外層函式名稱}（只追 def，模組層為 None）。"""
    owner = {}

    def visit(node, current):
        for child in ast.iter_child_nodes(node):
            name = current
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if isinstance(child, ast.Call):
                owner[id(child)] = name
            visit(child, name)

    visit(tree, None)
    return owner


def _buy_place_order_sites():
    tree = _load_ast()
    owner = _enclosing_functions(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "place_order"):
            continue
        if any(isinstance(a, ast.Constant) and a.value == "buy" for a in node.args):
            found.append((owner.get(id(node)), node.lineno))
    return found


def _place_buy_call_count():
    tree = _load_ast()
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "place_buy")


class PlaceBuySingleExitTest(unittest.TestCase):

    def test_direct_buy_orders_only_in_wrapper_or_parking(self):
        sites = _buy_place_order_sites()
        owners = sorted({o for o, _ in sites})
        self.assertEqual(
            owners, ["park_idle_if_due", "place_buy"],
            "直接下買單的地方只能用 place_buy()（停泊自己的 0050 買單除外）：\n"
            + "\n".join(f"  L{ln}: {o}" for o, ln in sites))

    def test_place_buy_is_actually_used_by_all_paths(self):
        n = _place_buy_call_count()
        self.assertGreaterEqual(
            n, 4,
            f"place_buy() 只有 {n} 個呼叫點；買單路徑（策略/mock/資金加碼/買入補足）都要走它")

    def test_wrapper_releases_parking_before_order(self):
        """`place_buy()` 必須先呼叫 `ensure_park_released_for_buy()` 再 `broker.place_order`。"""
        tree = _load_ast()
        wrapper = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "place_buy":
                wrapper = node
        self.assertIsNotNone(wrapper, "找不到 place_buy()")
        body_src = ast.get_source_segment(_SRC.read_text(encoding="utf-8"), wrapper) or ""
        self.assertIn("ensure_park_released_for_buy(", body_src, "place_buy() 沒有先釋出停泊部位")
        self.assertLess(body_src.index("ensure_park_released_for_buy("),
                        body_src.index("broker.place_order("),
                        "釋出停泊必須在下單之前")


if __name__ == "__main__":
    unittest.main()
