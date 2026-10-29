#!/usr/bin/env python3
"""`scripts/append_selector_prices.py` 的回歸測試（2026-09-14）。

背景：`cache/selector_prices/` 供母專案季度換股選股，但 `load_stock()` 有快取就直接用
（沒有新鮮度檢查）⇒ 候選池 100 檔實測全部停在 2026-08-13。
同一份快取也供 selector 自己的 `--grid/--backtest` 用（涵蓋 2015 起）
⇒ **只能附加、不能重抓或覆蓋**（重抓會讓歷史數值變動、回測結果靜默改變）。
"""
import os
import pickle
import time
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import append_selector_prices as A  # noqa: E402
from core import price_append as PA  # noqa: E402


def series(start, n, base=100.0, step=1.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": [base + i * step for i in range(n)],
         "high": [base + i * step + 1 for i in range(n)],
         "low": [base + i * step - 1 for i in range(n)],
         "close": [base + i * step for i in range(n)],
         "volume": [1000] * n},
        index=idx,
    )


class TestMergeAppend(unittest.TestCase):
    def test_appends_only_newer_dates(self):
        old = series("2026-08-01", 10)            # 至 08-14
        fresh = series("2026-08-10", 10)          # 08-10 ~ 08-21
        merged, st = PA.merge_append(old, fresh)
        self.assertEqual(len(merged), len(old) + 5)      # 只多 08-17~08-21
        self.assertEqual(st["last_old"], "2026-08-14")
        self.assertEqual(st["last_new"], "2026-08-21")
        self.assertEqual(st["rows_added"], 5)
        self.assertTrue(merged.index.is_monotonic_increasing)
        self.assertFalse(merged.index.duplicated().any())

    def test_old_history_is_untouched(self):
        """關鍵：歷史數值一個位元都不能變（否則回測結果會靜默改變）。"""
        old = series("2026-08-01", 10, base=100.0)
        fresh = series("2026-08-10", 10, base=999.0)   # 故意不同值
        merged, _ = PA.merge_append(old, fresh)
        for d in old.index:
            self.assertAlmostEqual(float(merged.loc[d, "close"]),
                                   float(old.loc[d, "close"]))

    def test_no_new_dates_returns_same(self):
        old = series("2026-08-01", 10)
        merged, st = PA.merge_append(old, series("2026-08-01", 10))
        self.assertEqual(st["rows_added"], 0)
        self.assertEqual(len(merged), len(old))

    def test_vintage_difference_is_measured(self):
        """重疊區間若價差大（除息回溯調整）→ 要能量出來。"""
        old = series("2026-08-01", 10, base=100.0)
        fresh = series("2026-08-05", 10, base=110.0)   # +10%
        _, st = PA.merge_append(old, fresh)
        self.assertGreater(st["vintage_max_diff"], 0.05)


class TestSeamSplice(unittest.TestCase):
    """接縫縮放：不同還原價版本之間不可留下假跳空（否則動能失真）。

    實測案例：3706 於 2026-08-14 接縫出現 −11.52%（新舊係數差 12.47%）。
    """

    def test_splice_removes_the_fake_gap(self):
        old = series("2026-08-01", 10, base=100.0, step=1.0)      # 舊基準
        fresh = series("2026-08-05", 10, base=80.0, step=1.0)     # 新基準（低 20%）
        merged, st = PA.merge_append(old, fresh, splice=True)
        # 接縫日（舊末日 → 下一天）的報酬必須只反映真實日變動，不該有版本跳空
        prev, nxt = merged.index[len(old) - 1], merged.index[len(old)]
        ret = float(merged.loc[nxt, "close"]) / float(merged.loc[prev, "close"]) - 1
        self.assertLess(abs(ret), 0.05, f"接縫報酬 {ret:.2%} 仍有假跳空")
        # 比例以「重疊最後一天」為基準（同一天、同一市場 ⇒ 純版本差異）
        d = old.index.intersection(fresh.index)[-1]
        self.assertAlmostEqual(st["splice_ratio"],
                               float(old.loc[d, "close"]) / float(fresh.loc[d, "close"]),
                               places=6)

    def test_splice_preserves_appended_daily_returns(self):
        old = series("2026-08-01", 10, base=100.0, step=1.0)
        fresh = series("2026-08-05", 10, base=80.0, step=1.0)
        merged, _ = PA.merge_append(old, fresh, splice=True)
        tail = merged["close"].iloc[len(old) - 1:]
        got = list(tail.pct_change().dropna().round(6))
        want = list(fresh["close"].loc[tail.index[0]:].pct_change().dropna().round(6))
        self.assertEqual(got, want, "附加段自身的日報酬必須完全不變")

    def test_splice_off_keeps_raw_values(self):
        old = series("2026-08-01", 10, base=100.0, step=1.0)
        fresh = series("2026-08-05", 10, base=80.0, step=1.0)
        merged, st = PA.merge_append(old, fresh, splice=False)
        self.assertAlmostEqual(st["splice_ratio"], 1.0)
        # 未縮放 → 接縫留著假跳空（-20% 級）
        prev, nxt = merged.index[len(old) - 1], merged.index[len(old)]
        ret = float(merged.loc[nxt, "close"]) / float(merged.loc[prev, "close"]) - 1
        self.assertLess(ret, -0.1)

    def test_no_vintage_change_ratio_is_one(self):
        """同一基準（重疊日收盤完全相同）→ ratio 必須是 1，不得亂縮放。"""
        old = series("2026-08-01", 10, base=100.0, step=1.0)
        # 同一個序列往後延伸：08-01 起第 3 個交易日是 08-05 → base 對齊 102
        fresh = series("2026-08-05", 10, base=102.0, step=1.0)
        merged, st = PA.merge_append(old, fresh, splice=True)
        self.assertAlmostEqual(st["splice_ratio"], 1.0, places=6)
        for d in old.index:
            self.assertAlmostEqual(float(merged.loc[d, "close"]), float(old.loc[d, "close"]))


