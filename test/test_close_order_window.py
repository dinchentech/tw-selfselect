#!/usr/bin/env python
"""回歸測試：日K策略的下單時點對齊回測（2026-09-16，使用者決定）。

背景（實盤 vs 回測口徑不一致）：
- **回測**（`scripts/backtest_plan2_monthly_3group.py`）：訊號用**當日收盤**算（`_SIG = STRAT(df)`），
  買賣一律 `close_at(sid, d)` ⇒ **收盤判定、收盤成交**。
- **實盤**（舊）：08:45–13:30 每輪把「日K ＋ 當下報價」合成當日一根 K 就判定，**第一時間下單**
  ⇒ 等於拿開盤價當收盤價。
- **實際後果（2026-09-16 2006）**：09:00:07 以 80.70 賣出（≈當日最低區），
  當日高 82.20、10:51 回到 82.00；而這根死叉貼在邊界（收盤 ≥約 82.3 就不成立）
  ⇒ **實盤做了回測不會做的交易**，績效不可比。

修法：日K策略（bollinger/vwap/ma_cross/breakout/auto）只在**收盤前窗口**（預設 13:25 起、交易時段到 13:30）
判定與下單；`keep_wait`（另一條腿，分鐘級補足/停利機制）**不受影響**。
"""
import ast
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.live_utils import close_order_window_open  # noqa: E402

SRC_CANDIDATES = ('selfselect_trader.py',)
D = datetime


class TestCloseOrderWindow(unittest.TestCase):
    def test_opens_at_1325_by_default(self):
        self.assertFalse(close_order_window_open(D(2026, 9, 16, 9, 0)), '開盤不該是下單窗口')
        self.assertFalse(close_order_window_open(D(2026, 9, 16, 13, 24)), '13:24 尚未進入窗口')
        self.assertTrue(close_order_window_open(D(2026, 9, 16, 13, 25)), '13:25 起為下單窗口')
        self.assertTrue(close_order_window_open(D(2026, 9, 16, 13, 30)), '13:30（交易時段最後一刻）仍在窗口內')

    def test_start_is_configurable(self):
        self.assertTrue(close_order_window_open(D(2026, 9, 16, 13, 22), start='13:20'))
        self.assertFalse(close_order_window_open(D(2026, 9, 16, 13, 19), start='13:20'))

    def test_bad_config_falls_back_to_default(self):
        for bad in ('', 'abc', '25:99', '13', None):
            try:
                got = close_order_window_open(D(2026, 9, 16, 13, 25), start=bad)
            except Exception as e:      # 不可因設定值壞掉而拋例外停掉主迴圈
                self.fail(f'start={bad!r} 不該拋例外：{e}')
            self.assertTrue(got, f'start={bad!r} 應回退預設 13:25（13:25 仍在窗口內）')


class TestLoopGating(unittest.TestCase):
    """原始碼層級：日K策略的判定/下單必須被窗口閘門擋住，而 keep_wait 不受影響"""

    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def test_loop_computes_window_flag(self):
        for rel, src in self._srcs():
            self.assertTrue('close_order_window_open(now)' in src,
                            f'{rel}: 迴圈需算一次收盤下單窗口旗標（單一判斷來源）')

    def test_daily_strategies_skipped_outside_window(self):
        for rel, src in self._srcs():
            self.assertTrue(
                'if (sn != \'keep_wait\') and (not _close_order_window):' in src,
                f'{rel}: 日K策略必須在非下單窗口時跳過（否則又會盤中即時下單、與回測不同口徑）')
            # keep_wait 必須被排除在閘門之外（該腿是分鐘級機制，不受本次對齊影響）
            self.assertTrue("sn != 'keep_wait'" in src, f'{rel}: 閘門需明確排除 keep_wait')

    def test_skip_happens_after_history_update(self):
        """跳過點必須在「更新當日合成K」之後：否則當日 high/low 不會被追蹤、ATR 會失真"""
        for rel, src in self._srcs():
            tree = ast.parse(src)
            seq = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and 'portfolio_history[symbol] = acd' in ast.unparse(node):
                    seq.append(('hist', node.lineno))
                if isinstance(node, ast.If) and '_close_order_window' in ast.unparse(node.test):
                    seq.append(('gate', node.lineno))
            hist = [ln for k, ln in seq if k == 'hist']
            gate = [ln for k, ln in seq if k == 'gate']
            self.assertTrue(hist and gate, f'{rel}: 找不到 history 更新或窗口閘門')
            self.assertLess(max(hist), min(gate),
                            f'{rel}: 窗口閘門必須放在 portfolio_history 更新之後（保住當日 high/low 追蹤）')


if __name__ == '__main__':
    unittest.main()
