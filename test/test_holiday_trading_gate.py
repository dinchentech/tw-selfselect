#!/usr/bin/env python
"""回歸測試：主迴圈的交易動作也要排除國定假日（2026-09-15）。

背景：主迴圈有多處只認 `is_weekday`（週一到五）⇒ **平日國定假日**（2026-09-25 中秋、
09-28 教師節）仍會：
  ① 策略/訊號迴圈（08:45~13:30 區塊）→ 用**休市舊價**算訊號，可能嘗試下單；
  ② 買入補足檢查（方案 B）→ 嘗試補足下單。
市場休市 ⇒ 玉山退單 ⇒ 每檔一次 TG 告警（噪音＋無意義委託）。

修法：迴圈頂端算一次 `is_tday = is_weekday and is_trading_day(now)`（`core.live_utils`，
日曆＝`core/trading_calendar`，與母專案選股同一份），三處交易閘門改用它；
**報告端**（`report_due(..., trading_day=is_tday)`）先前已帶交易日判斷。

⚠️ 刻意**不**改 08:40 熱重載（`is_weekday`）：它同時負責「休市日曆自動更新」，
假日也該跑，且不涉及下單。
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

from core.live_utils import is_trading_day  # noqa: E402

SRC_CANDIDATES = ('selfselect_trader.py',)
FLAG = 'is_tday = is_weekday and is_trading_day(now)'


def _blocks(tree, *needles):
    """找出 test 運算式同時含所有 needles 的 If 節點"""
    found = []

    class Walker(ast.NodeVisitor):
        def visit_If(self, node):
            s = ast.unparse(node.test)
            if all(n in s for n in needles):
                found.append(node)
            self.generic_visit(node)

    Walker().visit(tree)
    return found


class TestHolidayTradingGate(unittest.TestCase):
    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def test_loop_defines_trading_day_flag(self):
        """迴圈頂端要有一個共用的交易日旗標（單一判斷來源）"""
        for rel, src in self._srcs():
            self.assertTrue(FLAG in src,
                            f'{rel}: 迴圈頂端缺少 `{FLAG}`（國定假日無法與週末一起擋掉）')

    def test_strategy_loop_gated_on_trading_day(self):
        """策略/訊號迴圈（08:45 起的交易時段）必須用交易日旗標，不可只看 is_weekday"""
        for rel, src in self._srcs():
            blocks = _blocks(ast.parse(src), 'h == 8', 'm >= 45')
            self.assertTrue(blocks, f'{rel}: 找不到交易時段區塊')
            for b in blocks:
                t = ast.unparse(b.test)
                self.assertIn('is_tday', t,
                              f'{rel}: 交易時段區塊仍在用 is_weekday（平日國定假日會下單）: {t}')

    def test_post_close_block_gated_on_trading_day(self):
        """13:31 盤後區塊（報告/換股）也要交易日"""
        for rel, src in self._srcs():
            blocks = _blocks(ast.parse(src), 'h == 13', 'm >= 31')
            self.assertTrue(blocks, f'{rel}: 找不到 13:31 盤後區塊')
            for b in blocks:
                t = ast.unparse(b.test)
                self.assertIn('is_tday', t, f'{rel}: 13:31 盤後區塊仍在用 is_weekday: {t}')

    def test_topup_market_open_gated_on_trading_day(self):
        """買入補足（方案 B）的「盤中」判定必須用交易日旗標"""
        for rel, src in self._srcs():
            self.assertFalse('_market_open_now = is_weekday and' in src,
                             f'{rel}: 買入補足仍以 is_weekday 判定盤中（假日會嘗試下單）')
            self.assertTrue('_market_open_now = is_tday and' in src,
                            f'{rel}: 買入補足的盤中判定應改用 is_tday')

    def test_hot_reload_intentionally_keeps_weekday(self):
        """08:40 熱重載刻意維持 is_weekday（它同時負責假日也要跑的休市日曆更新）"""
        for rel, src in self._srcs():
            self.assertTrue('if is_weekday and h == 8 and m >= 40' in src,
                            f'{rel}: 08:40 熱重載/日曆更新不應被交易日閘門擋掉')

    def test_orphan_cleanup_gated_on_trading_day(self):
        """孤兒清倉/超額 trim（會下賣單）也必須只在交易日執行。

        原本註解寫「每檔每日一次，**不限時段**」⇒ 週末/國定假日也會對休市市場下賣單，
        玉山退單後每天每檔發一次無意義 TG 告警。
        """
        for rel, src in self._srcs():
            tree = ast.parse(src)
            found = []

            class Walker(ast.NodeVisitor):
                def visit_For(self, node):
                    if 'holdings.keys()' in ast.unparse(node.iter):
                        found.append(node)
                    self.generic_visit(node)

            Walker().visit(tree)
            self.assertTrue(found, f'{rel}: 找不到孤兒清倉迴圈')
            for node in found:
                # 2026-10-08（V4.51）：閘門由「交易日」升級為「交易日 ＋ 交易時段（09:00–13:30）」——
                #   原本只有 is_tday ⇒ VM 排程 08:00 開機第一圈（08:0x）就會送單，而這類 trim 多為
                #   **零股**（盤中零股 09:00 才開始）⇒ 退單後 `_cleaned_orphans` 已標記「當日完成」
                #   ⇒ 整天靜默失敗。`_trade_window` 仍以 `is_tday` 為輸入，故交易日閘門未被放鬆。
                body = ast.unparse(node)
                self.assertIn('not _trade_window', body,
                              f'{rel}: 孤兒清倉/trim 迴圈缺時段閘門（開盤前／休市會下單）')
            for rel, src in self._srcs():
                self.assertIn('_trade_window = intraday_trade_window(is_tday, h, m)', src,
                              f'{rel}: 下單時段必須由 is_tday＋時段共同決定')

    def test_composed_flag_is_false_on_holiday(self):
        """功能性：平日國定假日 ⇒（is_weekday and is_trading_day）為 False；交易日為 True"""
        holiday = datetime(2026, 9, 28, 10, 0)      # 教師節（週一）
        normal = datetime(2026, 9, 15, 10, 0)       # 週二交易日
        self.assertTrue(holiday.weekday() < 5, '測試前提：09-28 是平日')
        self.assertFalse(holiday.weekday() < 5 and is_trading_day(holiday),
                         '平日國定假日必須被擋掉（否則會用休市舊價下單）')
        self.assertTrue(normal.weekday() < 5 and is_trading_day(normal))


if __name__ == '__main__':
    unittest.main()
