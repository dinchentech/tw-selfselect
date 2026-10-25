#!/usr/bin/env python3
"""「最後一根 K 棒是 NaN」防護的回歸測試（2026-09-18）。

背景（實測事故）：yfinance 對**最新一個交易日**可能回傳「只有 volume、OHLC 全 NaN」的半成品 K 棒。
2026-09-18 實測 `cache/selector_prices/` 500/500 檔的 **2026-09-17** 全部是這種列
（09-16 及以前 0 筆 NaN）。

後果（為什麼一定要擋）：`ensure_fresh()` 會把這根 NaN 列**附加進快取** ⇒
`cache` 最後一列 = 選股基準日 = NaN ⇒ `score_stock()` 的 `close`/波動/均線全變 NaN ⇒
`total` 全是 NaN ⇒ `pick_top_stocks()` 的排序失效 ⇒ **亂選**。
實測（基準日 2026-09-17）選出 2317/2881/2882，三檔 total 都是 NaN；
丟掉 NaN 列（基準日 09-16）才是正常分數的 2883/2884/2887。

兩道防護：
  ① `core.price_append.merge_append()`：不可把 close 為 NaN 的**新列**寫進快取（source guard）。
  ② `stock_selector_grid.load_stock()`：讀取／下載後丟掉 close 為 NaN 的列（consumer guard，
     順帶覆蓋「已經躺在快取裡的」NaN 列，例如 09-17 那批）。
"""
import os
import shutil
import sys
import tempfile
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from core import price_append as PA  # noqa: E402
import stock_selector_grid as ssg  # noqa: E402


def frame(dates, closes, volumes=None):
    n = len(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": volumes if volumes is not None else [1000] * n},
        index=pd.to_datetime(dates),
    )


class TestMergeAppendDropsNaNRows(unittest.TestCase):
    def test_nan_close_row_is_not_appended(self):
        old = frame(["2026-09-15", "2026-09-16"], [100.0, 101.0])
        fresh = frame(["2026-09-16", "2026-09-17"], [101.0, float("nan")],
                      volumes=[1000, 555])
        merged, st = PA.merge_append(old, fresh)
        self.assertNotIn(pd.Timestamp("2026-09-17"), merged.index)
        self.assertEqual(st["rows_added"], 0)
        self.assertEqual(str(merged.index[-1])[:10], "2026-09-16")

    def test_good_rows_after_bad_row_are_still_appended(self):
        old = frame(["2026-09-15"], [100.0])
        fresh = frame(["2026-09-15", "2026-09-16", "2026-09-17"],
                      [100.0, 102.0, float("nan")])
        merged, st = PA.merge_append(old, fresh)
        self.assertEqual([str(d)[:10] for d in merged.index],
                         ["2026-09-15", "2026-09-16"])
        self.assertEqual(st["rows_added"], 1)

    def test_old_rows_with_nan_are_left_alone(self):
        """舊列一位元都不動（回測可重現性）——即使舊列本身是 NaN。"""
        old = frame(["2026-09-15", "2026-09-16"], [100.0, float("nan")])
        fresh = frame(["2026-09-16", "2026-09-17"], [101.0, 103.0])
        merged, _ = PA.merge_append(old, fresh)
        self.assertTrue(pd.isna(merged.loc[pd.Timestamp("2026-09-16"), "close"]))

    def test_nonpositive_close_is_also_dropped(self):
        old = frame(["2026-09-15"], [100.0])
        fresh = frame(["2026-09-15", "2026-09-16"], [100.0, 0.0])
        merged, st = PA.merge_append(old, fresh)
        self.assertEqual(st["rows_added"], 0)


class TestLoadStockDropsNaNRows(unittest.TestCase):
    """`load_stock()` 必須濾掉 NaN 列 —— 這是選股基準日不會落在 NaN 上的保證。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nan_guard_")
        self._old_dir = ssg._PRICE_CACHE_DIR
        self._old_cache = dict(ssg._cache)
        ssg._PRICE_CACHE_DIR = self.tmp
        ssg._cache.clear()

    def tearDown(self):
        ssg._PRICE_CACHE_DIR = self._old_dir
        ssg._cache.clear()
        ssg._cache.update(self._old_cache)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cached_nan_row_is_filtered(self):
        from core.cache_io import dump_cache
        df = frame(["2026-09-15", "2026-09-16", "2026-09-17"],
                   [100.0, 101.0, float("nan")])
        dump_cache(os.path.join(self.tmp, "2330.pkl"), df)
        got = ssg.load_stock("2330")
        self.assertEqual(str(got.index[-1])[:10], "2026-09-16")
        self.assertFalse(got["close"].isna().any())

    def test_reference_date_never_lands_on_nan(self):
        """實務症狀：基準日（最後一列）落在 NaN ⇒ 全池 total 變 NaN ⇒ 亂選。"""
        df = frame(["2026-09-15", "2026-09-16", "2026-09-17"],
                   [100.0, 101.0, float("nan")])
        d = pd.Timestamp("2026-09-18")
        av = df[df.index <= d]
        self.assertTrue(pd.isna(df.loc[av.index[-1], "close"]))     # 未防護時：NaN 基準日
        from core.cache_io import dump_cache
        dump_cache(os.path.join(self.tmp, "2330.pkl"), df)
        got = ssg.load_stock("2330")
        av2 = got[got.index <= d]
        self.assertFalse(pd.isna(got.loc[av2.index[-1], "close"]))  # 防護後：正常基準日


if __name__ == "__main__":
    unittest.main()