class TestOldFormatCache(unittest.TestCase):
    """舊格式（原始 DataFrame、無 schema_version）必須能讀取並升級（2026-09-14 VM 實況）。

    VM 上的 selector_prices 就是這種格式（1111 列、只到 2026-08-05）。
    若用嚴格 load_cache() 讀 → 全部被跳過；且 selector 自己的 load_stock()
    會改成「下載 250 天並覆蓋」⇒ 歷史被毀。本工具必須能接住這種檔案。
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "selector_prices")
        os.makedirs(self.cache)
        self._old = A.CACHE_DIR
        A.CACHE_DIR = self.cache
        PA.CACHE_DIR = self.cache
        self.df = series("2026-07-01", 33)
        # 故意寫「舊格式」：直接 pickle 一個裸 DataFrame（無 schema_version）
        import pickle
        with open(os.path.join(self.cache, "2330.pkl"), "wb") as f:
            pickle.dump(self.df, f)

    def tearDown(self):
        A.CACHE_DIR = self._old
        self.tmp.cleanup()

    def test_old_format_is_read_and_upgraded(self):
        from core.cache_io import load_cache
        bak = os.path.join(self.tmp.name, "bak")
        argv = ["append", "--symbols", "2330", "--apply", "--backup-dir", bak]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(PA, "fetch_prices", return_value=series("2026-08-05", 20)), \
             mock.patch("builtins.print"):
            rc = A.main()
        self.assertEqual(rc, 0, "舊格式不可被跳過")
        payload = pickle.loads(open(os.path.join(self.cache, "2330.pkl"), "rb").read())
        self.assertIsInstance(payload, dict, "寫回時應升級成 v2 包裝")
        self.assertEqual(payload["schema_version"], 2)
        df2, _ = load_cache(os.path.join(self.cache, "2330.pkl"))
        self.assertIsNotNone(df2)
        self.assertGreater(len(df2), len(self.df), "長歷史必須保留並附加新資料")
        for d in self.df.index:
            self.assertAlmostEqual(float(df2.loc[d, "close"]), float(self.df.loc[d, "close"]))


class TestIntegrity(unittest.TestCase):
    def test_ok_when_history_preserved(self):
        old = series("2026-08-01", 10)
        merged, _ = PA.merge_append(old, series("2026-08-10", 10))
        ok, why = PA.integrity_ok(old, merged)
        self.assertTrue(ok, why)

    def test_detects_lost_rows(self):
        old = series("2026-08-01", 10)
        ok, why = PA.integrity_ok(old, old.iloc[:5])
        self.assertFalse(ok)
        self.assertIn("列數變少", why)

    def test_detects_changed_history_value(self):
        old = series("2026-08-01", 10)
        tampered = old.copy()
        tampered.iloc[0, tampered.columns.get_loc("close")] = 1.0
        ok, why = PA.integrity_ok(old, tampered)
        self.assertFalse(ok)
        self.assertIn("被改動", why)


class TestMainEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "selector_prices")
        os.makedirs(self.cache)
        self._old_dir = A.CACHE_DIR
        A.CACHE_DIR = self.cache
        PA.CACHE_DIR = self.cache
        # 寫一份舊快取（末日 2026-08-14，比今天舊）
        from core.cache_io import dump_cache
        self.old = series("2026-07-01", 33)         # 至 2026-08-14
        dump_cache(os.path.join(self.cache, "2330.pkl"), self.old,
                   meta={"symbol": "2330", "source": "yfinance"})

    def tearDown(self):
        A.CACHE_DIR = self._old_dir
        PA.CACHE_DIR = self._old_dir
        self.tmp.cleanup()

    def _run(self, *extra, fresh=None):
        argv = ["append", "--symbols", "2330", "--pool", "0"] + list(extra)
        fetcher = mock.Mock(return_value=fresh if fresh is not None else series("2026-08-10", 20))
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(PA, "fetch_prices", fetcher), \
             mock.patch("builtins.print"):
            rc = A.main()
        return rc, fetcher

    def test_dry_run_does_not_write(self):
        before = open(os.path.join(self.cache, "2330.pkl"), "rb").read()
        rc, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(open(os.path.join(self.cache, "2330.pkl"), "rb").read(), before)

    def test_apply_extends_and_keeps_history(self):
        from core.cache_io import load_cache
        rc, _ = self._run("--apply")
        self.assertEqual(rc, 0)
        df, meta = load_cache(os.path.join(self.cache, "2330.pkl"))
        self.assertIsNotNone(df)
        self.assertGreater(len(df), len(self.old))
        self.assertGreater(str(df.index[-1])[:10], "2026-08-14")
        # 舊歷史不變
        for d in self.old.index:
            self.assertAlmostEqual(float(df.loc[d, "close"]), float(self.old.loc[d, "close"]))
        self.assertIn("appended_at", meta)

    def test_apply_makes_a_backup_in_given_dir(self):
        """⚠️ 測試**必須**指定 --backup-dir 到 tmp。

        2026-09-14 教訓：本測試原本掃 `cache/selector_prices_bak_*` 並 rmtree，
        把**真實的生產備份**一起刪了（工具的備份目錄錨在 repo 的真實 cache 下）。
        ⇒ 工具備份目錄預設仍在 repo，但測試一律指定 tmp，且絕不刪真實目錄。
        """
        bak = os.path.join(self.tmp.name, "bak")
        rc, _ = self._run("--apply", "--backup-dir", bak)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(bak))
        self.assertIn("2330.pkl", os.listdir(bak))

    def test_already_fresh_is_skipped_without_download(self):
        """已是最新 → 不該連線下載（重跑要快且不打 API）。"""
        from core.cache_io import dump_cache
        today = PA.date.today()
        dump_cache(os.path.join(self.cache, "2330.pkl"), series(today, 3),
                   meta={"symbol": "2330"})
        rc, fetcher = self._run("--apply")
        self.assertEqual(rc, 0)
        fetcher.assert_not_called()

    def test_no_new_dates_skips_without_writing(self):
        """下載回來但沒有更新的日期 → 不寫檔（避免無謂改動快取）。"""
        from core.cache_io import load_cache
        before = open(os.path.join(self.cache, "2330.pkl"), "rb").read()
        rc, _ = self._run("--apply", fresh=series("2026-08-10", 5))   # 末日 08-14 = 舊末日
        self.assertEqual(rc, 0)
        self.assertEqual(open(os.path.join(self.cache, "2330.pkl"), "rb").read(), before)

    def test_download_failure_is_reported_not_fatal_for_dry_run(self):
        argv = ["append", "--symbols", "2330"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(PA, "fetch_prices", side_effect=RuntimeError("boom")), \
             mock.patch("builtins.print"):
            rc = A.main()
        self.assertEqual(rc, 1, "有失敗就該回非 0")

    def test_truncate_after_then_reappend(self):
        """補救路徑：丟掉接縫後的列、再重新附加（含縮放）。"""
        from core.cache_io import load_cache, dump_cache
        full = series("2026-07-01", 40)            # 至 2026-08-25
        dump_cache(os.path.join(self.cache, "2330.pkl"), full, meta={})
        seam = str(full.index[-3])[:10]            # 丟掉最後 2 列
        bak = os.path.join(self.tmp.name, "bak2")
        argv = ["append", "--symbols", "2330", "--apply",
                "--backup-dir", bak, "--truncate-after", seam]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(PA, "fetch_prices", return_value=series("2026-08-10", 20)), \
             mock.patch("builtins.print"):
            rc = A.main()
        self.assertEqual(rc, 0)
        df, meta = load_cache(os.path.join(self.cache, "2330.pkl"))
        # 截斷舊的接縫後段 → 重新附加（下載的 fresh 到 2026-09-04）
        self.assertEqual(str(df.index[-1])[:10], "2026-09-04")
        self.assertEqual(meta["truncated_rows"], 2)
        # 接縫（含）以前的舊列必須原封不動
        for d in full.index[:len(full) - 2]:
            self.assertAlmostEqual(float(df.loc[d, "close"]), float(full.loc[d, "close"]))

    def test_integrity_failure_aborts_write(self):
        before = open(os.path.join(self.cache, "2330.pkl"), "rb").read()
        argv = ["append", "--symbols", "2330", "--apply"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(PA, "merge_append", return_value=(self.old.iloc[:3], {
                 "rows_added": 1, "last_old": "2026-08-14", "last_new": "2026-09-14",
                 "vintage_max_diff": 0.0, "vintage_date": None})), \
             mock.patch.object(PA, "fetch_prices", return_value=series("2026-08-10", 20)), \
             mock.patch("builtins.print"):
            rc = A.main()
        self.assertEqual(rc, 1)
        self.assertEqual(open(os.path.join(self.cache, "2330.pkl"), "rb").read(), before,
                         "完整性檢查失敗時不可寫入")


if __name__ == "__main__":
    unittest.main()


class TestEnsureFresh(unittest.TestCase):
    """實盤選股前的自動補價（2026-09-14 V4.19 接進 `--recommend`）。

    鐵則：**任何失敗都不可阻斷選股**（回報後照用現有快取）。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "selector_prices")
        os.makedirs(self.cache)
        self._a, self._p = A.CACHE_DIR, PA.CACHE_DIR
        A.CACHE_DIR = PA.CACHE_DIR = self.cache
        from core.cache_io import dump_cache
        dump_cache(os.path.join(self.cache, "2330.pkl"), series("2026-07-01", 33), meta={})

    def tearDown(self):
        A.CACHE_DIR, PA.CACHE_DIR = self._a, self._p
        self.tmp.cleanup()

    def test_disabled_is_noop(self):
        with mock.patch.object(PA, "fetch_prices") as f:
            rep = PA.ensure_fresh(["2330"], enabled=False)
        self.assertEqual(rep["checked"], 0)
        f.assert_not_called()

    def test_updates_and_reports(self):
        with mock.patch.object(PA, "fetch_prices", return_value=series("2026-08-10", 20)):
            rep = PA.ensure_fresh(["2330"], verbose=False)
        self.assertEqual(rep["updated"], 1)
        self.assertEqual(rep["failed"], 0)

    def test_already_fresh_skips_without_download(self):
        from core.cache_io import dump_cache
        dump_cache(os.path.join(self.cache, "2330.pkl"), series(PA.date.today(), 3), meta={})
        with mock.patch.object(PA, "fetch_prices") as f:
            rep = PA.ensure_fresh(["2330"], verbose=False)
        self.assertEqual(rep["skipped"], 1)
        f.assert_not_called()

    def test_download_failure_does_not_raise(self):
        with mock.patch.object(PA, "fetch_prices", side_effect=RuntimeError("no net")):
            rep = PA.ensure_fresh(["2330"], verbose=False)
        self.assertEqual(rep["failed"], 1)
        self.assertTrue(rep["notes"], "失敗原因要記錄下來")

    def test_deadline_stops_early(self):
        with mock.patch.object(PA, "fetch_prices", side_effect=lambda *a: (time.sleep(0.05),
                                                                          series("2026-08-10", 20))[1]):
            rep = PA.ensure_fresh(["2330", "2454", "2317"], deadline_s=0.01, verbose=False)
        self.assertTrue(rep["stopped_early"])
        self.assertLess(rep["checked"], 3)

    def test_missing_symbol_is_skipped(self):
        rep = PA.ensure_fresh(["9999"], verbose=False)
        self.assertEqual(rep["skipped"], 1)


class TestWiringIntoSelectionFlow(unittest.TestCase):
    """防「有人日後把補價拿掉」或把 timeout 改回去（那會讓補價被殺掉）。"""

    def _read(self, rel):
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
            return f.read()



