#!/usr/bin/env python
"""回歸測試：自選股賣出「成交未確認」的待對帳（2026-11-25，v1.1.53）。

停泊那條線（`park_asset.pending_verifies`）已證明有用；這版把同一套推到**策略賣出／硬停損**：
賣單送出後 `resolve_fill()` 回 `None` ⇒ 先照送單股數記帳（否則會重複下單），
但寫進 `logs/stock_pending.json` 佇列；下次窗口用券商 `qty_sm`（當天即時）或快照 `transactions`
把「沒賣掉的股數與成本」加回 `holdings` 與分帳本；未確認的金額同時從 `fit_cash()` 扣掉。
"""
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import stock_pending as sp  # noqa: E402
from core.park_asset import reconcile_pending  # noqa: E402


def _pending(sym="2603", shares=909, price=236.0, avg=276.0, day="2026-11-20"):
    return {"act": "SELL", "symbol": sym, "shares": shares, "price": price,
            "avg": avg, "date": day, "ts": day + "T13:25:31"}


class TestQueue(unittest.TestCase):

    def test_record_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sp.json"
            sp.record(_pending(), path)
            sp.record(_pending(sym="2609", shares=4000, price=53.0), path)
            rows = sp.load(path)
            self.assertEqual([r["symbol"] for r in rows], ["2603", "2609"])

    def test_load_tolerates_missing_and_garbage(self):
        self.assertEqual(sp.load("/nonexistent/xx.json"), [])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sp.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(sp.load(path), [])

    def test_unverified_sell_value_only_sells(self):
        rows = [_pending(shares=1000, price=100.0),
                {"act": "BUY", "symbol": "2408", "shares": 600, "price": 400.0}]
        self.assertAlmostEqual(sp.unverified_sell_value(rows), 100_000.0, places=2)
        self.assertEqual(sp.unverified_sell_value([]), 0.0)


class TestApplyDeltas(unittest.TestCase):

    def test_unsold_shares_go_back_to_holdings_and_ledger(self):
        holdings, alloc = {"2603": 0}, {"2603": {"total_buy_cost": 0.0, "total_buy_shares": 0}}
        sp.apply_deltas(_pending(shares=909, price=236.0, avg=276.0), 500, 500 * 276.0,
                        holdings, alloc)
        self.assertEqual(holdings["2603"], 500)
        self.assertEqual(alloc["2603"]["total_buy_shares"], 500)
        self.assertAlmostEqual(alloc["2603"]["total_buy_cost"], 500 * 276.0, places=2)

    def test_missing_ledger_entry_is_safe(self):
        holdings, alloc = {}, {}
        sp.apply_deltas({"symbol": "0050"}, 100, 9000.0, holdings, alloc)
        self.assertEqual(holdings["0050"], 100)


class TestReconcileWithRealCase(unittest.TestCase):
    """用真實案例：11/20 2603 送 909 股，券商快照 `S 909` ⇒ 全成（0 修正）。"""

    def test_full_fill_no_change(self):
        tx = [{"stk_no": "2603", "buy_sell": "S", "qty": "909", "price_avg": "236.00"}]
        res = reconcile_pending(_pending(), tx, [], "2026-11-21")
        self.assertEqual((res["status"], res["shares_delta"]), ("ok", 0))

    def test_partial_fill_adds_back(self):
        tx = [{"stk_no": "2603", "buy_sell": "S", "qty": "500", "price_avg": "236.00"}]
        res = reconcile_pending(_pending(), tx, [], "2026-11-21")
        self.assertEqual((res["status"], res["shares_delta"]), ("ok", 409))
        self.assertAlmostEqual(res["cost_delta"], 409 * 276.0, places=2)

    def test_same_day_uses_live_inventory(self):
        inv = [{"stk_no": "2603", "qty_bm": "0", "qty_sm": "500"}]
        res = reconcile_pending(_pending(), [], inv, "2026-11-20")
        self.assertEqual(res["shares_delta"], 409)


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

    def test_unknown_sell_is_recorded(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("stock_pending as _sp", src)
        self.assertIn("_sp.record(", src)
        self.assertIn("(action == 'SELL') and (_filled is None)", src)

    def test_fit_cash_deducts_stock_pending(self):
        seg = self._fn("fit_cash")
        self.assertIn("stock_pending", seg)
        self.assertIn("unverified_sell_value", seg)

    def test_reconcile_called_before_strategy_loop(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("_reconcile_stock_pending()", src)
        i_call = src.index("_reconcile_stock_pending()")
        i_loop = src.index("for (symbol, cfg) in PORTFOLIO_CONFIG.items():", i_call)
        self.assertLess(i_call, i_loop)


if __name__ == "__main__":
    unittest.main(verbosity=2)
