"""停泊帳對帳（2026-11-06，v1.1.35）：帳本 × 稽核檔重播 × 券商庫存。

## 為什麼要有這支

2026-11-06 實盤：停泊 0050 計畫 4,122 股、券商整股只送 4,000 股，帳面記 4,122 股
（多 122 股／NT$11,291）。這筆帳沒有任何工具會發現，因為：
- 停泊交易寫 `logs/park_trades.jsonl`，**不在** `performance.csv`
- `scripts/reconcile_broker_books.py` 與 `scripts/broker_shortfall_repair.py` 都只讀 `performance.csv`

⇒ 停泊是唯一沒有自動對帳的記帳路徑。本檢查補上這道防護，且**只告警、不自動改帳**
（停泊不影響下單股數，只影響權益與現金估算；自動改錯比留著人工確認更危險）。

## 三種判定

| status | 條件 | 行為 |
|---|---|---|
| `ok` | 帳本＝稽核檔重播（＝券商庫存，或券商不足以判斷但不衝突） | 不通知 |
| `ledger_mismatch` | **帳本 ≠ 稽核檔重播** ⇒ 我們自己的帳壞了 | TG 告警 |
| `broker_mismatch` | 帳本 ≠ 券商庫存，**且當日有停泊成交**（此時庫存可信） | TG 告警 |
| `broker_unverified` | 帳本 ≠ 券商庫存，但當日沒成交 | 只寫 log（庫存 API 只回當日未交割 ⇒ 不足以判定） |
"""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.park_asset import check_position, replay_shares, traded_on   # noqa: E402

BUY_4122 = {"ts": "2026-11-06T13:25:58", "action": "BUY", "symbol": "0050",
            "shares": 4122, "price": 92.55}
REPAIR_4000 = {"action": "REPAIR", "symbol": "0050", "shares": 4000, "price": 92.55}
SELL_1000 = {"ts": "2026-11-09T10:00:00", "action": "SELL", "symbol": "0050",
             "shares": 1000, "price": 93.0}


class TestReplayShares(unittest.TestCase):
    """稽核檔重播：BUY 加、SELL 減、REPAIR 覆寫（絕對值）、其他忽略。"""

    def test_buy_and_sell(self):
        self.assertEqual(replay_shares([]), 0)
        self.assertEqual(replay_shares([BUY_4122]), 4122)
        self.assertEqual(replay_shares([BUY_4122, SELL_1000]), 3122)

    def test_repair_overrides_absolute(self):
        """人工修帳（REPAIR）之後，重播必須等於修完的值，否則對帳永遠紅。"""
        self.assertEqual(replay_shares([BUY_4122, REPAIR_4000]), 4000)
        self.assertEqual(replay_shares([BUY_4122, REPAIR_4000, SELL_1000]), 3000)

    def test_unknown_action_and_broken_rows_ignored(self):
        rows = [BUY_4122, {"action": "SKIP"}, {"action": "FAIL", "shares": 999},
                {"action": "BUY", "shares": "abc"}, {"action": None}, "not-a-dict"]
        self.assertEqual(replay_shares(rows), 4122)

    def test_never_negative(self):
        self.assertEqual(replay_shares([SELL_1000]), 0)

    def test_string_shares_and_thousands_separator(self):
        self.assertEqual(replay_shares([{"action": "BUY", "shares": "4,000"}]), 4000)


class TestTradedOn(unittest.TestCase):

    def test_true_only_for_buy_sell_on_that_date(self):
        self.assertTrue(traded_on([BUY_4122], "2026-11-06", "0050"))
        self.assertFalse(traded_on([BUY_4122], "2026-11-07", "0050"))
        self.assertFalse(traded_on([REPAIR_4000], "2026-11-06", "0050"))

    def test_other_symbol_does_not_count(self):
        self.assertFalse(traded_on([BUY_4122], "2026-11-06", "0056"))

    def test_empty_date_is_false(self):
        self.assertFalse(traded_on([BUY_4122], "", "0050"))


class TestCheckPosition(unittest.TestCase):

    def test_ok_when_all_three_agree(self):
        r = check_position(4000, [BUY_4122, REPAIR_4000], broker_shares=4000, traded_today=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["diff"], 0)

    def test_incident_4122_vs_4000_is_caught(self):
        """2026-11-06 事故回歸：帳本 4,122、券商 4,000、當日有成交 ⇒ 必須告警。"""
        r = check_position(4122, [BUY_4122], broker_shares=4000, traded_today=True)
        self.assertEqual(r["status"], "broker_mismatch")
        self.assertEqual(r["broker"], 4000)
        self.assertIn("122", r["note"])

    def test_ledger_mismatch_when_replay_disagrees(self):
        """帳本被人工改過／寫檔中斷（帳本 4,000 但稽核檔只有 BUY 4122 且沒有 REPAIR）⇒ 我們自己的帳壞了。"""
        r = check_position(4000, [BUY_4122], broker_shares=4000, traded_today=True)
        self.assertEqual(r["status"], "ledger_mismatch")
        self.assertIn("重播", r["note"])

    def test_broker_unverified_does_not_alert_when_no_trade_today(self):
        """庫存 API 只回當日未交割部位 ⇒ 沒成交那天「券商 0 股」不算證據，不能告警。"""
        r = check_position(4000, [BUY_4122, REPAIR_4000], broker_shares=0, traded_today=False)
        self.assertEqual(r["status"], "broker_unverified")
        self.assertIn("僅記錄", r["note"])

    def test_broker_query_failure_is_not_an_error(self):
        r = check_position(4000, [BUY_4122, REPAIR_4000], broker_shares=None, traded_today=True)
        self.assertEqual(r["status"], "ok")
        self.assertIn("查不到", r["note"])

    def test_zero_position_is_ok(self):
        self.assertEqual(check_position(0, [], broker_shares=0, traded_today=False)["status"], "ok")


class TestWiringAndSafety(unittest.TestCase):
    """接線與「不得自動改帳」守門。"""

    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        cls.park = (ROOT / "core" / "park_asset.py").read_text(encoding="utf-8")

    def test_trader_runs_park_reconcile_daily(self):
        self.assertIn("park_recon", self.main, "收盤區塊要有停泊帳對帳（每日一次去重）")
        self.assertIn("check_position", self.main, "要呼叫 core.park_asset.check_position()")
        self.assertIn("broker_holding_qty(broker, _psym2)", self.main)

    def test_check_position_never_writes_state(self):
        """這支只判定、不改帳（呼叫端負責告警與人工修帳）。"""
        src = inspect.getsource(check_position)
        for bad in ("save_state", "write_text", "open(", "json.dump"):
            self.assertNotIn(bad, src, f"check_position() 不該寫檔（發現 {bad}）")

    def test_park_asset_exposes_helpers(self):
        for fn in ("def load_trades(", "def replay_shares(", "def traded_on(", "def check_position("):
            self.assertIn(fn, self.park)


if __name__ == "__main__":
    unittest.main()
