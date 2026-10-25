"""測試：持倉報告顯示每檔的策略（auto 顯示「買入時鎖定的策略」）。

需求（2026-09-11 使用者）：
    持倉報告中加顯示目前股的策略；若是 auto，則顯示**買入時決定用的策略**。

資料來源：
    - 設定的策略         → `PC_<代號>` 的 `strategy` 欄位（portfolio_config）
    - auto 買入時鎖定的策略 → `logs/auto_resolved.json`（買入瞬間寫入，持有期間不變）

執行：
    python3 -m unittest discover -s test -p 'test_holdings_strategy_label.py'
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from core.live_notifications import _build_holdings_message  # noqa: E402

PORTFOLIO = {
    "3017": {"strategy": "keep_wait", "alloc": 26.7},
    "3653": {"strategy": "keep_wait", "alloc": 16.7},
    "3515": {"strategy": "auto", "alloc": 5.0},
    "2006": {"strategy": "auto", "alloc": 5.0},
    "2464": {"strategy": "auto", "alloc": 5.0},
    "3008": {"strategy": "breakout", "alloc": 5.0},
}


class _TmpCwd:
    """建立含 logs/ 的暫存工作目錄並 chdir 進去（報告用相對路徑讀檔）。"""

    def __init__(self, holdings, auto_resolved=None, alloc=None):
        self.holdings = holdings
        self.auto_resolved = auto_resolved
        self.alloc = alloc or {}

    def __enter__(self):
        self._old = os.getcwd()
        self._dir = tempfile.mkdtemp(prefix="tw_report_")
        self._tmp = tempfile.TemporaryDirectory()
        logs = Path(self._dir) / "logs"
        logs.mkdir(parents=True)
        (logs / "holdings.json").write_text(json.dumps(self.holdings))
        if self.auto_resolved is not None:
            (logs / "auto_resolved.json").write_text(json.dumps(self.auto_resolved))
        (logs / "stock_allocation.json").write_text(json.dumps(self.alloc))
        os.chdir(self._dir)
        return self._dir

    def __exit__(self, *exc):
        os.chdir(self._old)
        self._tmp.cleanup()
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)
        return False


def _build(holdings, auto_resolved=None, alloc=None, portfolio=PORTFOLIO):
    with _TmpCwd(holdings, auto_resolved, alloc):
        # 2026-09-16：報告改走 fetch_latest_closes_dated（帶價格日期）；
        # 這裡一律 mock 成「沒有市場價」，讓報告回退 CSV 最後成交價（本檔測的是策略標籤，不碰網路）
        with mock.patch("core.inst_data.fetch_latest_closes_dated", return_value={}):
            return _build_holdings_message(pd, "9.99", "🚀", "測試報告", None, portfolio)


class TestHoldingsStrategyLabel(unittest.TestCase):

    def test_non_auto_shows_plain_strategy(self):
        """一般策略直接顯示名稱。"""
        msg = _build({"3017": 94}, alloc={"3017": {"total_buy_cost": 321930, "total_buy_shares": 94}})
        self.assertIn("3017: 94股 | keep_wait", msg)

    def test_breakout_shows_plain_strategy(self):
        msg = _build({"3008": 13}, alloc={"3008": {"total_buy_cost": 96915, "total_buy_shares": 13}})
        self.assertIn("3008: 13股 | breakout", msg)

    def test_auto_shows_buy_time_locked_strategy(self):
        """auto 顯示買入瞬間鎖定的策略（不是 'auto'，也不是今天的路由結果）。"""
        msg = _build(
            {"3515": 286, "2006": 735},
            auto_resolved={"3515": "bollinger", "2006": "ma_cross"},
            alloc={
                "3515": {"total_buy_cost": 59917, "total_buy_shares": 286},
                "2006": {"total_buy_cost": 59976, "total_buy_shares": 735},
            },
        )
        self.assertIn("3515: 286股 | auto→bollinger", msg)
        self.assertIn("2006: 735股 | auto→ma_cross", msg)
        self.assertNotIn("3515: 286股 | auto\n", msg)

    def test_auto_without_lock_record_shows_placeholder(self):
        """auto 有持倉但查不到鎖定紀錄 → 顯示 auto→? （誠實標示未知）。"""
        msg = _build(
            {"2464": 100},
            auto_resolved={"3515": "bollinger"},   # 沒有 2464
            alloc={"2464": {"total_buy_cost": 19000, "total_buy_shares": 100}},
        )
        self.assertIn("2464: 100股 | auto→?", msg)

    def test_missing_auto_resolved_file_is_safe(self):
        """logs/auto_resolved.json 不存在時不可爆掉。"""
        msg = _build({"2464": 100}, auto_resolved=None,
                     alloc={"2464": {"total_buy_cost": 19000, "total_buy_shares": 100}})
        self.assertIn("2464: 100股 | auto→?", msg)

    def test_label_reflects_current_file_content(self):
        """標籤必須讀「檔案現況」——auto 賣出後 lock 會被清掉，不可快取舊值。"""
        first = _build({"3515": 10}, auto_resolved={"3515": "bollinger"},
                       alloc={"3515": {"total_buy_cost": 2100, "total_buy_shares": 10}})
        self.assertIn("auto→bollinger", first)
        second = _build({"3515": 10}, auto_resolved={},
                        alloc={"3515": {"total_buy_cost": 2100, "total_buy_shares": 10}})
        self.assertIn("auto→?", second)

    def test_symbol_absent_from_config_gets_no_label(self):
        """持倉不在 PC_ 設定裡（例如已從 .env 移除）→ 不加策略標籤，不可爆掉。"""
        msg = _build({"9999": 50}, alloc={"9999": {"total_buy_cost": 5000, "total_buy_shares": 50}})
        self.assertIn("9999: 50股\n", msg)

    def test_portfolio_config_none_does_not_crash(self):
        """未傳 portfolio_config（舊呼叫端）→ 不可爆掉。"""
        msg = _build({"3017": 94}, alloc={"3017": {"total_buy_cost": 321930, "total_buy_shares": 94}},
                     portfolio=None)
        self.assertIsNotNone(msg)
        self.assertIn("3017: 94股", msg)

    def test_zero_share_holding_is_skipped(self):
        """0 股的殘留條目不出現（維持既有行為）。"""
        msg = _build({"3017": 94, "6213": 0}, alloc={"3017": {"total_buy_cost": 321930, "total_buy_shares": 94}})
        self.assertNotIn("6213", msg)


if __name__ == "__main__":
    unittest.main()
