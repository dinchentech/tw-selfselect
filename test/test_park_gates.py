#!/usr/bin/env python
"""回歸測試：停泊「A+B」兩道閘門（2026-11-23，v1.1.45）。

## 為什麼

11/20 13:25–13:30 的實況（使用者裁定要改）：

```
✅ E.Sun 下單成功: 盤中零股 sell 2603 909 股 @ 236.00      ← breakout 認賠出場（−14.9%）
🅿️ 停泊股數依整股規則對齊：2464 → 2000 股（…，上限 NT$208,044）
✅ E.Sun 下單成功: 整股 buy 0050 2000 股 @ 84.40           ← 同一圈把回款掃進 0050
```

⇒ 使用者裁定：**A**（大盤跌破年線就留現金、不買 0050）＋ **B**（賣出當天不要馬上停泊，
回款留現金，到下一個交易日的下單窗口再評估，且仍要過 A）。

## 釘住什麼

1. `core.park_asset.market_filter_on()`／`sold_on()` 兩個純函式的語意（旋鈕預設值、日期／方向／排除停泊標的）。
2. `selfselect_trader.park_idle_if_due()` 的**原始碼不變式**：兩道閘門存在、在「名單已建倉完成」
   之後且在下單之前、訊息去重 key 含日期（同 `test_park_no_duplicate.py` 的原始碼層級做法）。
"""
import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SRC = _ROOT / "selfselect_trader.py"

from core.park_asset import market_filter_on, sold_on  # noqa: E402


def _func_source(name: str) -> str:
    """取 `main()` 內某個巢狀函式的原始碼（排除 docstring 與整行註解，理由同 test_park_no_duplicate）。"""
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            first, last = body[0], body[-1]
            lines = src.splitlines()[first.lineno - 1:last.end_lineno]
            return "\n".join(l for l in lines if not l.lstrip().startswith("#"))
    raise AssertionError(f"找不到 {name}()（改名請同步更新本測試）")


def _row(ts: str, sym: str, action: str) -> dict:
    return {"timestamp": ts, "symbol": sym, "signal": "-1" if action == "SELL" else "1",
            "price": "236.0", "quantity": "909", "action": action}


class TestMarketFilterKnob(unittest.TestCase):
    """A 閘門的旋鈕：預設開、明確關閉才關。"""

    def test_default_on_when_key_absent(self):
        self.assertTrue(market_filter_on({}))

    def test_explicit_off_values(self):
        for v in ("false", "FALSE", "0", "no", "off", " false "):
            self.assertFalse(market_filter_on({"PARK_MARKET_FILTER": v}), f"{v!r} 應視為關閉")

    def test_explicit_on_values(self):
        for v in ("true", "1", "yes", "on", ""):
            self.assertTrue(market_filter_on({"PARK_MARKET_FILTER": v}), f"{v!r} 應視為開啟")

    def test_does_not_read_stock_filter_knob(self):
        """`MARKET_TREND_FILTER`（自選股買進）刻意與停泊分開，不能互相代換。"""
        self.assertTrue(market_filter_on({"MARKET_TREND_FILTER": "false"}))


