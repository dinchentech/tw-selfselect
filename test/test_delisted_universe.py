#!/usr/bin/env python
"""已下市個股必須進宇宙（補倖存者偏差）＋新鮮度閘門（不得污染實盤池）。

背景（2026-10-29）：池子原本只由 `historical_shares.pkl` 建，而那份只有「今天還活著」
的 612 檔 ⇒ 回測永遠選不到後來下市（多半是地雷）的公司，績效被系統性高估。
補 `historical_shares_delisted.pkl`（2016-2025 TWSE 下市清單）後：
  · 回測：已下市個股在它還活著的季點會正常參與市值排名。
  · 實盤：`build_quarterly_pool` 的 `max_stale_days` 讓「季點前 45 天內沒有成交價」
    的標的（＝已下市／長期停牌）自動退出池子，所以補資料不會讓實盤去買不存在的股票。
"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import candidate_pool as cp


def _px(start, end, price=100.0):
    idx = pd.date_range(start, end, freq="B")
    return pd.DataFrame({"date": idx, "close": [price] * len(idx)})


class TestLoadHistoricalShares(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join("TMP", "test_shares")
        os.makedirs(self.tmp, exist_ok=True)
        self.listed = os.path.join(self.tmp, "listed.pkl")
        self.delisted = os.path.join(self.tmp, "delisted.pkl")
        from core.cache_io import dump_cache
        dump_cache(self.listed, {("2330", "2020-02"): 1e10, ("2330", "2020-05"): 1e10})
        dump_cache(self.delisted, {("3519", "2020-02"): 5e9})

    def tearDown(self):
        for p in (self.listed, self.delisted):
            if os.path.exists(p):
                os.remove(p)

    def test_merges_delisted_by_default(self):
        old = os.environ.pop("UNIVERSE_DELISTED", None)
        try:
            hist, src = cp.load_historical_shares(self.listed, self.delisted)
        finally:
            if old is not None:
                os.environ["UNIVERSE_DELISTED"] = old
        self.assertEqual({k[0] for k in hist}, {"2330", "3519"})
        self.assertIn("listed", src)
        self.assertTrue(any(s.startswith("delisted") for s in src))

    def test_can_disable_delisted(self):
        os.environ["UNIVERSE_DELISTED"] = "0"
        try:
            hist, src = cp.load_historical_shares(self.listed, self.delisted)
        finally:
            os.environ.pop("UNIVERSE_DELISTED", None)
        self.assertEqual({k[0] for k in hist}, {"2330"})
        self.assertEqual(src, ["listed"])

    def test_missing_delisted_file_is_not_fatal(self):
        hist, src = cp.load_historical_shares(
            self.listed, os.path.join(self.tmp, "nope.pkl"))
        self.assertEqual({k[0] for k in hist}, {"2330"})
        self.assertEqual(src, ["listed"])


class TestPoolFreshnessGuard(unittest.TestCase):
    def test_delisted_ranks_while_alive_then_drops(self):
        """3519 在 2020-03 前有價、之後沒價 ⇒ 2020-02 進池、2020-08 起退出。"""
        hist = {("3519", q): 1e11 for q in ("2020-02", "2020-05", "2020-08", "2020-11")}
        hist.update({("2330", q): 1e9 for q in ("2020-02", "2020-05", "2020-08", "2020-11")})
        data = {
            "3519": _px("2019-01-01", "2020-03-31", 50.0),   # 2020-03 下市
            "2330": _px("2019-01-01", "2021-01-31", 100.0),
        }
        pools = cp.build_quarterly_pool(hist, data, top_n=5)
        self.assertIn("3519", pools["2020-02"])
        self.assertEqual(pools["2020-02"][0], "3519")   # 市值大者在前
        self.assertNotIn("3519", pools["2020-08"])
        self.assertNotIn("3519", pools["2020-11"])
        self.assertIn("2330", pools["2020-11"])

    def test_stale_guard_can_be_switched_off(self):
        hist = {("3519", "2020-08"): 1e11}
        data = {"3519": _px("2019-01-01", "2020-03-31", 50.0)}
        self.assertEqual(cp.build_quarterly_pool(hist, data, top_n=5)["2020-08"], [])
        loose = cp.build_quarterly_pool(hist, data, top_n=5, max_stale_days=0)
        self.assertEqual(loose["2020-08"], ["3519"])

    def test_fresh_stock_kept(self):
        hist = {("2330", "2020-08"): 1e9}
        data = {"2330": _px("2020-01-01", "2020-09-30", 100.0)}
        self.assertEqual(cp.build_quarterly_pool(hist, data, top_n=5)["2020-08"], ["2330"])


if __name__ == "__main__":
    unittest.main()
