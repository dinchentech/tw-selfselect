#!/usr/bin/env python
"""回歸測試：auto（自選股）「買入即鎖定」與回測口徑對齊（2026-09-18）。

## 背景（實測到的兩個落差）

1. **實盤漏鎖 `breakout`**：`selfselect_trader.py` 的 auto 鎖定碼原本只寫在
   `if (sn not in ['breakout','keep_wait'])` 分支內 ⇒ 若某股買入當下型態路由到 `breakout`，
   **永遠不會寫入 `logs/auto_resolved.json`**，之後每一圈都走「沒鎖定 → `route_strategy(acd)` 重算」
   ⇒ 持有期間策略可能被中途換掉。
   實例：2026-09-18 `2006` 買進（80.7 → 87.0 的突破型態），鎖定檔仍只有 `{"3515":"bollinger"}`。
2. **回測鎖定時點不同**：回測在**選股日**就 `pick_strategy_by_form(sid, sel_date)` 選定並全程固定，
   而實盤是**買入那一刻**才 `route_strategy()`。`EXEC=signal`（等訊號）下兩者可能相隔數日
   ⇒ 可能選到不同策略。修法：未進場時**每日重路由**決定買訊、**進場成交當天鎖定**（＝實盤行為）。

本測試用 AST 檢查實盤原始碼（專案既有風格，見 `test_close_order_window.py`），
以及對回測新增的純函式 `signal_strategy_for()` 做行為測試。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

SRC_CANDIDATES = ('selfselect_trader.py',)


class TestLiveAutoLockPlacement(unittest.TestCase):
    """實盤：鎖定必須在「不分策略」的共用位置（下單前），不可只在 bollinger 分支內。"""

    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def test_lock_assignment_is_not_inside_breakout_branch(self):
        for rel, src in self._srcs():
            tree = ast.parse(src)
            assigns = []
            for node in ast.walk(tree):
                # 找 AUTO_FIXED_CACHE[symbol] = <strategy> 這種指派
                if isinstance(node, ast.Assign):
                    txt = ast.unparse(node)
                    if txt.startswith('AUTO_FIXED_CACHE[symbol] ='):
                        assigns.append(node)
            self.assertEqual(len(assigns), 1,
                             f'{rel}: 鎖定指派應只有一處（找到 {len(assigns)} 處）——'
                             f'兩處代表舊的分支內版本還在')
            # 往上找所有父層 If，其判斷式不可提到 breakout
            parents = []
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    child._parent = node
            cur = assigns[0]
            while hasattr(cur, '_parent'):
                cur = cur._parent
                if isinstance(cur, ast.If):
                    parents.append(ast.unparse(cur.test))
            joined = ' | '.join(parents)
            self.assertNotIn('breakout', joined,
                             f'{rel}: 鎖定不可被「sn not in [\'breakout\',...]」之類的判斷包住'
                             f'（那正是漏鎖 breakout 的根因）；實際父層判斷：{joined}')
            self.assertTrue(any('_was_auto' in p for p in parents),
                            f'{rel}: 鎖定應以 _was_auto 為條件')
            self.assertTrue(any("'BUY'" in p or '"BUY"' in p for p in parents),
                            f'{rel}: 鎖定應只在 BUY 時發生')

    def test_lock_happens_before_order_and_after_risk_checks(self):
        for rel, src in self._srcs():
            lock_line = next(i for i, ln in enumerate(src.splitlines(), 1)
                             if 'AUTO_FIXED_CACHE[symbol] = sn' in ln)
            order_line = src[:src.index("broker.place_order(symbol, action.lower()")].count('\n') + 1
            mkt_line = next(i for i, ln in enumerate(src.splitlines(), 1)
                            if "os.getenv('MARKET_TREND_FILTER'" in ln)
            self.assertLess(mkt_line, lock_line,
                            f'{rel}: 鎖定應在所有風控檢查之後（被擋掉的買單不該留下鎖定）')
            self.assertLess(lock_line, order_line, f'{rel}: 鎖定應在下單之前')


class TestBacktestEntryLocking(unittest.TestCase):
    """回測：未進場→每日重路由；進場成交當天鎖定。

    規則本體已抽到輕量模組 `core/backtest_rules.signal_strategy()`（重型回測腳本 import 一次要
    ~50 秒，測試不該付這個代價 —— 同 `core/backtest_rules.py` 開頭的理由）。
    """

    def test_locked_wins_over_routing(self):
        from core.backtest_rules import signal_strategy
        calls = []

        def route(sid, dts):
            calls.append((sid, dts))
            return "breakout"

        self.assertEqual(signal_strategy("bollinger", route, "9999", "D"), "bollinger",
                         "已鎖定 → 必須用鎖定值，不可再重路由")
        self.assertEqual(calls, [], "已鎖定就不該呼叫路由")

    def test_unlocked_routes_on_that_day(self):
        from core.backtest_rules import signal_strategy
        calls = []

        def route(sid, dts):
            calls.append((sid, dts))
            return "breakout"

        self.assertEqual(signal_strategy(None, route, "9999", "2026-09-18"), "breakout")
        self.assertEqual(calls, [("9999", "2026-09-18")],
                         "未鎖定 → 必須用『當日』(dts) 路由，不是選股日")

    def test_source_locks_on_fill(self):
        src = (Path(_ROOT) / "scripts" / "backtest_plan2_monthly_3group.py").read_text(encoding="utf-8")
        self.assertIn('positions[sid]["strat"] is None', src,
                      "進場成交時必須檢查尚未鎖定")
        self.assertIn('positions[sid]["strat"] = _st_today', src,
                      "進場成交當天必須鎖定當日路由出來的那個策略")
        self.assertIn('_lock_now = (EXEC != "signal") or (LOCK_AT == "selection")', src,
                      "選股日要不要先鎖定，必須同時考慮 EXEC 與 LOCK_AT（預設 fill＝不先鎖）")
        self.assertIn('LOCK_AT = os.getenv("LOCK_AT", "fill")', src,
                      "LOCK_AT 預設必須是 fill（與實盤一致）")


if __name__ == "__main__":
    unittest.main()