class TestSoldOn(unittest.TestCase):
    """B 閘門：當天有自選股賣出成交才算。"""

    def test_today_sell_counts(self):
        rows = [_row("2026-11-20T13:25:31", "2603", "SELL")]
        self.assertTrue(sold_on(rows, "2026-11-20"))

    def test_buy_only_does_not_count(self):
        rows = [_row("2026-11-20T13:25:31", "2408", "BUY")]
        self.assertFalse(sold_on(rows, "2026-11-20"))

    def test_other_days_do_not_count(self):
        rows = [_row("2026-11-19T13:25:31", "2603", "SELL")]
        self.assertFalse(sold_on(rows, "2026-11-20"))
        self.assertTrue(sold_on(rows, "2026-11-19"))

    def test_park_symbol_is_excluded(self):
        """停泊釋出（賣 0050 換現金）不該觸發 B。"""
        rows = [_row("2026-11-20T13:25:31", "0050", "SELL")]
        self.assertFalse(sold_on(rows, "2026-11-20", park_symbol="0050"))
        self.assertTrue(sold_on(rows, "2026-11-20", park_symbol=""))

    def test_bad_rows_do_not_raise(self):
        rows = [None, {"symbol": "2603"}, {"timestamp": "2026-11-20", "action": "SELL"},
                {"timestamp": "2026-11-20T13:25:31", "symbol": "2603", "action": "SELL "}]
        self.assertTrue(sold_on(rows, "2026-11-20") is True)   # 最後一列 action 有空白仍算 SELL（strip+upper）

    def test_empty_and_none(self):
        self.assertFalse(sold_on([], "2026-11-20"))
        self.assertFalse(sold_on(None, "2026-11-20"))
        self.assertFalse(sold_on([_row("2026-11-20T13:25:31", "2603", "SELL")], ""))


class TestParkIdleGatesSource(unittest.TestCase):
    """`park_idle_if_due()` 原始碼不變式：兩道閘門存在、位置正確、去重 key 含日期。"""

    def setUp(self):
        self.body = _func_source("park_idle_if_due")

    def test_both_gates_present(self):
        self.assertIn("_park_market_ok(", self.body, "A 閘門（大盤年線）不見了")
        self.assertIn("_park_sold_today(", self.body, "B 閘門（當日有賣出）不見了")

    def test_gates_after_build_done_check(self):
        """A/B 閘門必須在「名單已建倉完成」（`_can(`）之後——否則停泊還沒建倉就會被擋。

        注意：`_park_market_ok()` 這個字串在 C 閘門（釋出）也會出現、而 C **刻意**排在 `_can(` 之前
        ⇒ 這裡用「A/B 閘門迴圈」的起點（`for (_code, _why)`）定位，不要拿第一次出現的字串比。
        """
        gates = self.body.index("for (_code, _why)")
        self.assertLess(self.body.index("_can("), gates)
        self.assertLess(gates, self.body.index("_park_market_ok(", gates))
        self.assertLess(gates, self.body.index("_park_sold_today(", gates))

    def test_gates_before_order(self):
        """閘門必須在下單之前——否則只是印訊息、錢照樣花出去。"""
        gates = self.body.index("for (_code, _why)")
        self.assertLess(gates, self.body.index("broker.place_order("))
        self.assertLess(gates, self.body.index("broker.place_order("))

    def test_gates_return_before_ordering(self):
        """命中閘門要**直接 return**（不是只印一行繼續往下買）。"""
        head = self.body[:self.body.index("idle = _idle(")]
        gate_region = head[head.index("for (_code, _why) in"):]
        self.assertIn("return 0.0", gate_region,
                      "閘門命中時必須 return，不能只印訊息（否則還是會送單）")

    def test_gate_messages_are_deduplicated_with_date(self):
        """停泊閘門訊息要每天每檔一次（13:25–13:30 每 60 秒一圈，不去重會洗版）。

        2026-11-25（v1.1.51）更正：去重改走 `_park_notice_once()`（**多槽**、key 各自記日期）；
        原本的 `should_emit_idle_notice()` 是單槽，兩個 key 交替會互相踩掉、每圈重印（11/25 實測 5 次）。
        """
        self.assertIn("_park_notice_once(", self.body)
        self.assertIn("park_gate:", self.body)
        impl = _func_source("_park_notice_once")
        self.assertIn("%Y-%m-%d", impl)

    def test_gate_helpers_use_shared_sources(self):
        """A 走 `market_filter.is_above_ma200_live()`（2026-11-24 v1.1.48 起改用即時指數）、
        B 走 `performance.csv`（`core.books.read_trades`）。"""
        a = _func_source("_park_market_ok")
        self.assertIn("market_filter.is_above_ma200_live()", a)
        self.assertIn("core.park_asset import market_filter_on", a)
        b = _func_source("_park_sold_today")
        self.assertIn("core.books import read_trades", b)
        self.assertIn("sold_on", b)


