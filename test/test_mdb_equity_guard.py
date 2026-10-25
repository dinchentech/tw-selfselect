"""回歸測試：MIN_DRAW_BACK 股災防護的 equity 口徑 + 選股端守門（2026-09-13）

⚠️ 重要更正（2026-09-13）：本檔第一版曾斷言 `compute_equity` 把持股市值「多算一次」，
   並要求改成「（TC − 成本）+ 淨現金流 + 市值」。**那個判斷是錯的，已回退。**
   根因：把 `net_cash_flow()`（Σ賣 − Σ買 = −956,101）誤讀成儀表板的「總已實現損益」
   （FIFO 口徑 = +5,515）。實際上它是**淨現金流**，身分式為
   `現金 = TOTAL_CAPITAL + 淨現金流`，因此
   `TC + 淨現金流 + 持股市值 = 現金 + 持股市值 = 總資產` —— **原公式正確**。
   本檔現在用最簡算例把這個身分式釘死（見 TestEquityIdentity）。

真正修掉的是「讓防護失效」的缺陷：
    - `manual_rotation_pick.py` 雖有呼叫檢查，但傳 `broker=None` → `None.get_current_price`
      → AttributeError → **永遠 fail-open**（形同裝飾）。
    - 直接跑 `stock_selector_grid.py --recommend` 則完全沒有檢查。
    → 修法：把檢查搬進**選股程式本體**（bot 與手動工具都經過它），
      並改用選股程式**自己就有的價格**（不需 broker）。見 TestMdbGuardEntry / TestSelectorGuardWiring。
    另：路徑改為錨定專案根目錄（不再依賴 CWD）。

執行：
    .venv/bin/python -m unittest discover -s test -p 'test_mdb_equity_guard.py'
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.drawdown_guard as rh  # noqa: E402


def _write_csv(path, rows):
    """fixture 一律寫滿 8 欄，且 `cost=0`：
    本檔測的是「equity = 現金 + 持股市值」的**恆等式**，不該被手續費干擾
    （費用行為由 test_fees.py 與下面的 test_net_cash_flow_deducts_costs 專測）。
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("timestamp,symbol,signal,price,quantity,action,exclude_daily,cost\n")
        for r in rows:
            f.write(r + ",0,0\n")


