#!/usr/bin/env python3
"""`scripts/void_untracked_buys.py` 的回歸測試（A 案：把幽靈買進列作廢）。

真實案例（2026-09-17）：2395/3665 各有 3 筆 12 股買進只寫進 `performance.csv`，
沒進 `holdings.json`／分帳本 ⇒ CSV 的 FIFO 未平倉多 36+36 股 =
儀表板「未平倉部位」看不到、總資產三口徑對不上、且這種部位永遠不會被自動賣出。
"""
import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import void_untracked_buys as V  # noqa: E402

HDR = ["timestamp", "symbol", "signal", "price", "quantity", "action", "exclude_daily", "cost"]

# 2395 的真實歷史（作廢前）：12/12/12 是幽靈列，273 與 121 是正常列
REAL_2395 = [
    ("2026-07-29T09:00:44", "2395", "1", "551.0", "12", "BUY", "0", "0"),
    ("2026-07-30T11:45:58", "2395", "1", "541.0", "12", "BUY", "0", "0"),
    ("2026-07-30T11:48:10", "2395", "1", "542.0", "12", "BUY", "0", "0"),
    ("2026-07-30T12:39:17", "2395", "1", "548.0", "273", "BUY", "1", "0"),
    ("2026-08-03T09:00:05", "2395", "-1", "561.0", "273", "SELL", "1", "0"),
    ("2026-08-06T12:06:50", "2395", "1", "619.0", "121", "BUY", "0", "0"),
    ("2026-09-01T09:00:05", "2395", "-1", "692.0", "121", "SELL", "0", "0"),
]


class VoidFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.perf = os.path.join(d, "performance.csv")
        self.holdings = os.path.join(d, "holdings.json")
        self.void_log = os.path.join(d, "voided_trades.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows, holdings=None):
        with open(self.perf, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(HDR)
            w.writerows(rows)
        with open(self.holdings, "w", encoding="utf-8") as f:
            json.dump(holdings or {}, f)
        return self.perf

    def run_main(self, *extra):
        argv = ["void", "--perf", self.perf, "--holdings", self.holdings,
                "--void-log", self.void_log] + list(extra)
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            return V.main()

    def body(self):
        with open(self.perf, newline="", encoding="utf-8") as f:
            return [r for r in csv.reader(f) if r][1:]


class TestSelectVoids(VoidFixture):
    def test_selects_oldest_buys_until_excess_covered(self):
        rows = [list(r) for r in REAL_2395]
        picks, excess, picked = V.select_voids(rows, {})   # holdings 0 → 未平倉 36 股全是幽靈
        self.assertEqual(len(picks), 3)
        self.assertEqual([r[4] for _, r in picks], ["12", "12", "12"])
        self.assertEqual(excess, {"2395": 36})
        self.assertEqual(picked, {"2395": 36})

    def test_partial_holdings_reduce_the_excess(self):
        rows = [list(r) for r in REAL_2395]
        picks, excess, _ = V.select_voids(rows, {"2395": 30})   # 只多 6 股
        self.assertEqual(excess, {"2395": 6})
        self.assertEqual(len(picks), 1)                          # 最舊的一列（12 股）即可覆蓋
        self.assertEqual(picks[0][1][4], "12")

    def test_fully_held_symbol_is_not_touched(self):
        rows = [list(r) for r in REAL_2395]
        picks, excess, _ = V.select_voids(rows, {"2395": 36})
        self.assertEqual(picks, [])
        self.assertEqual(excess, {})

    def test_closed_symbol_is_not_touched(self):
        rows = [list(r) for r in REAL_2395[:2]]      # 只有兩筆買進、沒有賣出 → 未平倉 24
        _, excess, _ = V.select_voids(rows, {"2395": 24})
        self.assertEqual(excess, {})

    def test_fifo_open_shares_handles_multiple_sells(self):
        rows = [["t", "2330", "1", "100", "10", "BUY"], ["t", "2330", "-1", "110", "4", "SELL"],
                ["t", "2330", "-1", "120", "3", "SELL"]]
        self.assertEqual(V.fifo_open_shares(rows), {"2330": 3})


class TestMain(VoidFixture):
    def test_dry_run_does_not_write(self):
        before = open(self.write(REAL_2395), encoding="utf-8").read()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(open(self.perf, encoding="utf-8").read(), before)

    def test_nothing_to_do_when_books_agree(self):
        self.write(REAL_2395, {"2395": 36})
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.body()), len(REAL_2395))

    def test_apply_removes_only_the_phantom_rows(self):
        self.write(REAL_2395)
        self.assertEqual(self.run_main("--apply"), 0)
        kept = self.body()
        # 7 列 → 4 列（作廢 3 筆 12 股）；273/121 的買賣完全保留
        self.assertEqual(len(kept), 4)
        self.assertEqual([r[4] for r in kept], ["273", "273", "121", "121"])
        self.assertEqual(V.fifo_open_shares(kept), {})        # 幽靈歸零
        baks = [n for n in os.listdir(self.tmp.name) if ".bak_void_" in n]
        self.assertEqual(len(baks), 1, "必須先備份")

    def test_apply_writes_audit_trail(self):
        self.write(REAL_2395)
        self.run_main("--apply")
        with open(self.void_log, encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs[0]["symbol"], "2395")
        self.assertEqual(recs[0]["quantity"], "12")
        self.assertIn("未進 holdings", recs[0]["reason"])
        self.assertEqual(recs[0]["amount"], 551.0 * 12)

    def test_apply_aborts_if_file_changed(self):
        self.write(REAL_2395)
        real = V.select_voids

        def sneaky(rows, holdings):
            out = real(rows, holdings)
            with open(self.perf, "a", encoding="utf-8") as f:
                f.write("2026-09-14T09:00:00,2330,1,100.0,1,BUY,0,0\n")
            return out

        V.select_voids = sneaky
        try:
            self.assertEqual(self.run_main("--apply"), 1)
        finally:
            V.select_voids = real
        self.assertIn("2330", open(self.perf, encoding="utf-8").read(), "新增成交不可遺失")

    def test_missing_holdings_exits_nonzero(self):
        with open(self.perf, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HDR)
        self.assertEqual(self.run_main(), 1)

    def test_no_leftover_tmp_files(self):
        self.write(REAL_2395)
        self.run_main("--apply")
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.startswith(".tmp_")], [])

    def test_apply_preserves_file_mode(self):
        self.write(REAL_2395)
        os.chmod(self.perf, 0o644)
        self.run_main("--apply")
        self.assertEqual(os.stat(self.perf).st_mode & 0o777, 0o644)


class TestEndToEndReconciliation(VoidFixture):
    """作廢後三本帳必須一致（用真實模組驗，不是只看工具自己說成功）。"""

    def test_cash_increases_by_the_voided_amount(self):
        from core import drawdown_guard as rh
        self.write(REAL_2395, {"2395": 0})
        before = rh.net_cash_flow(self.perf)
        self.run_main("--apply")
        after = rh.net_cash_flow(self.perf)
        # 作廢 3 筆共 19,608 元 → 淨現金流回升（再加上那三筆的手續費 60 元）
        self.assertGreater(after, before)
        self.assertAlmostEqual(after - before, 12 * (551 + 541 + 542), delta=200)

    def test_audit_has_no_phantom_after_apply(self):
        from core import books
        self.write(REAL_2395, {"2395": 0})
        self.run_main("--apply")
        r = books.audit_books(self.perf, holdings={}, holdings_path=self.holdings,
                              alloc={})
        self.assertEqual(r["phantom"], {})
        self.assertEqual(r["ghost"], {})


if __name__ == "__main__":
    unittest.main()
