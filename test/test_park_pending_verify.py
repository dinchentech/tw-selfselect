#!/usr/bin/env python
"""回歸測試：停泊「成交未確認 ⇒ 隔天用券商快照收斂」（2026-11-23，v1.1.46）。

## 事故（VM 實況，兩次部分成交把停泊帳帶偏）

```
11/09 停泊釋出：送 4,000 股 → 券商只成 1,000 股（qty_sm=1000）   bot 記 4,000 ❌
11/20 停泊買進：送 2,000 股 → 券商只成 1,000 股（qty_bm=1000）   bot 記 2,000 ❌
11/23 C 釋出：  送 4,000 股 → 券商成 0 股                        bot 記 4,000 ❌
```

⇒ 帳本 `park_position.json` 變成 0 股，券商實際約 6,000 股。

## 修法

送單當下仍依送單股數記帳（否則下一圈會重複下單），但把動作寫進 `pending_verify`；
**下一個下單窗口**先讀當天落地的 `logs/broker_snapshot_<date>.json`：

1. `transactions`（成交回報）優先；2. 沒有就退回 `inventories` 的 `qty_bm`／`qty_sm`；
3. 兩者都沒有 ⇒ 明天再試；連續 5 天沒有 ⇒ 放棄自動收斂（保留原帳、只印警告）。

## 另一個口徑修正

`broker_holding_qty()`／`reconcile_broker_books.parse_inventories()` 原本取 `qty_b`
（**委託量**）⇒ 11/20 把「只成交 1,000 股」報成「券商 2,000 股」。改為優先取 `qty_bm`（成交量）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.park_asset import load_state, reconcile_pending, save_state  # noqa: E402
from core.live_utils import broker_holding_qty  # noqa: E402
import scripts.reconcile_broker_books as rbb  # noqa: E402


def _tx(sym, side, qty, price="84.40"):
    return {"stk_no": sym, "buy_sell": side, "qty": str(qty), "price_avg": price}


def _inv(sym, qty_bm, qty_sm, qty_b="0"):
    return {"stk_no": sym, "qty_bm": str(qty_bm), "qty_sm": str(qty_sm), "qty_b": str(qty_b)}


def _pending(act, shares, price, avg=0.0, day="2026-11-20"):
    return {"act": act, "symbol": "0050", "shares": shares, "price": price,
            "avg": avg, "date": day, "ts": day + "T13:25:00"}


class TestReconcileSell(unittest.TestCase):
    """停泊釋出（SELL）的部分／零成交收斂。"""

    def test_partial_fill_adds_back_unsold_shares(self):
        # 11/09 實例：送 4,000、只成 1,000（成本基礎 92.55/股）
        res = reconcile_pending(_pending("SELL", 4000, 97.60, avg=92.55),
                                [_tx("0050", "S", 1000, "97.60")], [], "2026-11-09")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["matched"], 1000)
        self.assertEqual(res["shares_delta"], 3000)
        self.assertAlmostEqual(res["cost_delta"], 3000 * 92.55, places=2)

    def test_zero_fill_adds_everything_back(self):
        # 11/23 實例：送 4,000、成交 0（快照 transactions 空、qty_sm=0）
        res = reconcile_pending(_pending("SELL", 4000, 87.20, avg=92.875, day="2026-11-23"),
                                [], [_inv("0050", 0, 0)], "2026-11-23")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["matched"], 0)
        self.assertEqual(res["shares_delta"], 4000)
        self.assertAlmostEqual(res["cost_delta"], 4000 * 92.875, places=2)

    def test_full_fill_is_noop(self):
        res = reconcile_pending(_pending("SELL", 1000, 97.60, avg=92.55),
                                [_tx("0050", "S", 1000)], [], "2026-11-09")
        self.assertEqual((res["status"], res["shares_delta"], res["cost_delta"]), ("ok", 0, 0.0))


class TestReconcileBuy(unittest.TestCase):
    """停泊買進（BUY）的部分／全額成交收斂。"""

    def test_partial_fill_removes_phantom_shares(self):
        # 11/20 實例：送 2,000、只成 1,000 @ 84.40
        res = reconcile_pending(_pending("BUY", 2000, 84.40),
                                [_tx("0050", "B", 1000)], [], "2026-11-20")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["matched"], 1000)
        self.assertEqual(res["shares_delta"], -1000)
        self.assertAlmostEqual(res["cost_delta"], -1000 * 84.40, places=2)

    def test_inventory_fallback_uses_filled_qty(self):
        res = reconcile_pending(_pending("BUY", 2000, 84.40), [],
                                [_inv("0050", 1000, 0, qty_b="2000")], "2026-11-20")
        self.assertEqual((res["status"], res["matched"], res["shares_delta"]), ("ok", 1000, -1000))

    def test_full_fill_is_noop(self):
        res = reconcile_pending(_pending("BUY", 2000, 84.40), [_tx("0050", "B", 2000)], [], "2026-11-20")
        self.assertEqual((res["status"], res["shares_delta"]), ("ok", 0))


class TestReconcileNoData(unittest.TestCase):
    """查不到成交：先留著、太久才放棄（不得把帳本歸零）。"""

    def test_keep_when_snapshot_has_nothing(self):
        res = reconcile_pending(_pending("SELL", 4000, 87.20, avg=92.875, day="2026-11-23"),
                                [], [], "2026-11-23")
        self.assertEqual(res["status"], "keep")
        self.assertEqual((res["shares_delta"], res["cost_delta"]), (0, 0.0))

    def test_expire_after_max_days(self):
        res = reconcile_pending(_pending("SELL", 1000, 90.0, avg=90.0, day="2026-11-23"),
                                [], [], "2026-11-30", max_days=5)
        self.assertEqual(res["status"], "expire")

    def test_bad_pending_is_dropped(self):
        for bad in ({}, {"act": "SELL"}, {"act": "BUY", "symbol": "", "shares": 1},
                    {"act": "HOLD", "symbol": "0050", "shares": 1}):
            self.assertEqual(reconcile_pending(bad, [], [], "2026-11-23")["status"], "expire",
                             f"{bad} 應被視為壞資料")

    def test_other_symbol_does_not_match(self):
        res = reconcile_pending(_pending("SELL", 1000, 90.0, avg=90.0),
                                [_tx("0051", "S", 1000)], [], "2026-11-20")
        self.assertEqual(res["status"], "keep")


class TestLoadStateKeepsPending(unittest.TestCase):
    """`load_state()` 必須保留 `pending_verify`，否則寫進去就讀不回來。"""

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            save_state({"symbol": "0050", "shares": 6000, "cost": 557250.0,
                        "last_park_ts": 1.0,
                        "pending_verify": _pending("SELL", 4000, 87.20, avg=92.875)}, path)
            st = load_state(path)
            self.assertEqual(st["pending_verify"]["act"], "SELL")
            self.assertEqual(st["pending_verify"]["shares"], 4000)
            self.assertAlmostEqual(st["pending_verify"]["avg"], 92.875, places=3)

    def test_absent_pending_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            save_state({"symbol": "0050", "shares": 0, "cost": 0.0, "last_park_ts": 0.0}, path)
            self.assertIsNone(load_state(path)["pending_verify"])


class TestBrokerQtyPrefersFilled(unittest.TestCase):
    """券商庫存取「成交量」而不是「委託量」（11/20 實證 qty_b=2000／qty_bm=1000）。"""

    class _Broker:
        def __init__(self, rows):
            self._rows = rows

        def query_inventories(self):
            return self._rows

    def test_prefers_qty_bm(self):
        rows = [{"stk_no": "0050", "qty_b": "2000", "qty_bm": "1000", "cost_qty": "1000"}]
        self.assertEqual(broker_holding_qty(self._Broker(rows), "0050"), 1000)

    def test_falls_back_to_qty_b_when_no_bm(self):
        rows = [{"stk_no": "2884", "qty_b": "2000"}]
        self.assertEqual(broker_holding_qty(self._Broker(rows), "2884"), 2000)

    def test_reconcile_tool_uses_same_caliber(self):
        rows = [{"stk_no": "0050", "qty_b": "2000", "qty_bm": "1000", "cost_qty": "1000",
                 "price_avg": "84.40", "cost_sum": "-84520", "stk_na": "元大台灣50"}]
        self.assertEqual(rbb.parse_inventories(rows)["0050"]["qty"], 1000)


class TestTraderWiring(unittest.TestCase):
    """`park_idle_if_due()` 必須：先收斂 pending、再把未確認動作寫進 pending。"""

    def setUp(self):
        import ast
        import textwrap
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "park_idle_if_due")
        body = list(fn.body)
        if isinstance(body[0], ast.Expr):
            body = body[1:]
        lines = src.splitlines()[body[0].lineno - 1:body[-1].end_lineno]
        self.body = textwrap.dedent("\n".join(l for l in lines if not l.lstrip().startswith("#")))

    def test_reconcile_called_before_gates(self):
        self.assertIn("_reconcile_park_pending(", self.body)
        self.assertLess(self.body.index("_reconcile_park_pending("),
                        self.body.index("for (_code, _why)"))

    def test_pending_recorded_on_unknown_buy(self):
        self.assertIn("pending_verifies", self.body)   # v1.1.51：佇列
        self.assertIn("'act': 'BUY'", self.body)

    def test_release_records_pending_with_avg(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        import ast
        import textwrap
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "park_release_all")
        body = list(fn.body)
        if isinstance(body[0], ast.Expr):
            body = body[1:]
        lines = src.splitlines()[body[0].lineno - 1:body[-1].end_lineno]
        seg = textwrap.dedent("\n".join(l for l in lines if not l.lstrip().startswith("#")))
        self.assertIn("'act': 'SELL'", seg)
        self.assertIn("'avg'", seg)




class TestEmptySnapshotMeansNoFill(unittest.TestCase):
    """v1.1.47：快照檔存在且沒有錯誤 ⇒ 空紀錄就是「沒成交」，要把股數加回（不能一直等）。"""

    _OK_EMPTY = {"ok": True, "errors": {}, "transactions": [], "inventories": [], "settlements": []}

    def test_sell_restores_all_when_snapshot_is_empty(self):
        res = reconcile_pending(_pending("SELL", 6000, 87.20, avg=92.875, day="2026-11-24"),
                                [], [], "2026-11-25", snapshot=self._OK_EMPTY)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["matched"], 0)
        self.assertEqual(res["shares_delta"], 6000)
        self.assertAlmostEqual(res["cost_delta"], 6000 * 92.875, places=2)

    def test_buy_removes_all_when_snapshot_is_empty(self):
        res = reconcile_pending(_pending("BUY", 2000, 84.40, day="2026-11-24"),
                                [], [], "2026-11-25", snapshot=self._OK_EMPTY)
        self.assertEqual((res["status"], res["matched"], res["shares_delta"]), ("ok", 0, -2000))
        self.assertAlmostEqual(res["cost_delta"], -2000 * 84.40, places=2)

    def test_snapshot_with_errors_keeps_waiting(self):
        snap = {"ok": True, "errors": {"sdk": "timeout"}, "transactions": [], "inventories": []}
        res = reconcile_pending(_pending("SELL", 6000, 87.20, avg=92.875, day="2026-11-24"),
                                [], [], "2026-11-25", snapshot=snap)
        self.assertEqual(res["status"], "keep")
        self.assertEqual(res["shares_delta"], 0)

    def test_no_snapshot_file_keeps_waiting(self):
        res = reconcile_pending(_pending("SELL", 6000, 87.20, avg=92.875, day="2026-11-24"),
                                [], [], "2026-11-25", snapshot=None)
        self.assertEqual(res["status"], "keep")

    def test_real_11_23_snapshot_is_treated_as_no_fill(self):
        """11/23 的快照（transactions/inventories/settlements 全空、errors {}）⇒ 那筆 4,000 股確實沒成交。"""
        snap = {"ok": True, "errors": {}, "transactions": [], "inventories": [],
                "settlements": [], "summary": {"transactions": 0, "inventories": 0}}
        res = reconcile_pending(_pending("SELL", 4000, 87.20, avg=91.00, day="2026-11-23"),
                                [], [], "2026-11-24", snapshot=snap)
        self.assertEqual((res["status"], res["shares_delta"]), ("ok", 4000))


class TestTraderPendingWiring47(unittest.TestCase):
    """`_reconcile_park_pending()` 要傳 snapshot、expire 要發 TG。"""

    def _fn(self, name):
        import ast
        import textwrap
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        body = list(fn.body)
        if isinstance(body[0], ast.Expr):
            body = body[1:]
        lines = src.splitlines()[body[0].lineno - 1:body[-1].end_lineno]
        return textwrap.dedent("\n".join(l for l in lines if not l.lstrip().startswith("#")))

    def test_reads_snapshot_file_and_passes_it(self):
        seg = self._fn("_reconcile_park_pending")
        self.assertIn("broker_snapshot_", seg)
        self.assertIn("snapshot=_snap", seg)

    def test_expire_sends_telegram(self):
        seg = self._fn("_reconcile_park_pending")
        idx = seg.index("== 'expire'")
        tail = seg[idx:idx + 400]
        self.assertIn("send_telegram_message", tail)


class TestQueueAndReleaseGuard(unittest.TestCase):
    """v1.1.51：`pending_verifies` 佇列（11/25 買進那筆蓋掉賣出那筆）＋ `released_today`。"""

    def test_load_state_normalises_queue_and_legacy(self):
        from core.park_asset import load_state, save_state
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "park_position.json"
            # 舊版單一欄位（dict）要能讀成 1 筆佇列
            save_state({"symbol": "0050", "shares": 0, "cost": 0.0, "last_park_ts": 1.0,
                        "pending_verify": _pending("SELL", 6000, 90.3, avg=92.875)}, path)
            st = load_state(path)
            self.assertEqual(len(st["pending_verifies"]), 1)
            self.assertEqual(st["pending_verify"]["act"], "SELL")
            # 新版佇列（2 筆）要原樣保留
            save_state({"symbol": "0050", "shares": 0, "cost": 0.0, "last_park_ts": 1.0,
                        "pending_verifies": [_pending("SELL", 6000, 90.3, avg=92.875),
                                             _pending("BUY", 4000, 90.3)]}, path)
            self.assertEqual([x["act"] for x in load_state(path)["pending_verifies"]],
                             ["SELL", "BUY"])

    def test_released_today(self):
        from core.park_asset import released_today
        rows = [{"ts": "2026-11-25T13:25:40", "action": "SELL", "symbol": "0050"}]
        self.assertTrue(released_today(rows, "2026-11-25", "0050"))
        self.assertFalse(released_today(rows, "2026-11-26", "0050"))
        self.assertFalse(released_today([{"ts": "2026-11-25T13:25:40", "action": "REPAIR",
                                          "symbol": "0050"}], "2026-11-25", "0050"))

    def test_both_pending_entries_are_reconciled(self):
        """11/25：SELL 6,000 只成 1,000（＋5,000 加回）、BUY 4,000 全成（0 修正）⇒ 帳本總修正 +5,000。"""
        sell = reconcile_pending(_pending("SELL", 6000, 90.3, avg=92.875, day="2026-11-25"),
                                 [_tx("0050", "S", 1000, "90.30")], [], "2026-11-26")
        buy = reconcile_pending(_pending("BUY", 4000, 90.3, day="2026-11-25"),
                                [_tx("0050", "B", 4000, "90.30")], [], "2026-11-26")
        self.assertEqual((sell["shares_delta"], buy["shares_delta"]), (5000, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
