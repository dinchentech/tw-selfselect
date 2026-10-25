#!/usr/bin/env python
"""`scripts/reconcile_total_assets.py` 的回歸測試。

背景：2026-09-13 查出 VM 總資產三口径不一致（差 92,484），元凶是只寫進
`performance.csv`、沒進 `holdings.json`/分帳本的「幽靈部位」。
本測試鎖住對帳腳本的核心：FIFO 未平倉推算、幽靈部位偵測、離開碼。
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
import reconcile_total_assets as R  # noqa: E402
from core import books  # noqa: E402

HDR = ["timestamp", "symbol", "signal", "price", "quantity", "action",
       "exclude_daily", "cost"]


def write_csv(path, rows):
    """FIFO 單元測試的 fixture 一律補 `cost=0`：測的是配對邏輯，不是費用
    （費用版 FIFO 由 test_fees.py 專測）。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for r in rows:
            r = list(r)
            while len(r) < len(HDR):
                r.append("0")
            w.writerow(r)
    return path


class TestFifoOpenLots(unittest.TestCase):
    def test_full_round_trip_leaves_nothing(self):
        lots, realized, unmatched = books.fifo_open_positions([
            {"symbol": "2330", "price": "100", "quantity": "10", "action": "BUY", "cost": "0"},
            {"symbol": "2330", "price": "120", "quantity": "10", "action": "SELL", "cost": "0"},
        ])
        self.assertEqual(lots, {})
        self.assertAlmostEqual(realized, 200.0)
        self.assertEqual(unmatched, {})

    def test_partial_sell_leaves_remainder_with_original_cost(self):
        lots, _, _ = books.fifo_open_positions([
            {"symbol": "2330", "price": "100", "quantity": "10", "action": "BUY", "cost": "0"},
            {"symbol": "2330", "price": "120", "quantity": "4", "action": "SELL", "cost": "0"},
        ])
        self.assertEqual(lots["2330"], (6, 600.0))

    def test_fifo_consumes_oldest_lot_first(self):
        # 12 股 @500 先買、再買 100 股 @600，賣 50 股 → 吃掉 12 股舊的 + 38 股新的
        lots, realized, _ = books.fifo_open_positions([
            {"symbol": "2395", "price": "500", "quantity": "12", "action": "BUY", "cost": "0"},
            {"symbol": "2395", "price": "600", "quantity": "100", "action": "BUY", "cost": "0"},
            {"symbol": "2395", "price": "700", "quantity": "50", "action": "SELL", "cost": "0"},
        ])
        self.assertEqual(lots["2395"][0], 62)
        self.assertAlmostEqual(realized, 12 * 200 + 38 * 100)

    def test_sell_without_matching_buy_is_reported(self):
        lots, _, unmatched = books.fifo_open_positions([
            {"symbol": "2330", "price": "100", "quantity": "5", "action": "SELL", "cost": "0"},
        ])
        self.assertEqual(lots, {})
        self.assertEqual(unmatched, {"2330": 5})

    def test_lowercase_action_is_tolerated(self):
        lots, _, _ = books.fifo_open_positions([
            {"symbol": "2330", "price": "100", "quantity": "3", "action": "buy", "cost": "0"},
        ])
        self.assertEqual(lots["2330"], (3, 300.0))


