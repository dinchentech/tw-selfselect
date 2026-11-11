#!/usr/bin/env python
"""停泊「看得見」的回歸測試（2026-11-05，v1.1.27）。

## 背景

使用者問「沒看過停泊 0050 的通知，停泊的話 TG 會通知嗎？」——答案是「成交才通知」，
而那次壞掉四天沒人發現，正是因為：**成功才有聲音、失敗與「沒做」全靜默**，
而且收盤／睡前報告只列 `.env` 裡的股票，**完全沒有停泊欄位**。

本檔釘住三件事：
1. 收盤／睡前持倉報告必須有 `🅿️ 停泊（閒置資金）` 區塊。
2. 持股全部清空、但停泊部位還在時，**仍然要發報告**（否則錢全押在 0050 這件事無人知曉）。
3. 主程式每天要有一則「停泊狀態」TG（成功／失敗／沒做＋原因），且每天只一則（`report_due`）。
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

import pandas as pd  # noqa: E402

from core.live_notifications import _build_holdings_message  # noqa: E402


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")


class _TmpCwd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.getcwd()
        os.chdir(self._tmp.name)
        (Path("logs")).mkdir()

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()


class TestReportIncludesPark(_TmpCwd):

    def test_park_section_present_when_parked(self):
        _write(Path("logs/holdings.json"), {"2357": 93})
        _write(Path("logs/stock_allocation.json"),
               {"2357": {"total_buy_cost": 798 * 93, "total_buy_shares": 93}})
        pd.DataFrame([{"timestamp": "2026-08-03 09:00:00", "symbol": "2357", "signal": "BUY",
                       "price": 798.0, "quantity": 93, "action": "BUY"}]).to_csv(
            Path("logs/performance.csv"), index=False)
        _write(Path("logs/park_position.json"),
               {"symbol": "0050", "shares": 1000, "cost": 97150.0, "updated": "2026-11-05T13:30:00"})
        msg = _build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告", 1000000, {"2357": {"strategy": "auto", "alloc": 25}})
        self.assertIsNotNone(msg)
        self.assertIn("🅿️ 停泊（閒置資金）", msg)
        self.assertIn("0050 1,000 股", msg)
        self.assertIn("均價 97.15", msg)

    def test_no_park_section_reason_when_flat(self):
        _write(Path("logs/holdings.json"), {"2357": 93})
        _write(Path("logs/stock_allocation.json"),
               {"2357": {"total_buy_cost": 798 * 93, "total_buy_shares": 93}})
        pd.DataFrame([{"timestamp": "2026-08-03 09:00:00", "symbol": "2357", "signal": "BUY",
                       "price": 798.0, "quantity": 93, "action": "BUY"}]).to_csv(
            Path("logs/performance.csv"), index=False)
        msg = _build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告", 1000000, {"2357": {"strategy": "auto", "alloc": 25}})
        self.assertIn("🅿️ 停泊（閒置資金）", msg)
        self.assertIn("無停泊部位", msg)

    def test_message_still_sent_when_holdings_empty_but_parked(self):
        """持股全清空、錢全押 0050 ⇒ 以前 return None（整份報告不發），現在必須發。"""
        _write(Path("logs/holdings.json"), {})
        _write(Path("logs/stock_allocation.json"), {})
        pd.DataFrame([{"timestamp": "2026-08-03 09:00:00", "symbol": "2357", "signal": "SELL",
                       "price": 800.0, "quantity": 93, "action": "SELL"}]).to_csv(
            Path("logs/performance.csv"), index=False)
        _write(Path("logs/park_position.json"),
               {"symbol": "0050", "shares": 500, "cost": 48000.0})
        msg = _build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告")
        self.assertIsNotNone(msg, "只剩停泊部位時仍要發報告")
        self.assertIn("0050 500 股", msg)

    def test_no_message_when_nothing_at_all(self):
        _write(Path("logs/holdings.json"), {})
        _write(Path("logs/stock_allocation.json"), {})
        self.assertIsNone(_build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告"))


class TestReportShowsShouldVsActual(_TmpCwd):

    def _base(self):
        _write(Path("logs/holdings.json"), {"2357": 93})
        _write(Path("logs/stock_allocation.json"),
               {"2357": {"total_buy_cost": 798 * 93, "total_buy_shares": 93}})
        pd.DataFrame([{"timestamp": "2026-08-03 09:00:00", "symbol": "2357", "signal": "BUY",
                       "price": 798.0, "quantity": 93, "action": "BUY"}]).to_csv(
            Path("logs/performance.csv"), index=False)

    def test_report_shows_plan_lines(self):
        from datetime import datetime
        self._base()
        today = datetime.now().strftime("%Y-%m-%d")
        _write(Path("logs/park_plan.json"),
               {"date": today, "symbol": "0050", "idle": 305689.0, "cash": 12823.0,
                "cap": 12823.0, "price": 97.15, "target_shares": 131, "actual_shares": 0,
                "status": "SKIP", "reason": "可用現金 NT$12,823 不足", "unknown": False})
        msg = _build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告", 1000000,
                                      {"2357": {"strategy": "auto", "alloc": 25}})
        self.assertIn("應該停泊", msg)
        self.assertIn("實際停泊", msg)
        self.assertIn("305,689", msg)
        self.assertIn("12,823", msg)

    def test_stale_plan_is_ignored(self):
        self._base()
        _write(Path("logs/park_plan.json"),
               {"date": "2020-01-01", "idle": 1.0, "cash": 1.0, "cap": 1.0, "price": 1.0,
                "target_shares": 0, "actual_shares": 0, "status": "SKIP", "reason": "舊資料"})
        msg = _build_holdings_message(pd, "1.1.27", "📋", "收盤持倉報告", 1000000,
                                      {"2357": {"strategy": "auto", "alloc": 25}})
        self.assertNotIn("舊資料", msg, "不是今天的計畫不可顯示（避免誤導）")


class TestDailyParkStatusWired(unittest.TestCase):

    def _src(self):
        return (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")

    def test_daily_status_is_once_per_day(self):
        """每天只發一則；刻意**不用** `report_due`（13:31+ 區塊的守門測試要求剛好 2 次）。"""
        src = self._src()
        self.assertIn("'park_status'", src)
        self.assertIn("_report_state.get('park_status') != today_str", src)
        self.assertIn("_report_state['park_status'] = today_str", src)

    def test_status_uses_should_vs_actual(self):
        src = self._src()
        self.assertIn("format_plan_vs_actual", src, "停泊狀態必須分『應該停泊』與『實際停泊』")
        self.assertIn("logs/park_plan.json", src, "應該/實際的計算結果必須落地，報告才讀得到")

    def test_park_events_recorded_for_all_outcomes(self):
        src = self._src()
        self.assertIn("_park_events", src)
        for key in ("'action': 'BUY'", "'action': 'FAIL'", "'action': 'SKIP'"):
            self.assertIn(key, src, f"停泊事件必須記錄 {key}（否則『沒做』還是靜默的）")


if __name__ == "__main__":
    unittest.main()