class TestEquityIdentity(unittest.TestCase):
    """equity = 現金 + 持股市值；而 現金 = TOTAL_CAPITAL + 淨現金流。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self._tmp.name, "perf.csv")

    def tearDown(self):
        self._tmp.cleanup()

    def test_net_cash_flow_is_sells_minus_buys(self):
        _write_csv(self.csv, ["2026-01-01,2330,1,100,100,BUY",
                              "2026-02-01,2330,-1,120,50,SELL"])
        # 120*50 − 100*100 = 6000 − 10000
        self.assertEqual(rh.net_cash_flow(self.csv), -4000.0)

    def test_net_cash_flow_deducts_recorded_cost(self):
        """2026-09-17 起：淨現金流要扣交易成本（CSV 的 `cost` 欄）。"""
        _write_csv(self.csv, ["2026-01-01,2330,1,100,100,BUY,0,143"])
        self.assertEqual(rh.net_cash_flow(self.csv), -10_143.0)

    def test_unrecorded_cost_falls_back_to_rate(self):
        """舊列沒有 cost 欄 → 以現行費率推定。

        10,000 元 × 0.1425% = 14 元 < 最低手續費 20 元 → 收 20（不吃費率的帳）。
        期望值用 `fees.buy_fee()` 算，避免把費率硬編進測試（改 .env 折數就不會壞）。
        """
        from core import fees
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write("timestamp,symbol,signal,price,quantity,action\n")
            f.write("2026-01-01,2330,1,100,100,BUY\n")
        self.assertEqual(rh.net_cash_flow(self.csv), -10_000.0 - fees.buy_fee(10_000))

    def test_old_name_still_works(self):
        _write_csv(self.csv, ["2026-01-01,2330,1,100,100,BUY"])
        self.assertEqual(rh.realized_pnl(self.csv), -10000.0)

    def test_equity_before_any_trade_equals_capital(self):
        self.assertEqual(rh.compute_equity(1_000_000, {}, {}, self.csv), 1_000_000.0)

    def test_equity_is_cash_plus_holdings_worked_example(self):
        """最簡算例（釘死身分式）：
        本金 1000；買 10 股 @10 → 現金 900、市值 100；
        賣 4 股 @12 → 現金 948、剩 6 股市值 72 → 總資產 1020。
        """
        _write_csv(self.csv, ["2026-01-01,2330,1,10,10,BUY",
                              "2026-02-01,2330,-1,12,4,SELL"])
        eq = rh.compute_equity(1000, {"2330": 6}, {"2330": 12.0}, self.csv)
        self.assertEqual(eq, 948 + 72)          # 淨現金流 −52 → 現金 948
        self.assertEqual(eq, 1020.0)

    def test_no_cost_basis_subtraction(self):
        """反回歸：不可再引入「扣掉成本基礎」的錯誤修法。

        本金 1000、買 10 股 @10（CSV 有記錄）、市價仍 10：
        正確總資產 = 1000（現金 900 + 市值 100）；錯誤版本會得到 900。
        """
        _write_csv(self.csv, ["2026-01-01,2330,1,10,10,BUY"])
        eq = rh.compute_equity(1000, {"2330": 10}, {"2330": 10.0}, self.csv)
        self.assertEqual(eq, 1000.0)
        self.assertNotEqual(eq, 900.0)

    def test_missing_csv_treated_as_zero_cash_flow(self):
        self.assertEqual(rh.net_cash_flow("/nonexistent/perf.csv"), 0.0)
        self.assertEqual(rh.compute_equity(500, {"2330": 1}, {"2330": 100.0},
                                           "/nonexistent/perf.csv"), 600.0)


class TestDrawdownDetection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.perf = os.path.join(d, "perf.csv")
        # 本金 1,000,000 買 100 股 @8,000 → 現金 200,000
        _write_csv(self.perf, ["2026-01-01,2330,1,8000,100,BUY"])
        self.peak = os.path.join(d, "equity_peak.json")
        self.hold = os.path.join(d, "rotation_hold.json")
        self.TC = 1_000_000
        self.holdings = {"2330": 100}

    def tearDown(self):
        self._tmp.cleanup()

    def _check(self, price, min_drawback=30):
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold):
            return rh.check_drawdown_prices(min_drawback, self.TC, self.holdings,
                                                 {"2330": price}, "2026-09-30",
                                                 performance_csv=self.perf)

    def test_true_thirty_one_percent_drawdown_triggers_hold(self):
        # 市價 8,000 → 總資產 = 200,000 + 800,000 = 1,000,000（＝本金，無損益）
        hold0, dd0 = self._check(8_000.0)
        self.assertFalse(hold0, "首次執行只初始化峰值，不觸發")
        self.assertAlmostEqual(dd0, 0.0)
        self.assertEqual(json.load(open(self.peak))["peak"], 1_000_000)

        # 市價 4,900 → 總資產 = 200,000 + 490,000 = 690,000（真實 −31%）
        hold, dd = self._check(4_900.0)
        self.assertAlmostEqual(dd, 690_000 / 1_000_000 - 1, places=6)
        self.assertTrue(hold, "真實 −31% 回撤必須觸發 MIN_DRAW_BACK=30")

    def test_under_threshold_does_not_hold(self):
        self._check(8_000.0)
        hold, dd = self._check(7_900.0)          # 總資產 990,000 → −1%
        self.assertFalse(hold)
        self.assertGreater(dd, -0.30)

    def test_extend_once_then_force(self):
        """已延長一季仍超標 → 強制換股（狀態機）。"""
        self._check(8_000.0)
        hold1, _ = self._check(4_900.0)
        self.assertTrue(hold1)
        hold2, _ = self._check(4_900.0)
        self.assertFalse(hold2, "第二次仍超標 → 強制換股")


class TestPricesBasedCheck(unittest.TestCase):
    """不依賴 broker 的檢查函式（B2 的基礎）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.perf = os.path.join(self._tmp.name, "perf.csv")
        _write_csv(self.perf, [])
        self.peak = os.path.join(self._tmp.name, "peak.json")
        self.hold = os.path.join(self._tmp.name, "hold.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_prices_based_check_works_without_broker(self):
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold):
            hold, dd = rh.check_drawdown_prices(
                30, 1_000_000, {"2330": 100}, {"2330": 50.0},
                "2026-09-30", performance_csv=self.perf)
        self.assertFalse(hold)
        self.assertIsNotNone(dd)

    def test_missing_price_fails_open(self):
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold):
            hold, dd = rh.check_drawdown_prices(
                30, 1_000_000, {"2330": 100}, {}, "2026-09-30", performance_csv=self.perf)
        self.assertFalse(hold)
        self.assertIsNone(dd)

    def test_broker_none_is_safe_not_crash(self):
        """broker=None 不應拋 AttributeError（舊版 manual_rotation_pick 的 bug）。"""
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold):
            hold, dd = rh.check_drawdown(30, 1_000_000, None, {"2330": 100},
                                              "2026-09-30", performance_csv=self.perf)
        self.assertFalse(hold)
        self.assertIsNone(dd, "無 broker 且無價格 → fail-open 並回 None")

    def test_broker_path_uses_total_assets(self):
        class _B:
            def get_current_price(self, sym):
                return 10_000.0
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold):
            hold, dd = rh.check_drawdown(30, 1_000_000, _B(), {"2330": 100},
                                              "2026-09-30", performance_csv=self.perf)
        # equity = 1,000,000 + 0（無績效檔） + 1,000,000 = 2,000,000 → 首次初始化峰值 → dd=0
        self.assertFalse(hold)
        self.assertAlmostEqual(dd, 0.0)
        self.assertEqual(json.load(open(self.peak))["peak"], 2_000_000)


