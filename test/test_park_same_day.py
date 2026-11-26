#!/usr/bin/env python
"""回歸測試：停泊「當日即時對帳」與現金保護（2026-11-25，v1.1.52）。

## 事故

11/25 13:25 C 釋出 6,000 股 0050 @ 90.30，券商**實際只成 1,000 股**（`qty_sm=1000`），
帳本卻照送單股數記「全額賣出」⇒ `cash_available()` 把 541,800 的回款算成可用現金
（實際只進 90,081）⇒ 若同一天有股票買訊，真錢上就是**交割款不足（違約）**。

## 三件事

1. `unverified_sell_value()`：把「成交未確認的賣出金額」從可用現金扣掉（`cash_available(unverified_proceeds=…)`）。
2. 當日即時對帳：pending 是**當天**的 ⇒ 用券商**即時庫存**（`qty_bm`／`qty_sm`）先修正，不必等 13:45 快照。
3. 當天已釋出過 ⇒ C 不再重送（部分成交後每 60 秒重送會洗版）。
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.park_asset import cash_available, reconcile_pending, unverified_sell_value  # noqa: E402


def _pending(act, shares, price, avg=0.0, day="2026-11-25"):
    return {"act": act, "symbol": "0050", "shares": shares, "price": price,
            "avg": avg, "date": day, "ts": day + "T13:25:40"}


def _inv(sym, qty_bm, qty_sm):
    return {"stk_no": sym, "qty_bm": str(qty_bm), "qty_sm": str(qty_sm)}


class TestUnverifiedCash(unittest.TestCase):

    def test_sell_pending_reduces_available_cash(self):
        st = {"pending_verifies": [_pending("SELL", 6000, 90.3, avg=92.875)]}
        up = unverified_sell_value(st)
        self.assertAlmostEqual(up, 6000 * 90.3, places=2)
        self.assertAlmostEqual(cash_available(1_000_000, 553_916, 0.0, unverified_proceeds=up),
                               0.0, places=2)

    def test_buy_pending_does_not_reduce_cash(self):
        st = {"pending_verifies": [_pending("BUY", 4000, 90.3)]}
        self.assertEqual(unverified_sell_value(st), 0.0)
        self.assertAlmostEqual(cash_available(1_000_000, 553_916, 0.0,
                                              unverified_proceeds=0.0), 446_084.0, places=2)

    def test_legacy_single_slot_is_honoured(self):
        st = {"pending_verify": _pending("SELL", 6000, 90.3, avg=92.875)}
        self.assertAlmostEqual(unverified_sell_value(st), 6000 * 90.3, places=2)

    def test_empty_state(self):
        self.assertEqual(unverified_sell_value({}), 0.0)
        self.assertEqual(unverified_sell_value(None), 0.0)


class TestSameDayReconcile(unittest.TestCase):
    """當天 pending + 即時庫存 ⇒ 立刻修正（不必等隔天快照）。"""

    def test_live_inventory_fixes_partial_sell(self):
        # 11/25 實例：送 6,000、qty_sm=1000 ⇒ 加回 5,000 股與成本
        res = reconcile_pending(_pending("SELL", 6000, 90.3, avg=92.875),
                                [], [_inv("0050", 0, 1000)], "2026-11-25")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["shares_delta"], 5000)
        self.assertAlmostEqual(res["cost_delta"], 5000 * 92.875, places=2)

    def test_live_inventory_confirms_full_fill(self):
        res = reconcile_pending(_pending("BUY", 4000, 90.3), [], [_inv("0050", 4000, 0)], "2026-11-25")
        self.assertEqual((res["status"], res["shares_delta"]), ("ok", 0))

    def test_live_inventory_missing_symbol_keeps_waiting(self):
        res = reconcile_pending(_pending("SELL", 1000, 90.3, avg=90.0), [], [], "2026-11-25")
        self.assertEqual(res["status"], "keep")


class TestTraderWiring(unittest.TestCase):

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

    def test_fit_cash_excludes_unverified_proceeds(self):
        seg = self._fn("fit_cash")
        self.assertIn("unverified_sell_value", seg)
        self.assertIn("unverified_proceeds=", seg)

    def test_parking_cash_excludes_unverified_proceeds(self):
        seg = self._fn("park_idle_if_due")
        self.assertIn("unverified_proceeds", seg)

    def test_same_day_live_inventory_path(self):
        seg = self._fn("_reconcile_park_pending")
        self.assertIn("_live_park_inv_rows()", seg)
        self.assertIn("_day == _today", seg)

    def test_c_gate_skips_when_already_released_today(self):
        seg = self._fn("park_idle_if_due")
        idx = seg.index("依 C 釋出停泊部位")
        head = seg[:idx]
        self.assertIn("not _park_released_today(sym)", head)


if __name__ == "__main__":
    unittest.main(verbosity=2)
