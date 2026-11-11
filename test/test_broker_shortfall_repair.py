#!/usr/bin/env python
"""部分成交補帳：`scripts/broker_shortfall_repair.py` ＋ `core.broker_sync` 的純函式（2026-11-05）。

## 事故背景

2026-11-05：2615 送出 2,000 股賣單、券商只成交 1,000 股，帳本記成「賣 2,000、2615 = 0 股」。
隔天 `broker_sync` 比的是「當日成交」，而模擬環境查不到歷史 ⇒ **只能靠當天落地的快照補**。

這裡釘住：預設 dry-run 不寫檔、賣出少成交才自動修、買進少成交要 `--allow-trim`、
修完三本帳一致（CSV／holdings／allocation 都用 FIFO 重算）、可重複執行（idempotent）、有備份。
"""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.broker_sync import partial_fill_plan, rewrite_csv_text  # noqa: E402
from scripts.broker_shortfall_repair import main  # noqa: E402

HEAD = "timestamp,symbol,signal,price,quantity,action,exclude_daily,cost\n"
BUY = "2026-11-03T13:25:00.000000,2615,1,117.50,2000,BUY,0,333\n"
SELL = "2026-11-05T13:27:44.000000,2615,-1,114.00,2000,SELL,0,1162\n"

#: 券商當天真的只有成交 1,000 股（fee 162 + tax 342）
TX = [{"buy_sell": "S", "stk_no": "2615", "stk_na": "萬海", "qty": "1000", "price_avg": "114.00",
       "mat_dats": [{"qty": "1000", "fee": "162", "tax": "342"}]}]


class _Tmp:
    def __init__(self, csv_text=HEAD + BUY + SELL, holdings=None, alloc=None, tx=None, date="2026-11-05"):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.perf, self.hold, self.alloc, self.snap = d / "performance.csv", d / "holdings.json", d / "stock_allocation.json", d / "snap.json"
        self.perf.write_text(csv_text, encoding="utf-8")
        self.hold.write_text(json.dumps(holdings if holdings is not None else {"2615": 0}), encoding="utf-8")
        self.alloc.write_text(json.dumps(alloc if alloc is not None else
                                         {"2615": {"total_buy_cost": 0, "total_buy_shares": 0}}), encoding="utf-8")
        self.snap.write_text(json.dumps({"date": date, "transactions": tx if tx is not None else TX}),
                             encoding="utf-8")

    def run(self, *extra):
        return main(["--snapshot", str(self.snap), "--perf", str(self.perf),
                     "--holdings", str(self.hold), "--alloc", str(self.alloc), *extra])

    def rows(self):
        return list(csv.DictReader(io.StringIO(self.perf.read_text(encoding="utf-8"))))

    def cleanup(self):
        self.dir.cleanup()


class TestRewriteCsvText(unittest.TestCase):
    def test_single_row_reduces_qty_and_fixes_cost(self):
        text, changed, note = rewrite_csv_text(HEAD + BUY + SELL, "2026-11-05", "2615", "SELL",
                                              1000, cost=504)
        rows = list(csv.DictReader(io.StringIO(text)))
        sell = [r for r in rows if r["action"] == "SELL"][0]
        self.assertEqual(sell["quantity"], "1000")
        self.assertEqual(float(sell["cost"]), 504.0, "費用要校正成券商實收（fee 162 + tax 342）")
        self.assertEqual(len(changed), 1)
        self.assertIn("2000 股 → 券商 1000 股", note)

    def test_no_hit_returns_original(self):
        text = HEAD + BUY
        out, changed, note = rewrite_csv_text(text, "2026-11-05", "2615", "SELL", 1000)
        self.assertEqual(changed, [])
        self.assertEqual(out, text)
        self.assertIn("沒有帳本成交列", note)

    def test_earliest_fill_kept_when_split(self):
        """同一天分兩列成交時，**保留最早的成交**、後面的列砍到 0 就刪列。"""
        text = HEAD + BUY + SELL + "2026-11-05T13:29:00.000000,2615,-1,115.00,500,SELL,0,200\n"
        out, changed, _n = rewrite_csv_text(text, "2026-11-05", "2615", "SELL", 1200)
        rows = list(csv.DictReader(io.StringIO(out)))
        qty = [int(r["quantity"]) for r in rows if r["action"] == "SELL"]
        self.assertEqual(qty, [1200], "只留最早那列，且降到券商成交股數；後面的列到 0 就刪除")

    def test_never_increases_qty(self):
        """帳本比券商少時只警告、不放大（避免無中生有）。"""
        out, changed, note = rewrite_csv_text(HEAD + BUY + SELL, "2026-11-05", "2615", "SELL", 5000)
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(int([r for r in rows if r["action"] == "SELL"][0]["quantity"]), 2000)
        self.assertIn("只減不增", note)


