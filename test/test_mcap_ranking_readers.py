#!/usr/bin/env python3
"""市值排名「讀取端」的回歸測試（2026-09-18）。

背景：`cache/inst_momentum/mcap_ranking.pkl` 有兩種格式並存（舊＝裸 list、
新＝`core.cache_io.dump_cache` 的 v2 dict）。選股端 `build_candidate_pool()` 兩種都吃，
但 `core/inst_data.get_all_stock_ids()` 與 `plans/backtest_inst_momentum.py` 用**裸 pickle.loads**
⇒ 讀到 v2 dict 時 `ranked` 為空 ⇒ **無聲退回「按 stock_id 排序」的假池**
（≈ 1101、1102… 一堆老牌冷門股），選股/回測全錯卻沒有任何訊息。

本測試鎖住：兩種格式都要讀得到，而且讀不到時**必須出聲**（不可靜默退假池）。
"""
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.cache_io import dump_cache, read_ranking_codes  # noqa: E402
from core import inst_data  # noqa: E402


class TestReadRankingCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rank_reader_")

    def _path(self, name="r.pkl"):
        return os.path.join(self.tmp, name)

    def test_reads_v2_dump_cache_format(self):
        p = self._path()
        dump_cache(p, ["2330", "2454", "2308"])
        self.assertEqual(read_ranking_codes(p), ["2330", "2454", "2308"])

    def test_reads_legacy_bare_list(self):
        p = self._path()
        Path(p).write_bytes(pickle.dumps(["2330", "2317"]))
        self.assertEqual(read_ranking_codes(p), ["2330", "2317"])

    def test_reads_wrapped_dict_payload(self):
        p = self._path()
        Path(p).write_bytes(pickle.dumps({"data": ["2330", "2317"]}))
        self.assertEqual(read_ranking_codes(p), ["2330", "2317"])

    def test_filters_non_four_digit(self):
        """只要求「4 碼數字」；ETF（00xx）由呼叫端用 exclude_etf 決定要不要剔除。"""
        p = self._path()
        dump_cache(p, ["2330", "0050", "12345", "abc"])
        self.assertEqual(read_ranking_codes(p), ["2330", "0050"])

    def test_missing_or_broken_file_returns_empty(self):
        self.assertEqual(read_ranking_codes(self._path("nope.pkl")), [])
        broken = self._path("broken.pkl")
        Path(broken).write_bytes(b"not a pickle")
        self.assertEqual(read_ranking_codes(broken), [])


class FakeDL:
    """假的 FinMind DataLoader（真實呼叫要 token／網路，測試不該連網）。"""

    def __init__(self):
        self.called = False

    def taiwan_stock_info(self):
        import pandas as pd
        self.called = True
        return pd.DataFrame({"stock_id": ["1101", "1102", "2330"], "type": ["twse"] * 3})


class TestGetAllStockIds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rank_reader_")

    def test_v2_format_is_used_not_fallback(self):
        p = os.path.join(self.tmp, "rank.pkl")
        dump_cache(p, ["2330", "2454", "2308", "2317"])
        dl = FakeDL()
        ids = inst_data.get_all_stock_ids(dl, n=3, mcap_file=p)
        self.assertEqual(ids, ["2330", "2454", "2308"])
        self.assertFalse(dl.called, "讀得到排名就不該去打 FinMind 拿替代池")

    def test_exclude_etf_drops_zero_prefixed(self):
        p = os.path.join(self.tmp, "rank.pkl")
        dump_cache(p, ["0050", "2330", "2317"])
        self.assertEqual(inst_data.get_all_stock_ids(FakeDL(), n=5, mcap_file=p), ["2330", "2317"])

    def test_unreadable_ranking_warns_loudly(self):
        """檔案在、卻讀不出代號 ⇒ 必須印警告（不可靜默退回假池）。"""
        import io
        import contextlib
        p = os.path.join(self.tmp, "rank.pkl")
        Path(p).write_bytes(b"garbage")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ids = inst_data.get_all_stock_ids(FakeDL(), n=2, mcap_file=p)
        self.assertIn("市值排名讀不出任何代號", buf.getvalue())
        self.assertEqual(ids, ["1101", "1102"])      # 仍提供替代池，但已出聲

    def test_no_mcap_file_falls_back_silently(self):
        dl = FakeDL()
        self.assertEqual(inst_data.get_all_stock_ids(dl, n=2, mcap_file=None), ["1101", "1102"])
        self.assertTrue(dl.called)


if __name__ == "__main__":
    unittest.main()
