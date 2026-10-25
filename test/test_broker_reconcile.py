"""迴歸測試：`scripts/reconcile_broker_books.py`（券商庫存 vs 本機帳本對帳，唯讀）。

fixture 用 2026-09-23 的**真實**玉山回傳（事故當天）：2884 券商 2000 股、本機帳 1584；
5876 券商 1000 股 @49.90、本機帳 1461 @49.25；2881 兩邊都是 470 @153.00。
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "_rbb", ROOT / "scripts" / "reconcile_broker_books.py")
rbb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rbb)

# 真實回傳（節錄必要欄位）
INV = [
    {"stk_no": "2881", "stk_na": "富邦金", "ap_code": "5", "qty_b": "470",
     "cost_qty": "1", "cost_sum": "-154", "price_avg": "153.00",
     "stk_dats": [{"qty": "1", "price": "153.00", "pay_n": "-154"}]},
    {"stk_no": "2884", "stk_na": "玉山金", "ap_code": "", "qty_b": "2000",
     "cost_qty": "2000", "cost_sum": "-91029", "price_avg": "45.45"},
    {"stk_no": "5876", "stk_na": "上海商銀", "ap_code": "", "qty_b": "1000",
     "cost_qty": "1000", "cost_sum": "-49971", "price_avg": "49.90"},
]
TX = [
    {"stk_no": "2881", "qty": "1", "price_avg": "153.00", "mat_dats": [{"fee": "1"}]},
    {"stk_no": "2884", "qty": "2000", "price_avg": "45.45", "mat_dats": [{"fee": "129"}]},
    {"stk_no": "5876", "qty": "1000", "price_avg": "49.90", "mat_dats": [{"fee": "71"}]},
]

CSV = """timestamp,symbol,signal,price,quantity,action,exclude_daily,cost
2026-09-23T13:25:11.941400,2881,1,153.0,470,BUY,0,102.0
2026-09-23T13:25:15.869154,2884,1,45.45,1584,BUY,0,103.0
2026-09-23T13:25:20.305335,5876,1,49.25,1461,BUY,0,103.0
2026-09-22T13:25:00.000000,2006,1,87.0,689,BUY,0,85.0
"""


class TestParsing(unittest.TestCase):
    def test_parse_inventories_uses_qty_b(self):
        inv = rbb.parse_inventories(INV)
        self.assertEqual(inv["2884"]["qty"], 2000)
        self.assertEqual(inv["5876"]["qty"], 1000)
        # 零股列：qty_b 才是總數（stk_dats[].qty 是「1 股為單位」的表示）
        self.assertEqual(inv["2881"]["qty"], 470, "零股不可拿 stk_dats[].qty 當總數")
        self.assertAlmostEqual(inv["2884"]["price"], 45.45)

    def test_parse_inventories_tolerates_garbage(self):
        self.assertEqual(rbb.parse_inventories(None), {})
        self.assertEqual(rbb.parse_inventories([{"no_sym": 1}, "x"]), {})
        self.assertEqual(rbb.parse_inventories([{"stk_no": "2884", "qty_b": "bad"}])["2884"]["qty"], 0)

    def test_parse_transactions_sums_fees(self):
        tx = rbb.parse_transactions(TX)
        self.assertEqual(tx["2884"]["qty"], 2000)
        self.assertEqual(tx["2884"]["fee"], 129)
        self.assertEqual(tx["2881"]["fee"], 1)
        self.assertAlmostEqual(tx["5876"]["price"], 49.90)

    def test_read_csv_rows_filters_by_date(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "performance.csv"
            p.write_text(CSV, encoding="utf-8")
            rows = rbb.read_csv_rows(p, "2026-09-23")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1][1], "2881")
        self.assertEqual(rbb.read_csv_rows(p, "1999-01-01"), [])


class TestReport(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "performance.csv"
            p.write_text(CSV, encoding="utf-8")
            self.rows = rbb.read_csv_rows(p, "2026-09-23")
        self.inv = rbb.parse_inventories(INV)

    def test_detects_the_2026_09_23_mismatch(self):
        """事故當天：2884 與 5876 的股數／價格都要被抓出來。"""
        holdings = {"2881": 470, "2884": 1584, "5876": 1461}
        rep = rbb.build_report(self.inv, holdings, self.rows, "2026-09-23")
        self.assertFalse(rep["ok"])
        bad = {r["sym"]: r["diffs"] for r in rep["rows"]}
        self.assertIn("2884", bad)
        self.assertIn("5876", bad)
        self.assertNotIn("2881", bad, "2881 是對的，不該被列為差異")
        self.assertTrue(any("2000" in x for x in bad["2884"]))
        self.assertTrue(any("49.9" in x for x in bad["5876"]), "價格差也要抓")

    def test_ok_when_everything_matches(self):
        holdings = {"2881": 470, "2884": 2000, "5876": 1000}
        csv_ok = """timestamp,symbol,signal,price,quantity,action,exclude_daily,cost
2026-09-23T13:25:11.941400,2881,1,153.0,470,BUY,0,1.0
2026-09-23T13:25:15.869154,2884,1,45.45,2000,BUY,0,129.0
2026-09-23T13:25:20.305335,5876,1,49.90,1000,BUY,0,71.0
"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "performance.csv"
            p.write_text(csv_ok, encoding="utf-8")
            rows = rbb.read_csv_rows(p, "2026-09-23")
        rep = rbb.build_report(self.inv, holdings, rows, "2026-09-23")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["rows"], [])
        self.assertEqual(len(rep["consistent"]), 3)

    def test_no_broker_data_is_not_ok(self):
        rep = rbb.build_report({}, {"2884": 2000}, self.rows, "2026-09-23")
        self.assertFalse(rep["ok"])
        self.assertTrue(rep["notes"], "查不到券商資料必須明講，不可當成通過")

    def test_notes_uncovered_holdings(self):
        """玉山 get_inventories() 只回當日成交標的 ⇒ 未涵蓋的持股要明講「無法比對」。"""
        rep = rbb.build_report(self.inv, {"2884": 2000, "2006": 689, "3653": 34},
                               self.rows, "2026-09-23")
        joined = " ".join(rep["notes"])
        self.assertIn("未涵蓋", joined)
        self.assertIn("2006", joined)
        self.assertIn("3653", joined)

    def test_holdings_missing_symbol_is_reported(self):
        rep = rbb.build_report(self.inv, {"2881": 470}, self.rows, "2026-09-23")
        bad = {r["sym"]: r["diffs"] for r in rep["rows"]}
        self.assertIn("2884", bad, "券商有、holdings 沒有 ⇒ 也要抓（幽靈／漏記）")


class TestSafety(unittest.TestCase):
    def test_tool_is_read_only(self):
        src = (ROOT / "scripts" / "reconcile_broker_books.py").read_text(encoding="utf-8")
        for bad in ("json.dump(", "write_text(", "open(args.holdings", 'open("w"'):
            self.assertNotIn(bad, src, f"對帳工具不可寫檔（{bad}）")
        self.assertIn("只讀不改", src)

    def test_provider_exposes_readonly_queries(self):
        src = (ROOT / "data" / "esun_provider.py").read_text(encoding="utf-8")
        self.assertIn("def query_inventories", src)
        self.assertIn("def query_transactions", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
