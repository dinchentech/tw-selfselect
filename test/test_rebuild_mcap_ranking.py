#!/usr/bin/env python3
"""`scripts/rebuild_mcap_ranking.py` 的回歸測試（2026-09-18）。

背景：實盤選股的候選池來自 `cache/inst_momentum/mcap_ranking.pkl`，但 repo 內**沒有產生器**，
檔案凍結在 2026-06-26 ⇒ 池子太舊 ⇒ 新進榜的高動能股不在名單裡 ⇒ **系統性追高**
（8/31 選出距高點僅 −2.1% 的 2059，而當時真市值前 100 會選 3406/6213/3008）。

本測試釘住「市值＝股數×收盤價、排序、過濾規則」這些會直接改變實盤選股的部分。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import rebuild_mcap_ranking as R  # noqa: E402


class TestParse(unittest.TestCase):
    def test_parse_shares_handles_commas_and_blanks(self):
        rows = [{"公司代號": "2330", "已發行普通股數或TDR原股發行股數": "25,932,370,067"},
                {"公司代號": "9999", "已發行普通股數或TDR原股發行股數": ""},
                {"公司代號": "", "已發行普通股數或TDR原股發行股數": "100"}]
        self.assertEqual(R.parse_shares(rows), {"2330": 25932370067})

    def test_parse_closes_skips_bad_price_and_reads_roc_date(self):
        rows = [{"Date": "1150916", "Code": "2330", "ClosingPrice": "2380.00"},
                {"Date": "1150916", "Code": "1234", "ClosingPrice": "--"},
                {"Date": "1150916", "Code": "5678", "ClosingPrice": "0"}]
        closes, day = R.parse_closes(rows)
        self.assertEqual(closes, {"2330": 2380.0})
        self.assertEqual(day, "2026-09-16")


class TestRankMarketCap(unittest.TestCase):
    def test_orders_by_market_cap_desc(self):
        shares = {"2330": 25_000_000_000, "2059": 95_297_072}
        closes = {"2330": 2380.0, "2059": 11_700.0}
        got = [s for s, _ in R.rank_market_cap(shares, closes)]
        self.assertEqual(got, ["2330", "2059"])

    def test_excludes_etf_and_non_four_digit(self):
        shares = {"0050": 1_000_000_000, "2330": 25_000_000_000, "12345": 10, "1201": 100}
        closes = {"0050": 106.0, "2330": 2380.0, "12345": 10.0, "1201": 20.0}
        got = [s for s, _ in R.rank_market_cap(shares, closes)]
        self.assertEqual(got, ["2330", "1201"])          # ETF 與 5 碼一律排除

    def test_skips_missing_or_zero_values(self):
        shares = {"2330": 25_000_000_000, "1201": 0, "1202": 1000}
        closes = {"2330": 2380.0, "1201": 20.0}          # 1202 沒有收盤價
        got = [s for s, _ in R.rank_market_cap(shares, closes)]
        self.assertEqual(got, ["2330"])

    def test_cap_is_in_hundred_million_twd(self):
        got = dict(R.rank_market_cap({"2330": 25_932_370_067}, {"2330": 2380.0}))
        self.assertAlmostEqual(got["2330"], 25_932_370_067 * 2380.0 / 1e8, places=0)


class TestPoolCompatibility(unittest.TestCase):
    """產出的 list 必須能被選股端的 `build_candidate_pool()` 直接吃（格式不可改）。"""

    def test_output_is_consumable_by_selector(self):
        import stock_selector_grid as ssg
        ranked = [s for s, _ in R.rank_market_cap(
            {"2330": 25_000_000_000, "0050": 1_000_000_000, "1201": 500_000_000},
            {"2330": 2380.0, "0050": 106.0, "1201": 20.0})]
        self.assertEqual(ssg.build_candidate_pool(ranked, 3), ["2330", "1201"])


if __name__ == "__main__":
    unittest.main()
