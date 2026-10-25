"""測試：「近 50 筆交易」表格要包含買進（C，2026-09-11）。

需求（使用者）：
    一張叫「近 50 筆交易」的表卻只看得到賣出，不一致 → 買進也要列進去。

設計原則（不可妥協）：
    - `compute_pnl()` 的 FIFO 已實現損益 **完全不動**（那是被信任的數字）。
    - 統計用的 `pnl_list`（交易次數／勝率／總損益）**不可混入買進**，
      否則「交易次數」會暴增、勝率分母被汙染。
    - 只有「顯示用」的逐筆清單才合併買進。

執行：
    python3 -m unittest discover -s test -p 'test_dashboard_buy_rows.py'
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import scripts.generate_dashboard as gd  # noqa: E402


def _mk_df(rows, cost=0.0):
    """rows: [(timestamp, symbol, price, qty, action, group)]

    `cost` 預設 0：本檔測的是「清單／統計的組合邏輯」，費用會浮動（依 .env 費率）
    會讓斷言不穩；費用是否正確流進損益另由 `TestFeesFlowIntoPnl` 專測。
    """
    return pd.DataFrame([
        {
            "timestamp": pd.Timestamp(ts),
            "symbol": sym,
            "signal": 1 if act == "BUY" else -1,
            "price": float(price),
            "quantity": int(qty),
            "action": act,
            "exclude_daily": 0.0,
            "cost": float(cost),
            "group": grp,
        }
        for ts, sym, price, qty, act, grp in rows
    ])


# 2026-09-11 的真實情境：三檔舊持倉 + 今天兩筆買進。
# 順序刻意照 performance.csv 的樣子（依時間 append）—— build_trade_log 沿用 CSV 順序，
# 而 FIFO 的累積水位也依賴這個順序。
# （3008 需先有買進，FIFO 才配得到，否則已實現損益為 0）
_REALISH = [
    ("2026-08-01 09:00:00", "3008", 7455, 13, "BUY", 1),
    ("2026-09-01 09:00:00", "3653", 5156, 10, "BUY", 1),
    ("2026-09-09 10:42:00", "3008", 6795, 13, "SELL", 1),
    ("2026-09-11 09:33:26", "3515", 209.5, 286, "BUY", 1),
    ("2026-09-11 09:33:45", "2006", 81.6, 735, "BUY", 1),
]

# 上面資料經 build_trade_log 後的預期順序（沿用 CSV 順序）
_EXPECTED_ACTIONS = ["BUY", "BUY", "SELL", "BUY", "BUY"]
_EXPECTED_SYMBOLS = ["3008", "3653", "3008", "3515", "2006"]


class TestBuildTradeLog(unittest.TestCase):

    def test_includes_buys_and_sells_in_chronological_order(self):
        df = _mk_df(_REALISH)
        pnl = gd.compute_pnl(df)
        log = gd.build_trade_log(df, pnl)
        self.assertEqual([r["action"] for r in log], _EXPECTED_ACTIONS)
        self.assertEqual([r["symbol"] for r in log], _EXPECTED_SYMBOLS)
        # 時間需遞增
        keys = [r["date"] + r["time"] for r in log]
        self.assertEqual(keys, sorted(keys))

    def test_buy_rows_have_no_realized_pnl(self):
        df = _mk_df(_REALISH)
        log = gd.build_trade_log(df, gd.compute_pnl(df))
        for r in log:
            if r["action"] == "BUY":
                self.assertIsNone(r["pnl"], "買進沒有已實現損益，應為 None")
                self.assertIsNone(r["pnl_pct"])
            else:
                self.assertIsNotNone(r["pnl"])

    def test_sell_rows_carry_compute_pnl_values(self):
        """賣出列的損益必須與 compute_pnl 完全一致（不可自己重算 FIFO）。"""
        df = _mk_df(_REALISH)
        pnl = gd.compute_pnl(df)
        log = gd.build_trade_log(df, pnl)
        sells = [r for r in log if r["action"] == "SELL"]
        self.assertEqual(len(sells), len(pnl))
        for got, want in zip(sells, pnl):
            self.assertEqual(got["pnl"], want["pnl"])
            self.assertEqual(got["pnl_pct"], want["pnl_pct"])
            self.assertEqual(got["cumulative"], want["cumulative"])
            self.assertEqual(got["qty"], want["qty"])

    def test_buy_rows_carry_running_realized_cumulative(self):
        """買進列的累積損益＝當下最新的已實現累積（買進本身不改變它）。"""
        df = _mk_df(_REALISH)
        log = gd.build_trade_log(df, gd.compute_pnl(df))
        by_key = {(r["symbol"], r["action"], r["date"]): r for r in log}
        # 08-01 的買進之前還沒有任何已實現損益
        self.assertEqual(by_key[("3008", "BUY", "2026-08-01")]["cumulative"], 0.0)
        # 09-09 賣出後累積到 -8,580
        self.assertEqual(by_key[("3008", "SELL", "2026-09-09")]["cumulative"], -8580.0)
        # 今天買進時，累積損益仍停在 09-09 賣出後的水位
        self.assertEqual(by_key[("3515", "BUY", "2026-09-11")]["cumulative"], -8580.0)
        self.assertEqual(by_key[("2006", "BUY", "2026-09-11")]["cumulative"], -8580.0)

    def test_price_and_qty_are_numeric(self):
        df = _mk_df(_REALISH)
        log = gd.build_trade_log(df, gd.compute_pnl(df))
        for r in log:
            self.assertIsInstance(r["price"], float)
            self.assertIsInstance(r["qty"], int)

    def test_empty_df_returns_empty_log(self):
        self.assertEqual(gd.build_trade_log(pd.DataFrame(), []), [])

    def test_sell_without_matching_pnl_entry_is_safe(self):
        """賣出但 compute_pnl 沒給對應項目（配不到 lot）→ 不可爆掉，標成 None。"""
        df = _mk_df([("2026-09-11 10:00:00", "9999", 100, 10, "SELL", 1)])
        log = gd.build_trade_log(df, [])   # 故意給空的 pnl_list
        self.assertEqual(len(log), 1)
        self.assertIsNone(log[0]["pnl"])


class TestFeesFlowIntoPnl(unittest.TestCase):
    """2026-09-17：儀表板損益必須是**淨額**（扣手續費＋證交稅）。

    歷史事實：同一批真實交易毛額 +5,516，含費用後為 −6,439；
    本測試用小型 fixture 釘住「費用會反映到顯示的損益與累積」。
    """

    def test_recorded_cost_reduces_pnl_and_cumulative(self):
        rows = [("2026-08-01 09:00:00", "3008", 100.0, 10, "BUY", 1),
                ("2026-09-09 10:42:00", "3008", 200.0, 10, "SELL", 1)]
        gross = gd.compute_pnl(_mk_df(rows))[0]["pnl"]
        self.assertEqual(gross, 1000.0)
        # 買進費用 20 + 賣出費用（手續費 20 + 證交稅 6）= 46
        net = gd.compute_pnl(_mk_df(rows, cost=10.0))
        # 買 10 股成本基礎 +10、賣出成本 10 → 損益 1000 − 10 − 10 = 980
        self.assertEqual(net[0]["pnl"], 980.0)
        self.assertEqual(net[0]["cumulative"], 980.0)
        self.assertLess(net[0]["pnl"], gross)

    def test_pnl_pct_is_net(self):
        rows = [("2026-08-01 09:00:00", "3008", 100.0, 10, "BUY", 1),
                ("2026-09-09 10:42:00", "3008", 110.0, 10, "SELL", 1)]
        net = gd.compute_pnl(_mk_df(rows, cost=5.0))[0]
        # 成本基礎 (1000+5)/10 = 100.5；賣出成本 5 → 損益 95 − 5 = 95... 實算：
        # (110−100.5)*10 − 5 = 90
        self.assertEqual(net["pnl"], 90.0)
        self.assertAlmostEqual(net["pnl_pct"], 90.0 / 1005.0 * 100, places=1)


class TestBooksWarning(unittest.TestCase):
    """⚠️ 帳務不一致必須在儀表板現形（2026-09-17）。

    起因：使用者發現「這些股在未平倉區也沒顯示」—— 因為那區只認 holdings.json，
    而 2395/3665 各 36 股只在 performance.csv 裡（幽靈部位），
    不但看不到，還永遠不會被自動賣出。
    """

    def _fake(self, **kw):
        base = {"ok": True, "phantom": {}, "ghost": {}, "unmatched": {},
                "memory_drift": {}, "csv_schema": {"ok": True}}
        base.update(kw)
        return base

    def test_clean_books_render_nothing(self):
        with mock.patch("core.books.audit_books", return_value=self._fake()):
            self.assertEqual(gd._books_warning(), "")

    def test_phantom_positions_are_shown_with_shares(self):
        with mock.patch("core.books.audit_books",
                        return_value=self._fake(ok=False, phantom={"2395": 36, "3665": 36})):
            out = gd._books_warning()
        self.assertIn("帳務不一致", out)
        self.assertIn("2395 × 36 股", out)
        self.assertIn("3665 × 36 股", out)
        self.assertIn("永遠不會被自動賣出", out)

    def test_memory_drift_is_shown(self):
        with mock.patch("core.books.audit_books",
                        return_value=self._fake(ok=False, memory_drift={"2006": [0, 735]})):
            out = gd._books_warning()
        self.assertIn("2006", out)
        self.assertIn("記憶體與磁碟", out)

    def test_schema_drift_is_shown(self):
        with mock.patch("core.books.audit_books",
                        return_value=self._fake(ok=False,
                                                csv_schema={"ok": False, "header_cols": 7,
                                                            "drift_rows": 15})):
            out = gd._books_warning()
        self.assertIn("migrate_performance_csv_schema", out)

    def test_failure_never_breaks_the_dashboard(self):
        with mock.patch("core.books.audit_books", side_effect=RuntimeError("boom")):
            self.assertEqual(gd._books_warning(), "")


class TestStatsNotPolluted(unittest.TestCase):

    def test_total_trades_counts_only_closed_trades(self):
        """交易次數＝已平倉次數，不可因為買進被算進去。"""
        df = _mk_df(_REALISH)
        pnl = gd.compute_pnl(df)
        stats = gd.build_group_stats(pnl, df)
        self.assertEqual(stats["total_trades"], 1, "4 筆交易中只有 1 筆是已平倉")
        self.assertEqual(stats["total_pnl"], -8580.0)

    def test_symbol_stats_buys_and_sells_still_reported(self):
        df = _mk_df(_REALISH)
        stats = gd.compute_symbol_stats(df, gd.compute_pnl(df))
        by_sym = {s["symbol"]: s for s in stats}
        self.assertEqual(by_sym["3515"]["buys"], 1)
        self.assertEqual(by_sym["3515"]["sells"], 0)
        self.assertEqual(by_sym["3515"]["trades"], 0, "沒有平倉 → 交易次數 0")


class TestRenderedHtml(unittest.TestCase):

    def _build(self, rows):
        df = _mk_df(rows)
        with mock.patch.object(gd, "load_holdings", return_value={}), \
             mock.patch.object(gd, "load_stock_allocation", return_value={}), \
             mock.patch.object(gd, "fetch_current_prices", return_value={}), \
             mock.patch.object(gd, "load_group2_json_summary", return_value={}):
            return gd.build_html(df)

    def test_buy_row_is_rendered(self):
        html = self._build(_REALISH)
        self.assertIn('<span class="act buy">買</span>', html)
        self.assertIn('<span class="act sell">賣</span>', html)
        # 3515 是買進，不該出現損益數字
        self.assertIn("3515", html)

    def test_buy_row_shows_dash_for_pnl(self):
        html = self._build(_REALISH)
        self.assertIn('<td class="muted">—</td>', html)

    def test_action_column_header_present(self):
        html = self._build(_REALISH)
        self.assertIn("<th>動作</th>", html)

    def test_more_than_50_trades_is_capped_at_50(self):
        rows = []
        for i in range(60):
            rows.append((f"2026-08-{(i % 28) + 1:02d} 09:00:00", "2330", 100 + i, 1, "BUY", 1))
        html = self._build(rows)
        self.assertEqual(html.count('<span class="act buy">買</span>'), 50)


if __name__ == "__main__":
    unittest.main()