class TestMdbGuardEntry(unittest.TestCase):
    """B2：選股端守門的共用進入點（讀 .env + logs，再交給 check_drawdown_prices）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.env = os.path.join(d, ".env")
        self.perf = os.path.join(d, "perf.csv")
        _write_csv(self.perf, ["2026-01-01,2330,1,8000,100,BUY"])   # 支出 800,000
        self.peak = os.path.join(d, "peak.json")
        self.hold_state = os.path.join(d, "hold.json")
        self.holdings_path = os.path.join(d, "holdings.json")
        json.dump({"2330": 100}, open(self.holdings_path, "w"))

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, min_drawback, total_capital=1000000):
        with open(self.env, "w", encoding="utf-8") as f:
            f.write(f"TOTAL_CAPITAL={total_capital}   # 行內註解必須被剝除\n")
            f.write(f"MIN_DRAW_BACK={min_drawback}   # 同上\n")

    def _guard(self, price, **kw):
        """price=None → 空價格表（測 fallback_loader 用）。"""
        price_map = kw.pop("price_map", None)
        if price_map is None:
            price_map = {"2330": price} if price is not None else {}
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold_state):
            return rh.mdb_guard(price_map, "2026-09-30",
                                env_path=self.env, holdings_path=self.holdings_path,
                                perf_path=self.perf, **kw)

    def test_env_parsing_strips_inline_comment(self):
        self._env(30)
        self.assertEqual(rh.load_env_value("MIN_DRAW_BACK", "0", self.env), "30")
        self.assertEqual(rh.load_env_value("TOTAL_CAPITAL", "0", self.env), "1000000")

    def test_disabled_when_zero(self):
        self._env(0)
        hold, dd = self._guard(4900.0)
        self.assertFalse(hold)
        self.assertIsNone(dd)
        self.assertFalse(os.path.exists(self.peak), "停用時不應寫狀態檔")

    def test_deep_drawdown_blocks_selection(self):
        """關鍵情境：總資產 1,000,000 → 690,000（真實 −31%）→ 必須擋下換股。"""
        self._env(30)
        hold0, _ = self._guard(8000.0)          # 現金 200,000 + 市值 800,000 = 1,000,000
        self.assertFalse(hold0)
        hold, dd = self._guard(4900.0)
        self.assertTrue(hold, "選股端守門必須擋下這筆換股")
        self.assertAlmostEqual(dd, 690000 / 1000000 - 1, places=6)

    def test_missing_price_fails_open(self):
        self._env(30)
        hold, dd = rh.mdb_guard({}, "2026-09-30", env_path=self.env,
                                holdings_path=self.holdings_path,
                                perf_path=self.perf, fallback_loader=None)
        self.assertFalse(hold)
        self.assertIsNone(dd)

    def test_fallback_loader_supplies_price(self):
        """持倉不在候選池（價格表沒有）→ 用 fallback_loader 補價。"""
        self._env(30)

        class _Series:
            def __init__(self, v):
                self._v = v

            @property
            def iloc(self):
                return self

            def __getitem__(self, i):
                return self._v

        class _DF:
            """最小介面：只支援 df["close"].iloc[-1] 與 df.empty。"""
            empty = False

            def __getitem__(self, key):
                return _Series(8000.0)

        # 走 _guard helper → PEAK_FILE/HOLD_FILE 被隔離到 tmp，
        # 否則會讀到專案 logs/equity_peak.json（2026-09-14 就是這樣壞的：
        # 一次真實預覽寫入峰值後，本測試在全套裡失敗，但在單獨跑時剛好過）。
        hold, dd = self._guard(None, price_map={}, fallback_loader=lambda s: _DF())
        self.assertFalse(hold)
        self.assertIsNotNone(dd)

    def test_missing_env_file_is_safe(self):
        # 同樣走 _guard（隔離狀態檔）；env_path 另外指定成不存在的檔案
        with mock.patch.object(rh, "PEAK_FILE", self.peak), \
             mock.patch.object(rh, "HOLD_FILE", self.hold_state):
            hold, dd = rh.mdb_guard({"2330": 100.0}, "2026-09-30",
                                    env_path=os.path.join(self._tmp.name, "nope.env"),
                                    holdings_path=self.holdings_path,
                                    perf_path=self.perf)
        self.assertFalse(hold)
        self.assertIsNone(dd)


class TestSelectorGuardWiring(unittest.TestCase):
    """接線守門：檢查必須真的掛在選股程式的 --recommend 路徑上。

    行為已由 TestMdbGuardEntry 覆蓋；這裡只防「有人日後把守門拿掉/搬走」。
    （選股程式 import 時會抓 FinMind 資料，故不直接 import，改檢查原始碼。）
    """

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.src = open(os.path.join(root, "scripts", "stock_selector_grid.py"),
                        encoding="utf-8").read()






if __name__ == "__main__":
    unittest.main()
