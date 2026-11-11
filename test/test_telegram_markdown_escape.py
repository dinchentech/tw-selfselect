"""Telegram legacy Markdown 轉義（2026-11-09，v1.1.38）

## 問題

`utils.telegram.send_telegram_message()` 優先用 `parse_mode="Markdown"`（legacy）。
只要訊息裡有**落單**的 `_`／`*`／`` ` ``／`[`，Telegram 就回
`400 Bad Request: can't parse entities`，程式接著降級成純文字——使用者在 Telegram 看到的就是
「格式掉了」，而日誌只留一行「（Markdown 降級為純文字）」，連哪一則壞了都看不出來。

本專案的訊息幾乎每一則都帶底線，因為**策略名稱就是底線**：

- 靜態：`📥 *{symbol}* keep_wait 加碼 …`（字面 `keep_wait` 本身就會炸）
- 動態：策略標籤 `keep_wait`／`auto→ma_cross`、券商狀態 `broker_mismatch`／`ledger_mismatch`、
  對帳 `note`、例外字串、指令 `reconcile_broker_books.py` …

實測（2026-11-09 VM）：每天至少一則降級，`啟動持倉報告` 就是常客。

## 修法

1. `escape_md()`：只轉義**動態內容**（訊息本身的 `*粗體*` 留在外面）。
2. 靜態字面裡的底線（`keep_wait`、`tw_selfselect_bot`、`logs/broker_reconcile.jsonl`）直接寫成 `keep\\_wait`。
3. `md_ok()`：送出前粗檢標記是否成對；不成對就**直接發純文字並印出肇因**（省一次 400 往返，
   也讓「哪一則壞了」不再是祕密）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from utils import telegram as tg                           # noqa: E402
from core.live_notifications import _build_holdings_message  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class FakeResp:
    def __init__(self, status):
        self.status_code = status


class TestEscapeMd(unittest.TestCase):
    def test_escapes_legacy_markers(self):
        self.assertEqual(tg.escape_md("keep_wait"), "keep\\_wait")
        self.assertEqual(tg.escape_md("ma_cross"), "ma\\_cross")
        self.assertEqual(tg.escape_md("a*b"), "a\\*b")
        self.assertEqual(tg.escape_md("`x`"), "\\`x\\`")
        self.assertEqual(tg.escape_md("[1]"), "\\[1]")   # `]` 不必轉義（只有 `[` 開連結）

    def test_non_strings(self):
        self.assertEqual(tg.escape_md(None), "")
        self.assertEqual(tg.escape_md(123), "123")
        self.assertEqual(tg.escape_md(97.6), "97.6")

    def test_plain_text_untouched(self):
        self.assertEqual(tg.escape_md("2609 賣出 4,000 股 @ 57.30"), "2609 賣出 4,000 股 @ 57.30")
        self.assertEqual(tg.escape_md("要買 2609 需要資金"), "要買 2609 需要資金")


class TestMdOk(unittest.TestCase):
    def test_balanced_ok(self):
        self.assertTrue(tg.md_ok("*粗體*"))
        self.assertTrue(tg.md_ok("🅿️ *停泊*\nkeep\\_wait 2,000 股"))
        self.assertTrue(tg.md_ok("見 [1] 或 [2]"))

    def test_unbalanced_flagged(self):
        self.assertFalse(tg.md_ok("keep_wait"))
        self.assertFalse(tg.md_ok("logs/broker_snapshot_*.json"))
        self.assertFalse(tg.md_ok("*粗體"))

    def test_escaped_neutralizes(self):
        self.assertTrue(tg.md_ok(tg.escape_md("keep_wait 和 ma_cross")))


class TestSenderGate(unittest.TestCase):
    """送出前就發現不成對 ⇒ 直接走純文字（不再靠 400 往返）。"""

    def setUp(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "TEST_TOKEN"
        os.environ["TELEGRAM_CHAT_ID"] = "TEST_CHAT"

    @mock.patch("utils.telegram.requests.post")
    def test_unbalanced_goes_plain_once(self, mock_post):
        mock_post.return_value = FakeResp(200)
        self.assertTrue(tg.send_telegram_message("📥 *2408* keep_wait 加碼 6 股"))
        self.assertEqual(mock_post.call_count, 1, "不該先送 Markdown 再被 400 退回")
        self.assertNotIn("parse_mode", mock_post.call_args.kwargs["json"])

    @mock.patch("utils.telegram.requests.post")
    def test_balanced_uses_markdown(self, mock_post):
        mock_post.return_value = FakeResp(200)
        self.assertTrue(tg.send_telegram_message("🅿️ *停泊釋出*\n0050 賣出 4,000 股\n原因：要買 2609 需要資金"))
        self.assertEqual(mock_post.call_args.kwargs["json"].get("parse_mode"), "Markdown")

    @mock.patch("utils.telegram.requests.post")
    def test_trade_alert_escapes_strategy(self, mock_post):
        mock_post.return_value = FakeResp(200)
        tg.send_trade_alert("2609", "BUY", 57.3, 4000, "MA_CROSS")
        text = mock_post.call_args.kwargs["json"]["text"]
        self.assertEqual(mock_post.call_args.kwargs["json"].get("parse_mode"), "Markdown")
        self.assertIn("MA\\_CROSS", text)
        self.assertTrue(tg.md_ok(text))


class _TmpCwd:
    """建立含 logs/ 的暫存工作目錄（持倉報告用相對路徑讀檔）。"""

    def __init__(self, holdings, auto_resolved=None, alloc=None):
        self.holdings = holdings
        self.auto_resolved = auto_resolved or {}
        self.alloc = alloc or {}

    def __enter__(self):
        self._old = os.getcwd()
        self._dir = tempfile.mkdtemp(prefix="tw_mdesc_")
        logs = Path(self._dir) / "logs"
        logs.mkdir(parents=True)
        (logs / "holdings.json").write_text(json.dumps(self.holdings))
        (logs / "auto_resolved.json").write_text(json.dumps(self.auto_resolved))
        (logs / "stock_allocation.json").write_text(json.dumps(self.alloc))
        os.chdir(self._dir)
        return self._dir

    def __exit__(self, *exc):
        os.chdir(self._old)


class TestHoldingsReportValid(unittest.TestCase):
    """持倉報告曾經每天降級：策略標籤 `keep_wait`／`auto→ma_cross` 的底線是兇手。"""

    def _build(self, portfolio):
        with _TmpCwd({"0050": 2000}, auto_resolved={"2609": "ma_cross"},
                     alloc={"0050": {"total_buy_cost": 195200, "total_buy_shares": 2000}}):
            return _build_holdings_message(pd, "1.1.38", "🚀", "啟動持倉報告", 500000, portfolio)

    def test_keep_wait_label_is_escaped(self):
        msg = self._build({"0050": {"strategy": "keep_wait", "alloc": 25}})
        self.assertIn("keep\\_wait", msg)
        self.assertTrue(tg.md_ok(msg), msg)

    def test_auto_locked_label_is_escaped(self):
        msg = self._build({"0050": {"strategy": "auto", "alloc": 25}, "2609": {"strategy": "auto", "alloc": 25}})
        self.assertTrue(tg.md_ok(msg), msg)


class TestReportParkSection(unittest.TestCase):
    """停泊區塊（v1.1.39）：現價/市值、現金上限 0、`*無*` 不被二次轉義。"""

    def _build(self):
        import tempfile, json as _json
        d = tempfile.mkdtemp()
        logs = Path(d) / "logs"
        logs.mkdir(parents=True)
        (logs / "holdings.json").write_text(_json.dumps({"2609": 4000}))
        (logs / "auto_resolved.json").write_text(_json.dumps({"2609": "bollinger"}))
        (logs / "stock_allocation.json").write_text(
            _json.dumps({"2609": {"total_buy_cost": 229200, "total_buy_shares": 4000}}))
        (logs / "park_position.json").write_text(
            _json.dumps({"symbol": "0050", "shares": 2000, "cost": 195200.0}))
        # ⚠️ `park_plan.json` 必須用「今天」的日期，報告才肯顯示（拿舊計畫誤導是刻意的設計）
        #   ——2026-11-11 部署前檢查踩到：寫死日期只在當天通過，隔天就紅。
        _today = datetime.now().strftime("%Y-%m-%d")
        (logs / "park_plan.json").write_text(_json.dumps({
            "date": _today, "symbol": "0050", "idle": 19980.0, "cash": 0.0, "cap": 0.0,
            "price": 97.45, "target_shares": 0, "actual_shares": 0, "status": "SKIP",
            "reason": "可用金額 NT$0 不足（最低門檻 NT$10,000）", "unknown": False}))
        old = os.getcwd()
        os.chdir(d)
        try:
            with mock.patch("core.inst_data.fetch_latest_closes_dated",
                            return_value={"0050": {"price": 97.45, "date": _today},
                                          "2609": {"price": 58.0, "date": _today}}):
                return _build_holdings_message(pd, "1.1.39", "🚀", "啟動持倉報告", 1000000,
                                               {"2609": {"strategy": "auto", "alloc": 25}})
        finally:
            os.chdir(old)

    def test_park_line_has_price_and_value(self):
        msg = self._build()
        self.assertIn("現價 97.45", msg, "停泊代號也要抓報價（否則看不到現價/市值）")
        self.assertIn("市值 NT$194,900", msg)

    def test_zero_cash_is_visible(self):
        msg = self._build()
        self.assertIn("現金上限 NT$0", msg)

    def test_bold_not_double_escaped(self):
        """`format_plan_vs_actual()` 自己轉義動態原因、並保留 `*粗體*` ⇒ 呼叫端不可再轉義。"""
        msg = self._build()
        self.assertIn("*無*", msg)
        self.assertNotIn(r"\*無\*", msg)

    def test_available_capital_annotated(self):
        msg = self._build()
        self.assertIn("含停泊部位賣出後可動用", msg)

    def test_park_pnl_in_line(self):
        """停泊行要有損益（v1.1.40）：2,000 股 @97.60、現價 97.45 ⇒ -300（-0.15%）。"""
        msg = self._build()
        self.assertIn("損益 -300（-0.15%）", msg)

    def test_combined_totals(self):
        """合計（持股＋停泊）：市值 232,000 + 194,900；損益 +2,800 + (-300)。"""
        msg = self._build()
        self.assertIn("總資產(持股+停泊): NT$426,900", msg)
        self.assertIn("合計未實現損益: +2,500（持股 +2,800｜停泊 -300）", msg)

    def test_message_is_valid_markdown(self):
        self.assertTrue(tg.md_ok("🤖 TW SelfSelect\n" + self._build()))


class TestSourceGuards(unittest.TestCase):
    """原始碼守門：動態內容一律過 escape_md；靜態底線一律背斜線。"""

    def _read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_all_senders_import_escape_md(self):
        for rel in ("selfselect_trader.py", "core/live_notifications.py",
                    "core/live_capital.py", "data/esun_provider.py"):
            self.assertIn("escape_md", self._read(rel), f"{rel} 沒用 escape_md")

    def test_startup_message_escapes_strategy(self):
        src = self._read("selfselect_trader.py")
        self.assertIn("escape_md(c['strategy'])", src,
                      "啟動訊息的策略名（keep_wait）必須轉義")

    def test_startup_list_avoids_brackets(self):
        """legacy Markdown 會把 `[auto]` 的方括號吃掉（實測 TG 顯示 2408auto）⇒ 用括號。"""
        src = self._read("selfselect_trader.py")
        self.assertIn("({escape_md(c['strategy'])})", src)
        self.assertNotIn("[{escape_md(c['strategy'])}]", src)

    def test_park_messages_escape_reason(self):
        src = self._read("selfselect_trader.py")
        self.assertIn("escape_md(reason)", src)

    def test_risk_and_reconcile_escape_dynamic(self):
        src = self._read("selfselect_trader.py")
        for frag in ("escape_md(reject_reason)", "escape_md(_prc['note'])",
                     "escape_md(_ab['summary'])", "escape_md(_lines)"):
            self.assertIn(frag, src, f"缺少轉義：{frag}")

    def test_static_underscores_are_escaped(self):
        """靜態字面裡的底線也要背斜線（`keep_wait` 本身就是炸彈）。"""
        for rel in ("selfselect_trader.py", "core/live_capital.py"):
            src = self._read(rel)
            for line in src.splitlines():
                if "keep_wait" not in line or "send_telegram_message" not in line:
                    continue
                if ("f'" not in line) and ('f"' not in line):
                    continue          # 不是訊息字面（例如函式呼叫 _execute_keep_wait_on_profit_roll）
                self.assertIn("keep\\_wait", line,
                              f"{rel} 的訊息字面仍有未轉義的 keep_wait：{line.strip()}")
        trader = self._read("selfselect_trader.py")
        self.assertIn(r"tw\_selfselect\_bot", trader)
        self.assertIn(r"reconcile\_broker\_books.py", trader)
        self.assertIn(r"logs/broker\_reconcile.jsonl", trader)


if __name__ == "__main__":
    unittest.main()