class TestParkGateSemantics51(unittest.TestCase):
    """v1.1.51：未知不得動作、當日已釋出不買回、訊息多槽去重、pending 佇列。"""

    def _src(self, name):
        return _func_source(name)

    def test_gate_requires_explicit_verdict(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_market_ok() is False", body, "C 閘門必須只在明確 False 才釋出")
        self.assertIn("_park_market_ok() is not True", body, "A 閘門必須在 False/None 都擋")

    def test_release_guard_present(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_released_today(", body, "當日已釋出 ⇒ 當天不買回")

    def test_notice_dedupe_is_multislot(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_notice_once(", body)
        self.assertNotIn("should_emit_idle_notice(_park_gate_state", body,
                         "單槽去重會在不同 key 之間互相踩掉（11/25 每圈重印）")

    def test_pending_queue_used_at_booking(self):
        for fn in ("park_idle_if_due", "park_release_all"):
            seg = self._src(fn)
            self.assertIn("pending_verifies", seg, f"{fn} 必須把待對帳寫進佇列")
        self.assertIn("pending_verifies", self._src("_reconcile_park_pending"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestParkReleaseOnBearSource(unittest.TestCase):
    """C 閘門（2026-11-23 使用者裁定）：大盤跌破年線 ⇒ **釋出**停泊部位、留現金。"""

    def setUp(self):
        self.body = _func_source("park_idle_if_due")

    def test_release_call_exists(self):
        self.assertIn("park_release_all(", self.body, "C 閘門（釋出停泊部位）不見了")

    def test_release_guarded_by_market_and_holding(self):
        idx = self.body.index("park_release_all(")
        head = self.body[:idx]
        self.assertIn("_park_market_ok()", head, "釋出必須綁大盤年線判斷（A/C 同一個旋鈕）")
        self.assertIn("st.get('shares')", head, "沒有持倉就不該送釋出單")

    def test_release_before_build_check(self):
        """釋出要排在「名單已建倉完成」之前：名單還沒建倉、大盤轉壞時一樣該先變現。"""
        self.assertLess(self.body.index("park_release_all("), self.body.index("_can("))

    def test_release_failure_is_throttled(self):
        """釋出失敗要寫 `last_park_ts`（5 分鐘冷卻），否則 13:25–13:30 每 60 秒重送一次。"""
        seg = self.body[self.body.index("park_release_all("):]
        self.assertIn("last_park_ts", seg[:seg.index("_can(")],
                      "釋出失敗沒有留時間戳 ⇒ 會每圈重送")

    def test_release_message_deduplicated(self):
        """C 的訊息每天只印一次（13:25–13:30 每 60 秒一圈）。"""
        self.assertIn("_park_notice_once('c_release')", self.body)


class TestParkGateSemantics51(unittest.TestCase):
    """v1.1.51：未知不得動作、當日已釋出不買回、訊息多槽去重、pending 佇列。"""

    def _src(self, name):
        return _func_source(name)

    def test_gate_requires_explicit_verdict(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_market_ok() is False", body, "C 閘門必須只在明確 False 才釋出")
        self.assertIn("_park_market_ok() is not True", body, "A 閘門必須在 False/None 都擋")

    def test_release_guard_present(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_released_today(", body, "當日已釋出 ⇒ 當天不買回")

    def test_notice_dedupe_is_multislot(self):
        body = self._src("park_idle_if_due")
        self.assertIn("_park_notice_once(", body)
        self.assertNotIn("should_emit_idle_notice(_park_gate_state", body,
                         "單槽去重會在不同 key 之間互相踩掉（11/25 每圈重印）")

    def test_pending_queue_used_at_booking(self):
        for fn in ("park_idle_if_due", "park_release_all"):
            seg = self._src(fn)
            self.assertIn("pending_verifies", seg, f"{fn} 必須把待對帳寫進佇列")
        self.assertIn("pending_verifies", self._src("_reconcile_park_pending"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
