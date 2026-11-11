#!/usr/bin/env python
"""`core/broker_sync.py`（收盤「券商成交 vs 帳本」對帳）的回歸測試（2026-11-05）。

## 事故背景

2615 送 **2,000 股**整股賣單，券商只成交 **1,000 股**（`qty_s=2000`／`qty_sm=1000`），
但帳本記成「賣出 2,000 股」⇒ holdings 變 0。若那 1,000 股還在手上，
明天同檔出現買訊就會**重複建倉**。既有校正關卡只覆蓋「下單逾時的買單」，賣出部分成交沒有防護。

方向刻意不對稱（見模組 docstring）：
· 賣出少成交 ⇒ **預設自動補回持股**（保守方向）
· 買進少成交 ⇒ **預設只告警**（`BROKER_SYNC_TRIM=1` 才真的減）
· 券商回報裡完全沒有 ⇒ **不動帳**（「查不到」≠「沒發生」）
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.broker_sync import (apply_adjustments, book_trades_on, matched_by_symbol,  # noqa: E402
                             plan_adjustments, run_daily)


def _tx(sid, side, qty, mats=None):
    row = {"stk_no": sid, "buy_sell": side, "qty": str(qty)}
    if mats is not None:
        row["mat_dats"] = [{"qty": str(m)} for m in mats]
    return row


class TestMatchedBySymbol(unittest.TestCase):

    def test_single_row(self):
        self.assertEqual(matched_by_symbol([_tx("2615", "S", 1000)]), {("2615", "SELL"): 1000.0})

    def test_mat_dats_are_summed(self):
        got = matched_by_symbol([_tx("2615", "S", 9999, mats=[1000, 500])])
        self.assertEqual(got[("2615", "SELL")], 1500.0)

    def test_square_off_buy_maps_to_buy(self):
        self.assertEqual(matched_by_symbol([_tx("2603", "B", 909)]), {("2603", "BUY"): 909.0})

    def test_bad_rows_ignored(self):
        self.assertEqual(matched_by_symbol([None, {}, {"stk_no": "2615"}, {"buy_sell": "S"}]), {})
        self.assertEqual(matched_by_symbol(None), {})

    def test_multiple_orders_same_symbol_accumulate(self):
        got = matched_by_symbol([_tx("2615", "S", 1000), _tx("2615", "S", 1000)])
        self.assertEqual(got[("2615", "SELL")], 2000.0)


class TestBookTradesOn(unittest.TestCase):

    def _trades(self):
        return [
            {"timestamp": "2026-11-03T13:25:56", "symbol": "2615", "action": "BUY", "quantity": "2000"},
            {"timestamp": "2026-11-05T13:27:45", "symbol": "2615", "action": "SELL", "quantity": "2000"},
            {"timestamp": "2026-11-04T09:00:11", "symbol": "6505", "action": "SELL", "quantity": "2000"},
        ]

    def test_only_requested_date(self):
        got = book_trades_on(self._trades(), "2026-11-05")
        self.assertEqual(got, {("2615", "SELL"): 2000.0})

    def test_empty_date_returns_empty(self):
        self.assertEqual(book_trades_on(self._trades(), ""), {})


class TestPlanAdjustments(unittest.TestCase):

    def test_partial_sell_adds_holding_back(self):
        plan = plan_adjustments({("2615", "SELL"): 2000.0}, {("2615", "SELL"): 1000.0})
        self.assertEqual(len(plan), 1)
        p = plan[0]
        self.assertEqual(p["action"], "add_holding")
        self.assertTrue(p["apply"], "賣出少成交要預設自動修正")
        self.assertEqual(p["delta"], -1000.0)

    def test_full_fill_no_adjustment(self):
        self.assertEqual(plan_adjustments({("2615", "SELL"): 2000.0}, {("2615", "SELL"): 2000.0}), [])

    def test_partial_buy_alerts_by_default(self):
        plan = plan_adjustments({("2603", "BUY"): 1000.0}, {("2603", "BUY"): 600.0})
        self.assertEqual(plan[0]["action"], "trim_holding")
        self.assertFalse(plan[0]["apply"], "買進少成交預設只告警（避免減錯造成重複建倉）")

    def test_partial_buy_trims_when_enabled(self):
        plan = plan_adjustments({("2603", "BUY"): 1000.0}, {("2603", "BUY"): 600.0}, apply_trim=True)
        self.assertTrue(plan[0]["apply"])

    def test_env_switch(self):
        old = os.environ.get("BROKER_SYNC_TRIM")
        try:
            os.environ["BROKER_SYNC_TRIM"] = "1"
            plan = plan_adjustments({("2603", "BUY"): 1000.0}, {("2603", "BUY"): 600.0})
            self.assertTrue(plan[0]["apply"])
        finally:
            if old is None:
                os.environ.pop("BROKER_SYNC_TRIM", None)
            else:
                os.environ["BROKER_SYNC_TRIM"] = old

    def test_missing_in_broker_is_unknown_and_not_applied(self):
        plan = plan_adjustments({("2408", "BUY"): 608.0}, {})
        self.assertEqual(plan[0]["action"], "unknown")
        self.assertFalse(plan[0]["apply"])


class TestApplyAdjustments(unittest.TestCase):

    def test_add_holding_back(self):
        plan = [{"sid": "2615", "action": "add_holding", "delta": -1000.0, "apply": True}]
        self.assertEqual(apply_adjustments({"2615": 0}, plan)["2615"], 1000)

    def test_trim_holding(self):
        plan = [{"sid": "2603", "action": "trim_holding", "delta": -400.0, "apply": True}]
        self.assertEqual(apply_adjustments({"2603": 909}, plan)["2603"], 509)

    def test_not_applied_is_ignored(self):
        plan = [{"sid": "2603", "action": "trim_holding", "delta": -400.0, "apply": False}]
        self.assertEqual(apply_adjustments({"2603": 909}, plan)["2603"], 909)

    def test_never_negative_and_input_not_mutated(self):
        src = {"2615": 100}
        out = apply_adjustments(src, [{"sid": "2615", "action": "trim_holding", "delta": -999, "apply": True}])
        self.assertEqual(out["2615"], 0)
        self.assertEqual(src["2615"], 100, "不可就地改動傳入的 holdings")


class _FakeBroker:
    def __init__(self, tx):
        self._tx = tx

    def query_transactions(self, start, end):
        if isinstance(self._tx, Exception):
            raise self._tx
        return self._tx


class TestRunDaily(unittest.TestCase):

    def _env(self, d, holdings):
        perf = Path(d) / "performance.csv"
        perf.write_text(
            "timestamp,symbol,signal,price,quantity,action,exclude_daily,cost\n"
            "2026-11-05T13:27:45.279429,2615,-1,114.0,2000,SELL,0,1009.0\n", encoding="utf-8")
        hold = Path(d) / "holdings.json"
        hold.write_text(json.dumps(holdings), encoding="utf-8")
        return perf, hold, Path(d) / "audit.jsonl"

    def test_partial_sell_is_written_back(self):
        with tempfile.TemporaryDirectory() as d:
            perf, hold, audit = self._env(d, {"2615": 0, "2603": 909})
            rep = run_daily(_FakeBroker([_tx("2615", "S", 1000)]), "2026-11-05",
                            perf_path=perf, holdings_path=hold, audit_path=audit)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["changed"]["2615"], (0, 1000))
            saved = json.loads(hold.read_text(encoding="utf-8"))
            self.assertEqual(saved["2615"], 1000)
            self.assertEqual(saved["2603"], 909, "未調整的檔位必須原樣保留")
            self.assertTrue(audit.exists(), "必須留稽核紀錄")

    def test_full_fill_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            perf, hold, audit = self._env(d, {"2615": 0})
            rep = run_daily(_FakeBroker([_tx("2615", "S", 2000)]), "2026-11-05",
                            perf_path=perf, holdings_path=hold, audit_path=audit)
            self.assertEqual(rep["changed"], {})
            self.assertEqual(json.loads(hold.read_text(encoding="utf-8"))["2615"], 0)

    def test_broker_error_does_not_touch_books(self):
        with tempfile.TemporaryDirectory() as d:
            perf, hold, audit = self._env(d, {"2615": 0})
            rep = run_daily(_FakeBroker(RuntimeError("api down")), "2026-11-05",
                            perf_path=perf, holdings_path=hold, audit_path=audit)
            self.assertFalse(rep["ok"])
            self.assertIn("broker", rep["errors"])
            self.assertEqual(json.loads(hold.read_text(encoding="utf-8"))["2615"], 0)

    def test_no_trades_today_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            perf = Path(d) / "performance.csv"
            perf.write_text("timestamp,symbol,signal,price,quantity,action,exclude_daily,cost\n", encoding="utf-8")
            hold = Path(d) / "holdings.json"
            hold.write_text("{}", encoding="utf-8")
            rep = run_daily(_FakeBroker([]), "2026-11-05", perf_path=perf, holdings_path=hold,
                            audit_path=Path(d) / "a.jsonl")
            self.assertTrue(rep["ok"])
            self.assertIn("沒有成交", rep["summary"])


class TestTraderIntegration(unittest.TestCase):

    def test_trader_runs_booksync_once_per_day(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("from core.broker_sync import run_daily", src)
        self.assertIn("_booksync_tried", src)
        self.assertLess(src.index("from core.broker_sync import run_daily"),
                        src.index("_bs_run(broker"), "匯入要在呼叫之前")

    def test_booksync_never_places_orders(self):
        src = (_ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
        for bad in ("place_order", "cancel_order"):
            self.assertNotIn(bad, src, f"對帳模組不得呼叫 {bad}（只修帳、不下單）")


if __name__ == "__main__":
    unittest.main()
