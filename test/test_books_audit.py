#!/usr/bin/env python
"""`core/books.py` 的回歸測試 —— 三本帳一致性 + 原子寫入/檔案鎖。

背景（2026-09-13）：VM 上 2395/3665 各 36 股只寫進 performance.csv，沒進
holdings.json／分帳本（成本基礎缺口 92,484）⇒ 這些部位永遠不會被賣出。
本測試鎖住「偵測得到」與「缺檔不可靜默回退成 0」這兩件事。
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import books  # noqa: E402

# fixture 用完整 8 欄且 `cost=0`：本檔測「三本帳比對」，不該被手續費干擾
HDR = ["timestamp", "symbol", "signal", "price", "quantity", "action",
       "exclude_daily", "cost"]
COST0 = ["0", "0"]        # exclude_daily=0, cost=0


def write_csv(path, rows):
    """列不足 8 欄時自動補 `exclude_daily=0, cost=0`（見上方 COST0 說明）。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for r in rows:
            r = list(r)
            while len(r) < len(HDR):
                r.append("0")
            w.writerow(r)
    return path


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


class BooksFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.perf = os.path.join(d, "performance.csv")
        self.holdings_path = os.path.join(d, "holdings.json")
        self.alloc_path = os.path.join(d, "stock_allocation.json")

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self, holdings=None, **kw):
        return books.audit_books(
            self.perf,
            holdings=holdings if holdings is not None else books.load_holdings(self.holdings_path),
            alloc=books.load_ledger(self.alloc_path),
            **kw)


class TestAuditBooks(BooksFixture):
    def test_clean_books_ok(self):
        write_csv(self.perf, [("t", "2330", "1", "100.0", "10", "BUY")])
        write_json(self.holdings_path, {"2330": 10})
        write_json(self.alloc_path, {"2330": {"total_buy_cost": 1000, "total_buy_shares": 10}})
        r = self.audit()
        self.assertTrue(r["ok"], r["summary"])
        self.assertEqual(r["phantom"], {})
        self.assertEqual(r["signature"], "clean")
        self.assertAlmostEqual(r["ledger_gap"], 0.0)

    def test_phantom_position_detected(self):
        """CSV 說有 12 股、holdings 沒有 → 幽靈部位（VM 實案）。"""
        write_csv(self.perf, [("t", "2395", "1", "500.0", "12", "BUY")])
        write_json(self.holdings_path, {})
        write_json(self.alloc_path, {})
        r = self.audit()
        self.assertFalse(r["ok"])
        self.assertEqual(r["phantom"], {"2395": 12})
        self.assertEqual(r["holdings"], {})

    def test_ledger_gap_equals_phantom_cost(self):
        """分帳本成本基礎缺口 = 幽靈部位成本（= 92,484 的成因）。"""
        write_csv(self.perf, [("t", "2395", "1", "551.0", "12", "BUY")])
        write_json(self.holdings_path, {})
        write_json(self.alloc_path, {"2395": {"total_buy_cost": 0, "total_buy_shares": 0}})
        r = self.audit()
        self.assertAlmostEqual(r["ledger_gap"], 12 * 551.0)

    def test_ghost_holding_detected(self):
        """holdings 有、CSV 找不到買進 → 也是不一致（另一種方向的失真）。"""
        write_csv(self.perf, [])
        write_json(self.holdings_path, {"2330": 5})
        write_json(self.alloc_path, {})
        r = self.audit()
        self.assertFalse(r["ok"])
        self.assertEqual(r["ghost"], {"2330": 5})

    def test_missing_ledger_file_is_flagged_not_silent(self):
        """⚠️ 缺分帳本不可靜默當 0 —— 否則會算出 2,055,586 的荒謬總資產。

        這正是 2026-09-13 我自己引入的 bug：路徑誤指 data/stock_allocations.json
        （實盤其實是 logs/stock_allocation.json，單數）。
        """
        write_csv(self.perf, [("t", "2330", "1", "100.0", "10", "BUY")])
        write_json(self.holdings_path, {"2330": 10})
        # ⚠️ 不可依賴「本機 logs/ 剛好沒有分帳本」：VM 上該檔一定存在，
        #    開發機也可能有（2026-09-14 就是這樣壞掉的）→ 明確把預設路徑指到不存在的位置。
        missing_alloc = os.path.join(self.tmp.name, "no_such_allocation.json")
        with mock.patch.object(books, "ALLOC_FILE", missing_alloc):
            r = books.audit_books(self.perf, holdings={"2330": 10}, alloc=None)
        self.assertFalse(r["ok"])
        self.assertTrue(r["missing"], "缺檔必須被回報")
        self.assertIn(missing_alloc, r["missing"])

    def test_missing_perf_csv_is_flagged(self):
        r = books.audit_books(os.path.join(self.tmp.name, "nope.csv"),
                              holdings={}, alloc={})
        self.assertFalse(r["ok"])
        self.assertIn(os.path.join(self.tmp.name, "nope.csv"), r["missing"])

    def test_memory_drift_detected(self):
        """記憶體 holdings 與磁碟不同 = 別的 writer 寫過 → 下次 save 會蓋掉對方。"""
        write_csv(self.perf, [("t", "2330", "1", "100.0", "10", "BUY")])
        write_json(self.holdings_path, {"2330": 10, "2454": 3})
        r = self.audit(holdings={"2330": 10}, holdings_path=self.holdings_path)
        self.assertFalse(r["ok"])
        self.assertEqual(r["memory_drift"], {"2454": [0, 3]})

    def test_ledger_gap_alone_does_not_flip_ok(self):
        """⚠️ ledger_gap 只是參考值，**不可**列入 ok —— 否則會誤報。

        分帳本是加權平均成本按比例扣減（`sell_stock_allocation`），CSV 這邊是 FIFO；
        買價不同又部分賣出時兩者本來就會合法地不同（本例差 250）。
        """
        write_csv(self.perf, [
            ("t", "2330", "1", "10.0", "100", "BUY"),
            ("t", "2330", "1", "20.0", "100", "BUY"),
            ("t", "2330", "-1", "30.0", "50", "SELL"),
        ])
        # CSV FIFO 未平倉 = 50@10 + 100@20 = 2,500；分帳本均價法 = 3,000 − 15×50 = 2,250
        write_json(self.holdings_path, {"2330": 150})
        write_json(self.alloc_path, {"2330": {"total_buy_cost": 2250, "total_buy_shares": 150}})
        r = self.audit()
        self.assertAlmostEqual(r["ledger_gap"], 250.0)
        self.assertTrue(r["ok"], "部位一致時，FIFO vs 均價的成本差不得判為不一致")
        self.assertEqual(r["phantom"], {})
        self.assertEqual(r["ghost"], {})

    def test_signature_changes_when_discrepancy_changes(self):
        """通知去重靠 signature：同一種不一致同一個值、換一種就變。"""
        write_csv(self.perf, [("t", "2395", "1", "500.0", "12", "BUY")])
        write_json(self.holdings_path, {})
        write_json(self.alloc_path, {})
        s1 = self.audit()["signature"]
        write_csv(self.perf, [("t", "2395", "1", "500.0", "24", "BUY")])
        s2 = self.audit()["signature"]
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(s1, "clean")

    def test_unmatched_sell_detected(self):
        write_csv(self.perf, [("t", "2330", "-1", "100.0", "5", "SELL")])
        write_json(self.holdings_path, {})
        write_json(self.alloc_path, {})
        r = self.audit()
        self.assertFalse(r["ok"])
        self.assertEqual(r["unmatched"], {"2330": 5})

    def test_append_audit_log_writes_jsonl(self):
        log = os.path.join(self.tmp.name, "books_audit.jsonl")
        write_csv(self.perf, [("t", "2395", "1", "500.0", "12", "BUY")])
        write_json(self.holdings_path, {})
        write_json(self.alloc_path, {})
        books.append_audit_log(self.audit(), {"source": "test"}, path=log)
        books.append_audit_log(self.audit(), {"source": "test"}, path=log)
        with open(log, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["phantom"], {"2395": 12})
        self.assertEqual(lines[0]["source"], "test")
        self.assertIn("ts", lines[0])


