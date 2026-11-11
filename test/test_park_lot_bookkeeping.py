"""迴歸測試：停泊（0050／SELFSELECT_PARK_ASSET）與補足的記帳股數必須等於「券商實際送單股數」（2026-11-06）。

## 實盤事故（2026-11-06 13:25，v1.1.33）

```
🅿️ 停泊額度 457,206 受限於可用現金 381,560（額度≠現金）
↻  0050 4122 股餘數 <500，捨去為 4 張               ← 券商整股規則只送 4,000 股
✅ E.Sun 下單成功: 整股 buy 0050 4000 股 @ 92.55     ← 真正送出去 4,000 股
🅿️ 閒置資金停泊：買進 0050 4122 股 @ 92.55（NT$381,491）   ← 帳上記 4,122 股 ❌
🅿️ 停泊狀態已發送：0050 4,122 股 @ 均價 92.55（現價 92.50，市值 NT$381,285）
```

- 多記 **122 股／NT$11,291**（實際 4,000 股＝NT$370,200，帳面 4,122 股＝NT$381,491，差 3.05%）。
- 後果：停泊市值與總權益虛胖；下次釋出時的「估算可動用現金」跟著偏；`logs/park_asset.json`、
  `logs/park_trades.jsonl`、TG、儀表板全部沿用錯的股數。
- 為什麼對帳沒抓到：停泊交易寫 `logs/park_trades.jsonl`，**不在** `performance.csv`
  ⇒ `reconcile_broker_books`／`broker_shortfall_repair` 都不看它。

## 根因（與 2026-09-23 的一般買進事故同一類，但停泊是 2026-10-31 才加的功能，沒接到那次修正）

13:25 送整股單時 `resolve_fill()` 查不到成交（整股在 13:30 撮合）⇒ 回 `None`
⇒ 走「成交未確認，先依送單股數記帳」分支。舊寫法在該分支用**計畫股數**
（`int(n if _unknown else ...)`）⇒ 但券商整股規則（餘數 ≥500 進位、<500 捨去）會改掉真正送出的股數。

修法：三條路徑一律改用 `core.live_utils.reconcile_order_qty(requested, order_ret)`
（provider 回報 `sent_qty`／`qty` 就用它，沒有才退回 requested）：
- `park_idle_if_due()`（停泊買進）、`park_release_all()`（停泊釋出）、買入補足（DCA／top-up）。

本檔鎖住這三處，避免下一次「新增一條下單路徑」又漏掉。
"""
import ast
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_utils import reconcile_order_qty   # noqa: E402

TRADER = ROOT / "selfselect_trader.py"


def _trader_ast():
    return ast.parse(TRADER.read_text(encoding="utf-8"))


def _find_func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _func_source(node):
    return ast.unparse(node)


def _calls_to(node, func_name):
    """回傳該函式內對 `func_name(...)` 的所有呼叫節點。"""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == func_name:
            out.append(sub)
    return out


class TestReconcileQtySemantics(unittest.TestCase):
    """今天這筆的實際數字：計畫 4,122 股、券商只送 4,000 股 ⇒ 帳上必須記 4,000。"""

    def test_board_lot_round_down_uses_sent_qty(self):
        ret = {"order_no": "OK123", "sent_qty": 4000, "status": "pending"}
        self.assertEqual(reconcile_order_qty(4122, ret), 4000)

    def test_board_lot_round_up_uses_sent_qty(self):
        self.assertEqual(reconcile_order_qty(1461, {"order_no": "OK", "sent_qty": 1000}), 1000)
        self.assertEqual(reconcile_order_qty(1584, {"order_no": "OK", "sent_qty": 2000}), 2000)

    def test_falls_back_when_provider_silent(self):
        """舊版 provider／mock 沒有 sent_qty ⇒ 維持原行為（用計畫股數）。"""
        self.assertEqual(reconcile_order_qty(4122, {"order_no": "OK123"}), 4122)
        self.assertEqual(reconcile_order_qty(4122, None), 4122)

    def test_incident_cost_basis(self):
        """記帳成本必須是「實際送單股數 × 送單價」，不是計畫股數。"""
        px = 92.55
        done = reconcile_order_qty(4122, {"order_no": "OK123", "sent_qty": 4000})
        self.assertAlmostEqual(done * px, 370_200.0)
        self.assertNotAlmostEqual(done * px, 4122 * px)


