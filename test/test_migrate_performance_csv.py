#!/usr/bin/env python3
"""`scripts/migrate_performance_csv_schema.py` 的回歸測試。

背景（2026-09-13）：`logs/performance.csv` 表頭 6 欄，但 2026-09-01 10:15
（commit 165e994）之後寫入 7 欄（多 `exclude_daily`）⇒ 同一份檔混兩種寬度。
按欄位序號解析會錯位；`DictReader` 讀 7 欄列會把多出的值塞到 key `None`（靜默錯位）。
"""
import csv
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import migrate_performance_csv_schema as M  # noqa: E402
from core import books  # noqa: E402

HDR6 = "timestamp,symbol,signal,price,quantity,action"
HDR7 = HDR6 + ",exclude_daily"
HDR8 = HDR7 + ",cost"

# 取自 VM 實檔的樣態：6 欄舊列 + 7 欄新列 + 兩筆第 7 欄＝9 的來歷不明列
MIXED = "\n".join([
    HDR6,
    "2026-07-20T09:00:00.000000,1301,1,60.0,1000,BUY",   # 讓 1301 的賣出有對應買進
    "2026-07-29T09:00:44.228477,2395,1,551.0,12,BUY",
    "2026-07-30T12:39:17.794496,2395,1,548.0,273,BUY",
    "2026-07-24T09:00:01.244429,1301,-1,66.5,1000,SELL,9",
    "2026-09-11T09:33:45.856674,2006,1,81.6,735,BUY,0",
]) + "\n"


class MigrationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "performance.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return self.path

    def run_main(self, *args):
        old = sys.argv
        sys.argv = ["migrate", "--file", self.path] + list(args)
        try:
            return M.main()
        finally:
            sys.argv = old

    def rows(self):
        with open(self.path, newline="", encoding="utf-8") as f:
            return [r for r in csv.reader(f) if r]


class TestNormalize(MigrationFixture):
    def test_header_becomes_current_width(self):
        rows, st = M.normalize(M.read_rows(self.write(MIXED)))
        self.assertEqual(rows[0], M.HEADER)
        self.assertEqual(st["header_before"], 6)

    def test_six_column_rows_padded_with_zero(self):
        rows, st = M.normalize(M.read_rows(self.write(MIXED)))
        self.assertEqual(st["padded"], 5)          # 3 列 6 欄 + 2 列 7 欄，全部要補到 8 欄
        self.assertEqual(st["already_ok"], 0)
        self.assertEqual(st["padded_exclude_daily"], 3)
        self.assertEqual(st["padded_cost"], 5)
        for r in rows[1:]:
            self.assertEqual(len(r), 8, r)
        # exclude_daily 補 0（沿用舊語意：當時確實計入每日交易次數）
        self.assertEqual(rows[2][6], "0")
        # cost 補空＝未記錄（不捏造金額；讀取端以費率推定）
        self.assertEqual(rows[2][7], "")

    def test_unusual_last_field_is_left_untouched_and_reported(self):
        """第 7 欄＝9 的來歷不明列：不猜語意、照原樣留著，但要列出來。"""
        rows, st = M.normalize(M.read_rows(self.write(MIXED)))
        self.assertEqual(len(st["unusual_last_field"]), 1)   # fixture 內只有 1301 那筆
        kept = [r for r in rows[1:] if r[1] == "1301" and r[2] == "-1"][0]
        self.assertEqual(kept[6], "9")

    def test_idempotent(self):
        rows1, _ = M.normalize(M.read_rows(self.write(MIXED)))
        rows2, st2 = M.normalize(rows1)
        self.assertEqual(rows1, rows2)
        self.assertEqual(st2["padded"], 0)

    def test_empty_file_gets_header(self):
        rows, st = M.normalize([])
        self.assertEqual(rows, [M.HEADER])

    def test_headerless_rows_are_treated_as_data(self):
        rows, st = M.normalize([["t", "2330", "1", "10.0", "5", "BUY"]])
        self.assertEqual(rows[0], M.HEADER)
        self.assertEqual(len(rows[1]), 8)
        self.assertEqual(st["padded"], 1)

    def test_odd_width_row_reported_not_silently_fixed(self):
        # 3 欄不是任何歷史 schema → 壞列，必須回報而不是「補成看似正常」
        rows, st = M.normalize([list(M.HEADER), ["t", "2330", "1"]])
        self.assertEqual(len(st["anomalies"]), 1)
        self.assertEqual(len(rows[1]), 3)

    def test_render_quotes_commas(self):
        text = M.render([list(M.HEADER), ["t", "2330", "1", "10.0", "5", "BUY", "0"]])
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len(text.strip().split("\n")), 2)


