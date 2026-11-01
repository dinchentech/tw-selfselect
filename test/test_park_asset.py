#!/usr/bin/env python
"""`core/park_asset.py`（實盤閒置資金停泊）的純函式回歸測試。

守住的規則（使用者 2026-10-31 裁定）：
1. **預設開啟、停泊 `0050`**；只有明確寫 `SELFSELECT_PARK_ASSET=`（空字串）才是「不用停泊」。
2. 只在 **immediate** 模式、且名單每一檔都「已持有或今天已嘗試買進」時才停泊（signal 模式不停泊）。
3. 停泊金額不得把「已停泊的市值」再算成閒置（避免重複買）。
4. 太小的金額不做（< MIN_PARK_NTD）；以整股買進。
5. 要買股時賣出剛好夠用的股數（向上取整、不超過持有）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.park_asset import (DEFAULT_SYMBOL, MIN_PARK_NTD, can_park_after_build,  # noqa: E402
                             enabled, idle_amount, load_state, park_shares, park_symbol,
                             release_shares, save_state)


class TestSymbolAndEnabled(unittest.TestCase):
    def test_default_is_enabled_with_0050(self):
        """2026-10-31 第二版：未設定 ⇒ **預設停泊 0050**。"""
        self.assertEqual(park_symbol({}), "0050")
        self.assertTrue(enabled({}))
        self.assertEqual(DEFAULT_SYMBOL, "0050")

    def test_explicit_empty_turns_it_off(self):
        """`SELFSELECT_PARK_ASSET=`（明確留空）＝使用者關閉停泊。"""
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": ""}), "")
        self.assertFalse(enabled({"SELFSELECT_PARK_ASSET": ""}))
        self.assertFalse(enabled({"SELFSELECT_PARK_ASSET": "   "}))

    def test_user_can_specify(self):
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": "0050"}), "0050")
        self.assertEqual(park_symbol({"SELFSELECT_PARK_ASSET": "00878"}), "00878")
        self.assertTrue(enabled({"SELFSELECT_PARK_ASSET": "00878"}))

    def test_reads_real_env(self):
        old = os.environ.pop("SELFSELECT_PARK_ASSET", None)
        try:
            self.assertTrue(enabled())                       # 未設定 ⇒ 預設停泊 0050
            self.assertEqual(park_symbol(), "0050")
            os.environ["SELFSELECT_PARK_ASSET"] = "0056"
            self.assertTrue(enabled())
            self.assertEqual(park_symbol(), "0056")
            os.environ["SELFSELECT_PARK_ASSET"] = ""
            self.assertFalse(enabled())                      # 明確留空 ⇒ 關閉
        finally:
            os.environ.pop("SELFSELECT_PARK_ASSET", None)
            if old is not None:
                os.environ["SELFSELECT_PARK_ASSET"] = old


class TestIdleAmount(unittest.TestCase):
    def test_subtracts_stock_and_parked_value(self):
        # 腿額度 100 萬、股票市值 60 萬、已停泊 30 萬 ⇒ 閒置 10 萬（不能把停泊的再算一次）
        self.assertAlmostEqual(idle_amount(1_000_000, 600_000, 300_000), 100_000)
        self.assertAlmostEqual(idle_amount(1_000_000, 600_000), 400_000)

    def test_never_negative(self):
        self.assertEqual(idle_amount(1_000_000, 1_200_000), 0.0)
        self.assertEqual(idle_amount(None, 1), 0.0)


class TestParkShares(unittest.TestCase):
    def test_whole_shares_round_down(self):
        self.assertEqual(park_shares(100_000, 105.5), 947)      # 947 × 105.5 = 99,908
        self.assertEqual(park_shares(1_000_000, 200), 5000)

    def test_too_small_is_skipped(self):
        self.assertEqual(park_shares(MIN_PARK_NTD - 1, 50), 0)   # 金額不足門檻
        self.assertEqual(park_shares(5_000, 50), 0)              # 也不足 1 張的錢

    def test_bad_price(self):
        self.assertEqual(park_shares(100_000, 0), 0)
        self.assertEqual(park_shares(100_000, -5), 0)

    def test_boundary_exactly_min(self):
        self.assertEqual(park_shares(MIN_PARK_NTD, 100), int(MIN_PARK_NTD // 100))


class TestReleaseShares(unittest.TestCase):
    def test_rounds_up_and_clamps(self):
        self.assertEqual(release_shares(10_000, 100, 200), 100)   # 剛好 100 股
        self.assertEqual(release_shares(10_050, 100, 200), 101)   # 向上取整
        self.assertEqual(release_shares(10_000, 100, 50), 50)     # 不足則賣光

    def test_zero_cases(self):
        self.assertEqual(release_shares(0, 100, 200), 0)
        self.assertEqual(release_shares(10_000, 0, 200), 0)
        self.assertEqual(release_shares(10_000, 100, 0), 0)


class TestCanParkAfterBuild(unittest.TestCase):
    def test_immediate_all_settled(self):
        self.assertTrue(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100},
                                             {"2317": "2026-11-02"}, "0050"))

    def test_immediate_someone_pending(self):
        self.assertFalse(can_park_after_build("immediate", ["2330", "2317"], {"2330": 100}, {}, "0050"))

    def test_signal_mode_never_parks(self):
        self.assertFalse(can_park_after_build("signal", ["2330"], {"2330": 100}, {"2330": "x"}, "0050"))

    def test_park_symbol_excluded_from_watchlist(self):
        # 名單含停泊標的時，它自己不算「還沒建倉」
        self.assertTrue(can_park_after_build("immediate", ["2330", "0050"], {"2330": 100}, {}, "0050"))

    def test_empty_watchlist(self):
        self.assertFalse(can_park_after_build("immediate", [], {}, {}, "0050"))


class TestStateIO(unittest.TestCase):
    def test_roundtrip_and_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "park.json"
            self.assertEqual(load_state(path)["shares"], 0)
            st = {"symbol": "0050", "shares": 100, "cost": 10_000.0, "opened": "2026-11-02",
                  "updated": "2026-11-02T13:30:00", "last_park_date": "2026-11-02"}
            save_state(st, path)
            got = load_state(path)
            self.assertEqual(got["symbol"], "0050")
            self.assertEqual(got["shares"], 100)
            self.assertAlmostEqual(got["cost"], 10_000.0)
            self.assertEqual(got["last_park_date"], "2026-11-02")

    def test_corrupt_state_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_state(path)["shares"], 0)


if __name__ == "__main__":
    unittest.main()