class TestParkCallSitesUseReconciledQty(unittest.TestCase):
    """原始碼守門：三條路徑都必須經過 `reconcile_order_qty`，且不得再出現「計畫股數記帳」。"""

    @classmethod
    def setUpClass(cls):
        cls.tree = _trader_ast()

    def test_park_buy_uses_reconciled_qty(self):
        fn = _find_func(self.tree, "park_idle_if_due")
        self.assertIsNotNone(fn, "找不到 park_idle_if_due()")
        src = _func_source(fn)
        self.assertNotIn("int(n if _unknown", src,
                         '停泊買進又用「計畫股數 n」記帳了（券商整股規則會改動實際送出股數）')
        calls = _calls_to(fn, "reconcile_order_qty")
        self.assertTrue(calls, "park_idle_if_due() 沒有呼叫 reconcile_order_qty()")
        self.assertTrue(any(isinstance(c.args[0], ast.Name) and c.args[0].id == "n" for c in calls if c.args),
                        "停泊買進應以計畫股數 n 為 requested，向 provider 對帳")

    def test_park_release_uses_reconciled_qty(self):
        fn = _find_func(self.tree, "park_release_all")
        self.assertIsNotNone(fn, "找不到 park_release_all()")
        src = _func_source(fn)
        self.assertNotIn("int(sh if _unknown", src,
                         '停泊釋出又用「帳面持股 sh」記帳了（賣單同樣會被整股規則捨去）')
        # 2026-11-09（v1.1.36）：賣單也要避免被券商的整股進位改股數（持有 1,584 股送 2,000 股
        # ⇒ 只成交 1,000 股）。送單前先 `sell_lot_qty(sh, sh)` 對齊，對帳的 requested 是 **`_send`**。
        self.assertIn("sell_lot_qty(sh, sh)", src, "停泊釋出要先依整股規則對齊股數")
        calls = _calls_to(fn, "reconcile_order_qty")
        self.assertTrue(calls, "park_release_all() 沒有呼叫 reconcile_order_qty()")
        self.assertTrue(any(isinstance(c.args[0], ast.Name) and c.args[0].id == "_send" for c in calls if c.args),
                        "停泊釋出應以實際送單股數 _send 為 requested，向 provider 對帳")

    def test_topup_uses_reconciled_qty(self):
        """買入補足（DCA／top-up）：成交查不到時也不得直接記 `_need`。"""
        found = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "reconcile_order_qty" and node.args \
                    and isinstance(node.args[0], ast.Name) and node.args[0].id == "_need":
                found.append(node)
        self.assertTrue(found, "買入補足沒有把 _need 交給 reconcile_order_qty()")
        src = TRADER.read_text(encoding="utf-8")
        self.assertNotIn("_filled if _filled is not None else _need", src,
                         '買入補足又退回「計畫股數 _need」記帳')

    def test_visible_warning_when_qty_changes(self):
        """股數被券商改掉時要有 log（否則帳實不符只能靠對帳才發現）。"""
        for name in ("park_idle_if_due", "park_release_all"):
            fn = _find_func(self.tree, name)
            self.assertIn("記帳股數依實際送單", _func_source(fn),
                          f"{name}() 少了「股數被改動」的可見警告")


class TestOtherOrderSitesUseReconciledQty(unittest.TestCase):
    """同類缺陷的另外兩個站點：孤兒清倉（`sell_with_fill_check`）與 `keep_wait` 資金加碼。"""

    def test_sell_with_fill_check_returns_reconciled_qty(self):
        """賣 4,122 股、券商整股只賣 4,000 股 ⇒ 回傳 4,000（否則帳上多扣 122 股）。"""
        from core.live_utils import sell_with_fill_check

        class _Broker:
            def place_order(self, symbol, action, qty):
                return {"order_no": "OK", "sent_qty": 4000}
            def check_fill(self, symbol, action, order_ret, requested):
                return None            # 13:25 送整股單查不到成交（13:30 才撮合）

        done, _n, ret = sell_with_fill_check(_Broker(), '0050', 4122, {}, '2026-11-06', None, '清倉')
        self.assertEqual(done, 4000)
        self.assertEqual(ret["sent_qty"], 4000)

    def test_sell_with_fill_check_falls_back(self):
        from core.live_utils import sell_with_fill_check

        class _Broker:
            def place_order(self, symbol, action, qty):
                return {"order_no": "OK"}          # 舊版 provider 沒回報 sent_qty
            def check_fill(self, symbol, action, order_ret, requested):
                return None

        done, _n, _ret = sell_with_fill_check(_Broker(), '0050', 4122, {}, '2026-11-06', None, '清倉')
        self.assertEqual(done, 4122)

    def test_keepwait_capital_add_buy_uses_reconciled_qty(self):
        """`place_buy(symbol, buy_shares, '資金加碼需要資金')` 之後必須對帳股數。"""
        src = TRADER.read_text(encoding="utf-8")
        idx = src.find("place_buy(symbol, buy_shares, '資金加碼需要資金')")
        self.assertGreater(idx, 0, "找不到 keep_wait 資金加碼的送單呼叫")
        window = src[idx:idx + 900]
        self.assertIn('reconcile_order_qty(buy_shares, _kw_ret)', window,
                      '資金加碼的記帳股數沒對帳（券商整股規則會改 buy_shares）')


if __name__ == "__main__":
    unittest.main()