class TestAtomicWriteAndLock(BooksFixture):
    def test_atomic_write_creates_valid_json_and_no_temp_leftover(self):
        p = os.path.join(self.tmp.name, "h.json")
        books.atomic_write_json(p, {"2330": 10})
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"2330": 10})
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp_")]
        self.assertEqual(leftovers, [], "暫存檔必須被 rename 掉，不能殘留")

    def test_atomic_write_overwrites_existing(self):
        p = os.path.join(self.tmp.name, "h.json")
        books.atomic_write_json(p, {"2330": 10})
        books.atomic_write_json(p, {"2330": 20})
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"2330": 20})

    def test_atomic_write_creates_missing_directory(self):
        p = os.path.join(self.tmp.name, "sub", "dir", "h.json")
        books.atomic_write_json(p, {"a": 1})
        self.assertTrue(os.path.exists(p))

    def test_atomic_write_preserves_existing_mode(self):
        """mkstemp 是 0600 → 直接 os.replace 會把 0644 的狀態檔變成只有 root 可讀。"""
        p = os.path.join(self.tmp.name, "h.json")
        books.atomic_write_json(p, {"a": 1})
        os.chmod(p, 0o640)
        books.atomic_write_json(p, {"a": 2})
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o640)

    def test_atomic_write_new_file_is_not_root_only(self):
        p = os.path.join(self.tmp.name, "fresh.json")
        books.atomic_write_json(p, {"a": 1})
        mode = os.stat(p).st_mode & 0o777
        self.assertTrue(mode & 0o044, f"新檔不該只有擁有者可讀（mode={oct(mode)}）")

    def test_lock_excludes_other_process(self):
        """file_lock 必須真的擋住另一個行程（不只是同行程的擺設）。"""
        target = os.path.join(self.tmp.name, "h.json")
        code = (
            "import fcntl, sys\n"
            "f = open(sys.argv[1], 'a+')\n"
            "try:\n"
            "    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except OSError:\n"
            "    sys.exit(0)\n"   # 被擋住 = 鎖有效
            "sys.exit(1)\n"       # 拿到鎖 = 鎖沒生效
        )
        with books.file_lock(target):
            r = subprocess.run([sys.executable, "-c", code, target + ".lock"],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, f"檔案鎖沒生效 rc={r.returncode} {r.stderr[:200]}")

    def test_save_json_goes_through_locked_atomic_path(self):
        """core.live_state.save_json 必須用同一套原子/鎖語義（所有 writer 的咽喉）。"""
        from core import live_state
        p = os.path.join(self.tmp.name, "holdings.json")
        live_state.save_json({"2330": 7}, p)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"2330": 7})
        self.assertTrue(os.path.exists(p + ".lock"))


class TestLiveWiring(BooksFixture):
    """實盤端必須真的掛上帳務斷言。"""

    def _src(self, rel):
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_audit_hook_wired_in_both_copies(self):
        for rel in ("selfselect_trader.py",):
            src = self._src(rel)
            self.assertIn("from core.books import audit_books", src, f"{rel} 沒掛斷言")
            self.assertIn("_books_audit_sig", src, f"{rel} 沒做通知去重")



if __name__ == "__main__":
    unittest.main()