class TestReconcileEndToEnd(unittest.TestCase):
    """模擬 VM 實況：幽靈買進 → A 低估、B 為真值。"""

    @staticmethod
    def _write_json(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.perf = write_csv(os.path.join(d, "performance.csv"), [
            ("2026-07-29T09:00:00", "2395", "1", "500.0", "12", "BUY"),    # 幽靈：沒進 holdings
            ("2026-07-30T12:00:00", "2395", "1", "500.0", "100", "BUY"),
            ("2026-08-03T09:00:00", "2395", "-1", "600.0", "100", "SELL"),
        ])
        self.holdings = self._write_json(os.path.join(d, "holdings.json"), {})
        self.alloc = self._write_json(
            os.path.join(d, "alloc.json"),
            {"2395": {"total_buy_cost": 0, "total_buy_shares": 0}})

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, prices="2395=600", json_out=False, extra=None):
        """跑 main()；非 json 模式時把 stdout 靜音，避免污染測試輸出。"""
        argv = ["reconcile", "--perf", self.perf, "--holdings", self.holdings,
                "--alloc", self.alloc, "--total-capital", "1000000",
                "--prices", prices] + (["--json"] if json_out else []) + (extra or [])
        buf = []
        with mock.patch.object(sys, "argv", argv):
            if json_out:
                def _cap(*a, **k):
                    if k.get("file") in (None, sys.stdout):  # 只收 stdout（stderr 的警告不算）
                        buf.append(a[0])
                with mock.patch("builtins.print", _cap):
                    rc = R.main()
                return rc, json.loads(buf[-1])
            with mock.patch("builtins.print"):
                return R.main()

    def test_phantom_position_detected_and_exit_code_1(self):
        self.assertEqual(self._run(), 1)

    def test_phantom_makes_cash_flow_view_understate(self):
        # 買 12@500(幽靈) + 100@500，賣 100@600：
        #   net_cash_flow = 60,000 − 56,000 = +4,000 → cash = 1,004,000
        #   FIFO 吃掉 12 股舊的(賺 1,200) + 88 股新的(賺 8,800) → 已實現 10,000，未平倉 12 股@500
        #   A = cash + M(holdings={}) = 1,004,000              ← 漏掉幽靈持股
        #   B = TC + 已實現 + (0 − 0) = 1,010,000
        #   C = cash + M(CSV 12 股 @600 = 7,200) = 1,011,200
        rc, out = self._run(json_out=True)
        self.assertEqual(rc, 1)
        self.assertEqual(out["phantom_positions"]["2395"]["shares"], 12)
        self.assertAlmostEqual(out["phantom_positions"]["2395"]["cost"], 6_000)
        self.assertAlmostEqual(out["phantom_positions"]["2395"]["market_value"], 7_200)
        self.assertAlmostEqual(out["A_cash_flow"], 1_004_000)
        self.assertAlmostEqual(out["B_dashboard"], 1_010_000)
        self.assertAlmostEqual(out["C_csv_consistent"], 1_011_200)
        # A 低估 = 幽靈部位成本（B − A）；C − B = 幽靈未實現
        self.assertAlmostEqual(out["B_minus_A"], 6_000)
        self.assertAlmostEqual(out["C_minus_B"], 1_200)
        self.assertFalse(out["consistent"])

    def test_clean_books_exit_code_0(self):
        # 用 write_csv helper（會補齊 8 欄）：手寫 6 欄會觸發 schema 檢查 → 判為不一致
        perf = write_csv(os.path.join(self.tmp.name, "clean.csv"), [
            ("2026-07-30T12:00:00", "2395", "1", "500.0", "100", "BUY"),
        ])
        with open(self.holdings, "w", encoding="utf-8") as f:
            json.dump({"2395": 100}, f)
        with open(self.alloc, "w", encoding="utf-8") as f:
            json.dump({"2395": {"total_buy_cost": 50000, "total_buy_shares": 100}}, f)
        self.perf = perf
        self.assertEqual(self._run(prices="2395=500"), 0)

    def test_holdings_without_csv_buy_is_flagged(self):
        with open(self.holdings, "w", encoding="utf-8") as f:
            json.dump({"2330": 5}, f)
        self.assertEqual(self._run(), 1)

    def test_unpriced_symbol_is_not_reported_consistent(self):
        """抓不到現價時市值算不出來 → 不可假回報「三口徑一致」。"""
        perf = write_csv(os.path.join(self.tmp.name, "nop.csv"), [
            ("2026-07-30T12:00:00", "9999", "1", "10.0", "10", "BUY"),
        ])
        with open(self.holdings, "w", encoding="utf-8") as f:
            json.dump({"9999": 10}, f)
        with open(self.alloc, "w", encoding="utf-8") as f:
            json.dump({}, f)
        self.perf = perf
        with mock.patch("core.inst_data.fetch_latest_closes", side_effect=RuntimeError("no net")):
            rc, out = self._run(prices="", json_out=True)
        self.assertEqual(rc, 1)
        self.assertEqual(out["unpriced"], ["9999"])
        self.assertFalse(out["consistent"])

    def test_empty_trades_is_consistent(self):
        perf = write_csv(os.path.join(self.tmp.name, "empty.csv"), [])
        with open(self.holdings, "w", encoding="utf-8") as f:
            json.dump({}, f)
        with open(self.alloc, "w", encoding="utf-8") as f:
            json.dump({}, f)
        self.perf = perf
        self.assertEqual(self._run(prices=""), 0)


if __name__ == "__main__":
    unittest.main()