class TestPartialFillPlan(unittest.TestCase):
    def test_sell_shortfall_is_applied(self):
        trades = list(csv.DictReader(io.StringIO(HEAD + BUY + SELL)))
        res = partial_fill_plan(trades, TX, "2026-11-05")
        todo = [p for p in res["plan"] if p["apply"]]
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["action"], "add_holding")
        self.assertEqual(todo[0]["broker"], 1000)
        self.assertAlmostEqual(todo[0]["broker_cost"], 504.0)

    def test_buy_shortfall_needs_allow_trim(self):
        tx_buy = [{"buy_sell": "B", "stk_no": "2615", "qty": "1000", "price_avg": "117.50",
                   "mat_dats": [{"qty": "1000", "fee": "166"}]}]
        trades = list(csv.DictReader(io.StringIO(HEAD + BUY)))
        res = partial_fill_plan(trades, tx_buy, "2026-11-03")
        self.assertEqual([p for p in res["plan"] if p["apply"]], [], "買進少成交預設不減帳")
        self.assertEqual(len(res["blocked"]), 1)
        res2 = partial_fill_plan(trades, tx_buy, "2026-11-03", allow_trim=True)
        self.assertEqual(len([p for p in res2["plan"] if p["apply"]]), 1)


class TestScript(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        t = _Tmp()
        try:
            before = t.perf.read_text(encoding="utf-8")
            rc = t.run()
            self.assertEqual(rc, 0)
            self.assertEqual(t.perf.read_text(encoding="utf-8"), before)
            self.assertEqual(json.loads(t.hold.read_text())["2615"], 0)
        finally:
            t.cleanup()

    def test_apply_fixes_three_books(self):
        t = _Tmp()
        try:
            rc = t.run("--apply")
            self.assertEqual(rc, 0)
            rows = [r for r in t.rows() if r["action"] == "SELL"]
            self.assertEqual(int(rows[0]["quantity"]), 1000)
            self.assertEqual(float(rows[0]["cost"]), 504.0)
            # 剩 1,000 股回到帳本（FIFO 成本含買進手續費）
            hold = json.loads(t.hold.read_text())
            self.assertEqual(hold["2615"], 1000)
            alloc = json.loads(t.alloc.read_text())["2615"]
            self.assertEqual(alloc["total_buy_shares"], 1000)
            self.assertAlmostEqual(alloc["total_buy_cost"], (117.5 * 2000 + 333) / 2, places=1)
            # 有備份
            self.assertTrue(list(Path(t.dir.name).glob("performance.csv.bak_shortfall_*")))
            self.assertTrue(list(Path(t.dir.name).glob("holdings.json.bak_shortfall_*")))
        finally:
            t.cleanup()

    def test_idempotent(self):
        t = _Tmp()
        try:
            self.assertEqual(t.run("--apply"), 0)
            after = t.perf.read_text(encoding="utf-8")
            self.assertEqual(t.run("--apply"), 0)
            self.assertEqual(t.perf.read_text(encoding="utf-8"), after)
        finally:
            t.cleanup()

    def test_buy_shortfall_blocked_without_allow_trim(self):
        t = _Tmp(csv_text=HEAD + BUY, holdings={"2615": 2000}, date="2026-11-03", tx=[
            {"buy_sell": "B", "stk_no": "2615", "qty": "1000", "price_avg": "117.50",
             "mat_dats": [{"qty": "1000", "fee": "166"}]}])
        try:
            self.assertEqual(t.run(), 3)
            self.assertEqual(json.loads(t.hold.read_text())["2615"], 2000, "沒 --allow-trim 不可減帳")
            self.assertEqual(t.run("--allow-trim", "--apply"), 0)
            self.assertEqual(json.loads(t.hold.read_text())["2615"], 1000)
        finally:
            t.cleanup()

    def test_unknown_symbol_untouched(self):
        """券商回報裡沒有這個代號 ⇒ 不動帳（查不到 ≠ 沒發生）。"""
        t = _Tmp(tx=[{"buy_sell": "S", "stk_no": "9999", "qty": "500", "mat_dats": []}])
        try:
            self.assertEqual(t.run("--apply"), 0)
            rows = [r for r in t.rows() if r["action"] == "SELL"]
            self.assertEqual(int(rows[0]["quantity"]), 2000)
        finally:
            t.cleanup()

    def test_missing_snapshot_returns_1(self):
        self.assertEqual(main(["--snapshot", "/nonexistent.json"]), 1)


if __name__ == "__main__":
    unittest.main()