class TestMain(MigrationFixture):
    def test_dry_run_does_not_write(self):
        self.write(MIXED)
        self.assertEqual(self.run_main(), 0)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), MIXED, "dry-run 不得改檔")

    def test_apply_pads_and_backs_up(self):
        self.write(MIXED)
        self.assertEqual(self.run_main("--apply"), 0)
        rows = self.rows()
        self.assertEqual(rows[0], M.HEADER)
        self.assertTrue(all(len(r) == 8 for r in rows))
        baks = [n for n in os.listdir(self.tmp.name) if ".bak_schema_" in n]
        self.assertEqual(len(baks), 1, "必須先備份")
        with open(os.path.join(self.tmp.name, baks[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), MIXED, "備份必須是遷移前的原樣")

    def test_apply_is_idempotent_and_reports_clean(self):
        self.write(MIXED)
        self.assertEqual(self.run_main("--apply"), 0)
        before = open(self.path, encoding="utf-8").read()
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(open(self.path, encoding="utf-8").read(), before)
        baks = [n for n in os.listdir(self.tmp.name) if ".bak_schema_" in n]
        self.assertEqual(len(baks), 1, "第二次已無事可做 → 不該再備份")

    def test_missing_file_exits_nonzero(self):
        self.assertEqual(self.run_main(), 1)

    def test_aborts_if_file_changed_after_read(self):
        """CAS：讀取後若有新成交 append → 中止，不可蓋掉。"""
        self.write(MIXED)
        real_norm = M.normalize

        def sneaky(rows):
            out = real_norm(rows)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write("2026-09-11T10:00:00.000000,2330,1,10.0,1,BUY,0\n")
            return out

        M.normalize = sneaky
        try:
            self.assertEqual(self.run_main("--apply"), 1, "檔案變了必須中止")
        finally:
            M.normalize = real_norm
        self.assertIn("2330", open(self.path, encoding="utf-8").read(), "新增的成交不可遺失")

    def test_apply_preserves_file_mode(self):
        """mkstemp 是 0600；遷移不得把原檔權限收窄（VM 上曾發生 644 → 600）。"""
        self.write(MIXED)
        os.chmod(self.path, 0o644)
        self.run_main("--apply")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_no_leftover_tmp_files(self):
        self.write(MIXED)
        self.run_main("--apply")
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp_")]
        self.assertEqual(leftovers, [])


class TestAuditIntegration(MigrationFixture):
    """遷移後 audit 的 schema 檢查必須由紅轉綠。"""

    def test_schema_drift_detected_by_audit(self):
        self.write(MIXED)
        s = books.csv_schema(self.path)
        self.assertFalse(s["ok"])
        self.assertEqual(s["header_cols"], 6)
        self.assertEqual(s["drift_rows"], 2)   # 兩列 7 欄 vs 表頭 6 欄

    def test_audit_ok_becomes_true_after_migration(self):
        self.write(MIXED)
        h = os.path.join(self.tmp.name, "holdings.json")
        a = os.path.join(self.tmp.name, "stock_allocation.json")
        # holdings 必須涵蓋 CSV FIFO 的全部未平倉部位（2395 285＋2006 735），
        # 否則會是 phantom，驗不到「schema 由紅轉綠」這件事。
        snap = {"2395": 285, "2006": 735}
        with open(h, "w", encoding="utf-8") as f:
            f.write('{"2395": 285, "2006": 735}')
        with open(a, "w", encoding="utf-8") as f:
            f.write("{}")
        pre = books.audit_books(self.path, holdings=snap, alloc={}, holdings_on_disk=snap)
        self.assertFalse(pre["csv_schema"]["ok"], "遷移前應偵測到混 schema")
        self.run_main("--apply")
        r = books.audit_books(self.path, holdings_path=h, alloc=books.load_ledger(a),
                              holdings_on_disk=snap)
        self.assertTrue(r["csv_schema"]["ok"], r["csv_schema"])
        self.assertEqual(r["phantom"], {})
        self.assertTrue(r["ok"], r["summary"])

    def test_schema_drift_makes_audit_not_ok(self):
        self.write(MIXED)
        r = books.audit_books(self.path, holdings={"2395": 285}, alloc={})
        self.assertFalse(r["ok"])
        self.assertIn("混 schema", r["summary"])
        self.assertIn("X6x", r["signature"])


class TestPandasImpact(MigrationFixture):
    """為什麼混 schema 不是美觀問題：pandas 會**靜默丟掉**寬度不符的列。"""

    def test_mixed_schema_makes_pandas_drop_rows(self):
        import pandas as pd
        self.write(MIXED)
        df = pd.read_csv(self.path, on_bad_lines="skip")
        n_mixed = len(df)
        self.assertEqual(n_mixed, 3, "6 欄表頭下，2 筆 7 欄列會被當成壞行丟掉")
        self.assertNotIn("exclude_daily", df.columns)

        self.run_main("--apply")
        df2 = pd.read_csv(self.path, on_bad_lines="skip")
        self.assertEqual(len(df2), 5, "遷移後 5 列全部讀得到")
        self.assertIn("exclude_daily", df2.columns)

    def test_exclude_daily_exclusion_requires_the_column(self):
        """`RiskManager._load_today_trades` 靠 `'exclude_daily' in df.columns` 判斷
        —— 欄位不存在時，全輪替排除每日額度的功能**靜默失效**（VM 實況就是如此）。"""
        import pandas as pd
        self.write(MIXED)
        self.assertNotIn("exclude_daily", pd.read_csv(self.path, on_bad_lines="skip").columns)
        self.run_main("--apply")
        self.assertIn("exclude_daily", pd.read_csv(self.path, on_bad_lines="skip").columns)


class TestHeaderSingleSource(unittest.TestCase):
    """遷移工具為了能離線執行而只用標準庫（不能 import risk_manager → 拖進 pandas），
    所以表頭定義是**複製**的 —— 用測試守住兩者一致。"""

    def test_migration_header_matches_risk_manager(self):
        from core.risk_manager import CSV_HEADER
        self.assertEqual(M.HEADER, CSV_HEADER)
        self.assertEqual(M.WIDTH, len(CSV_HEADER))

    def test_cost_is_the_last_column(self):
        from core.risk_manager import CSV_HEADER
        self.assertEqual(CSV_HEADER[-1], "cost")
        self.assertEqual(CSV_HEADER[6], "exclude_daily")


class TestWriterSchemaInvariant(unittest.TestCase):
    """writer 端必須永遠寫出「表頭寬度 == 資料列寬度」。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)          # RiskManager 用相對路徑 logs/performance.csv

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_fresh_file_header_matches_row_width(self):
        """2026-09-13 修正前：建檔寫 6 欄表頭、寫資料列寫 7 欄 → 從第一天就混 schema。"""
        from core.risk_manager import RiskManager, CSV_HEADER
        rm = RiskManager()
        rm.log_trade("2330", 1, 100.0, 10)
        with open(rm.log_file, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f) if r]
        self.assertEqual(rows[0], CSV_HEADER)
        self.assertEqual(len(rows[0]), 8)
        self.assertEqual(len(rows[1]), len(rows[0]), "資料列寬度必須等於表頭寬度")
        self.assertTrue(books.csv_schema(rm.log_file)["ok"])
        self.assertEqual(books.csv_schema(rm.log_file)["drift_rows"], 0)

    def test_log_trade_uses_lf_and_marks_exclude_daily(self):
        from core.risk_manager import RiskManager
        rm = RiskManager()
        rm.log_trade("2330", 1, 100.0, 10)
        rm.log_trade("2454", -1, 50.0, 2, exclude_from_daily=True)
        with open(rm.log_file, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r", raw, "統一 LF，避免檔案換行混用")
        rows = [r for r in csv.reader(open(rm.log_file, newline="", encoding="utf-8")) if r]
        self.assertEqual(rows[1][6], "0")
        self.assertEqual(rows[2][6], "1")
        self.assertEqual(rows[2][5], "SELL")


if __name__ == "__main__":
    unittest.main()
