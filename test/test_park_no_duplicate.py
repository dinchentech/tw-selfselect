#!/usr/bin/env python
"""回歸測試：停泊（`park_idle_if_due`）不得重複下同一筆單（2026-11-04）。

## 事故

VM log（v1.1.21、2026-11-03/04）：

```
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
```

四筆金額完全相同，且**沒有任何 `🅿️ 閒置資金停泊` 記帳訊息** ⇒ 系統自認「沒買到」，
所以下一圈（60 秒後）又用同一個 idle 再送一次。

## 兩個根因（都在同一條鏈上）

1. `resolve_fill()` 在「成交查不到」時回 **`None`**（＝不是沒成交，是查不到），
   但 `park_idle_if_due()` 寫成 `int(filled or 0)` ⇒ 當成 0 ⇒ `return 0.0`
   ⇒ 停泊帳不變 ⇒ idle 不變 ⇒ 重複下單。
2. 防重複的 `last_park_ts` 是死碼：`core.park_asset.load_state()` 漏回這個鍵
   ⇒ `st.get('last_park_ts')` 永遠 `None` ⇒ 「5 分鐘內不重複下單」永遠通過。

`park_idle_if_due()` 是 `main()` 內的巢狀函式，無法直接呼叫，因此這裡用**原始碼層級**的
不變式把它釘住（同 `test/live_trader_no_undefined_names.py` 的做法）。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SRC = _ROOT / "selfselect_trader.py"


def _func_source(name: str, include_docstring: bool = False) -> str:
    """取 `main()` 內某個巢狀函式的原始碼；預設**排除 docstring 與整行註解**。

    排除的理由：docstring 裡為了說明事故會引用舊寫法（例如 `int(filled or 0)`），
    若連 docstring 一起比對，就無法用「不得出現某字串」來守住程式碼本身。
    """
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            if include_docstring:
                return ast.get_source_segment(src, node) or ""
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            first, last = body[0], body[-1]
            lines = src.splitlines()[first.lineno - 1:last.end_lineno]
            # 同時剔除「整行註解」：註解裡為了說明事故會引用舊寫法，不能拿來當程式碼比對
            return "\n".join(l for l in lines if not l.lstrip().startswith("#"))
    raise AssertionError(f"找不到 {name}()（改名請同步更新本測試）")


def _park_func_source(include_docstring: bool = False) -> str:
    return _func_source("park_idle_if_due", include_docstring)


class TestParkNoDuplicateOrder(unittest.TestCase):

    def test_unknown_fill_is_not_treated_as_zero(self):
        """`resolve_fill()` 回 None ⇒ 必須沿用送單股數記帳，不可當成 0 股。"""
        body = _park_func_source()
        self.assertNotIn(
            "int(filled or 0)", body,
            "`int(filled or 0)` 會把『成交查不到』當成 0 ⇒ 不記帳 ⇒ 下一圈重複下單（2026-11-04 事故）")
        self.assertIn("filled is None", body,
                      "必須明確區分『查不到成交（None）』與『明確失敗（0）』")

    def test_cooldown_timestamp_written_on_success_and_on_failure(self):
        """成功與失敗兩條路都要寫 `last_park_ts`，5 分鐘冷卻才真的擋得住重送。"""
        body = _park_func_source()
        self.assertGreaterEqual(
            body.count("'last_park_ts': _now_ts"), 2,
            "成功與失敗（送單未成交）兩條路徑都要落地 last_park_ts")

    def test_rechecks_window_right_before_order(self):
        """下單前要再確認一次 13:25–13:30：迴圈可能在 13:29 起算、送單時已過 13:30（000017）。"""
        body = _park_func_source()
        self.assertIn("close_order_window_open(datetime.now())", body,
                      "停泊送單前必須再檢查一次下單窗口")
        # 位置：時間檢查要在 place_order 之前
        self.assertLess(body.index("close_order_window_open(datetime.now())"),
                        body.index("broker.place_order("),
                        "時間檢查必須在送單之前")

    def test_cooldown_still_guarded_by_last_park_ts(self):
        body = _park_func_source()
        self.assertIn("last_park_ts", body)
        self.assertIn("300", body, "沿用 5 分鐘冷卻（300 秒）")


class TestParkReleaseNoDoubleSell(unittest.TestCase):
    """鏡像缺陷：`park_release_all()` 把「成交查不到」當成 0 ⇒ 帳上還留著停泊股
    ⇒ 下次買股前再賣一次（重複賣出／賣不存在的股數）。2026-11-04 同一輪修掉。"""

    def test_unknown_fill_sells_all_planned_shares(self):
        body = _func_source("park_release_all")
        self.assertNotIn("int(filled or 0)", body,
                         "`int(filled or 0)` 會讓『查不到成交』變成 0 ⇒ 停泊帳留著已賣出的股數")
        self.assertIn("filled is None", body,
                      "必須明確區分『查不到成交（None）』與『明確沒成交（0）』")
        self.assertIn("(filled or 0)", body, "仍要保留『明確 0 股』的處理")


class TestParkCallIsReachable(unittest.TestCase):
    """停泊呼叫點必須在「交易日主區塊」內（2026-11-05 重大修正）。

    舊版把 `park_idle_if_due()` 放在兩個「必定 `time.sleep(60); continue`」的分支之後
    （交易日 08:45–13:30 主區塊、13:31+ 收盤報告區塊）⇒ 交易日結構上永遠到不了它。
    v1.1.22 之前看起來「有作用」，是因為 `close_order_window_open()` 當時沒有上限，
    停泊其實是在收盤後（14:00+）才下單 —— 那正是 `000017` 的來源。
    """

    def _main_tree(self):
        return ast.parse(SRC.read_text(encoding="utf-8"))

    def test_park_call_appears_exactly_once(self):
        tree = self._main_tree()
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "park_idle_if_due"]
        self.assertEqual(len(calls), 1, "park_idle_if_due() 只能有一個呼叫點（多個容易被 continue 繞過）")

    def test_call_is_inside_trading_block_and_before_continue(self):
        tree = self._main_tree()
        # 交易日主區塊：test 含 is_tday 且含 m <= 30（13:30 前的盤中區塊）
        block = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            seg = ast.get_source_segment(SRC.read_text(encoding="utf-8"), node.test) or ""
            if "is_tday" in seg and "m <= 30" in seg:
                block = node
                break
        self.assertIsNotNone(block, "找不到交易日主區塊（is_tday ... m <= 30）")
        call = next(n for n in ast.walk(block)
                    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "park_idle_if_due")
        self.assertLessEqual(call.lineno, block.end_lineno)
        # 呼叫點必須在同一個區塊內的 `continue` 之前（否則又會被繞過）
        conts = [n.lineno for n in ast.walk(block)
                 if isinstance(n, ast.Continue) and n.lineno > call.lineno]
        if conts:
            self.assertLess(call.lineno, min(conts),
                            "停泊呼叫點必須在該區塊的 continue 之前才執行得到")

    def test_park_amount_capped_by_cash(self):
        body = _park_func_source()
        self.assertIn("cash_available", body, "停泊必須以可用現金封頂（額度 idle ≠ 現金）")
        self.assertIn("_cash_now", body)


class TestLoadStateReturnsTs(unittest.TestCase):
    """`load_state()` 必須回 `last_park_ts`（死碼的另一半）。"""

    def test_source_mentions_key(self):
        src = (_ROOT / "core" / "park_asset.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "load_state"), None)
        self.assertIsNotNone(fn, "找不到 load_state()")
        body = ast.get_source_segment(src, fn) or ""
        self.assertIn("last_park_ts", body,
                      "load_state() 不回 last_park_ts ⇒ 停泊的 5 分鐘防重複是死碼")


if __name__ == "__main__":
    unittest.main()
