#!/usr/bin/env python
"""收盤／睡前報告「一天一次」的回歸測試（2026-09-15）。

背景：VM 容器日誌實證兩次重複發送——
  ① 2026-09-14 18:57:07 重啟（deploy 後）→ 18:57:23 立刻又發一輪
     「收盤持倉報告＋dashboard＋睡前持倉報告」（當天 13:45 已發過）
  ② 2026-09-15 00:57:34 跨午夜 → 再發同一輪
根因：`daily_report_sent_date` / `sleep_notified_date` 只存在記憶體、且判斷式是
`!= now.date()`；而非交易時段分支只要 `sleep_seconds >= 3600` 就會送
⇒（a）盤後任何重啟都補發一次、（b）每天午夜換日那一輪再發一次。

修復：`core.live_utils.report_due()` —— 收盤後窗口（同日 13:31 起）＋ 已發送日期
落地在 `logs/report_state.json`。**但「盤後崩潰補發」必須保留**
（2026-09-10 主迴圈卡死 8 小時、收盤/睡前報告全掉，17:16 重啟才補發）。
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

from core.live_utils import (  # noqa: E402
    report_due, mark_report_sent, close_report_window_open, REPORT_STATE_PATH,
    is_trading_day,
)

SRC_CANDIDATES = ('selfselect_trader.py',)
D = datetime


class TestReportDue(unittest.TestCase):
    def test_midnight_rollover_does_not_resend(self):
        """跨午夜（00:57）不得再發一次前一天的收盤/睡前報告"""
        state = {'daily_report': '2026-09-14', 'sleep': '2026-09-14'}
        now = D(2026, 9, 15, 0, 57, 34)
        self.assertFalse(close_report_window_open(now))
        self.assertFalse(report_due(now, state, 'daily_report'))
        self.assertFalse(report_due(now, state, 'sleep'))

    def test_restart_after_close_same_day_does_not_resend(self):
        """同日盤後重啟（已發過）不得補發第二次"""
        state = {'daily_report': '2026-09-14'}
        self.assertFalse(report_due(D(2026, 9, 14, 18, 57), state, 'daily_report'))

    def test_first_report_in_window_sends_then_locks(self):
        """收盤後窗口內第一次要發；標記後同一輪與下一輪都不再發"""
        state = {}
        now = D(2026, 9, 14, 13, 45)
        self.assertTrue(report_due(now, state, 'daily_report'))
        mark_report_sent(state, 'daily_report', now)
        self.assertEqual(state['daily_report'], '2026-09-14')
        self.assertFalse(report_due(now, state, 'daily_report'))
        self.assertFalse(report_due(D(2026, 9, 14, 14, 45), state, 'daily_report'))

    def test_afternoon_catchup_still_sends(self):
        """盤後崩潰補發必須保留：當日 17:16 重啟且當日尚未發過 → 要發"""
        self.assertTrue(report_due(D(2026, 9, 14, 17, 16), {}, 'daily_report'))
        self.assertTrue(report_due(D(2026, 9, 14, 17, 16), {}, 'sleep'))

    def test_before_close_no_report(self):
        """盤中（含 13:30 收盤前最後一分鐘）不得發收盤報告"""
        for hm in ((9, 30), (12, 0), (13, 30)):
            self.assertFalse(close_report_window_open(D(2026, 9, 14, hm[0], hm[1])),
                             f'{hm} 不應在收盤報告窗口內')
            self.assertFalse(report_due(D(2026, 9, 14, hm[0], hm[1]), {}, 'daily_report'))

    def test_keys_are_independent(self):
        """收盤報告發過不影響睡前報告（兩者各自一天一次）"""
        state = {}
        now = D(2026, 9, 14, 13, 45)
        mark_report_sent(state, 'daily_report', now)
        self.assertTrue(report_due(now, state, 'sleep'))

    def test_next_day_in_window_sends_again(self):
        """隔天收盤後仍要正常發（不可因落地狀態而永久靜音）"""
        state = {'daily_report': '2026-09-14', 'sleep': '2026-09-14'}
        now = D(2026, 9, 15, 13, 45)
        self.assertTrue(report_due(now, state, 'daily_report'))
        self.assertTrue(report_due(now, state, 'sleep'))


class TestTradingDayGate(unittest.TestCase):
    """報告只在**交易日**發（週末／國定假日不發）——2026-09-15 收緊。

    收緊前：非交易時段分支只看「距下次開盤 ≥1 小時」，週六/週日下午也會各發一次
    「收盤持倉報告＋睡前持倉報告」（日曆日為單位）⇒ 使用者要求收緊成僅交易日。
    """

    def test_weekend_is_not_trading_day(self):
        self.assertFalse(is_trading_day(D(2026, 9, 19, 14, 0)), '週六不是交易日')
        self.assertFalse(is_trading_day(D(2026, 9, 20, 14, 0)), '週日不是交易日')

    def test_holiday_is_not_trading_day(self):
        self.assertTrue(is_trading_day(D(2026, 9, 15, 14, 0)), '2026-09-15（二）是交易日')
        self.assertFalse(is_trading_day(D(2026, 9, 25, 14, 0)), '2026-09-25 中秋節休市')
        self.assertFalse(is_trading_day(D(2026, 9, 28, 14, 0)), '2026-09-28 教師節休市')

    def test_injected_calendar(self):
        class _Cal:
            def is_trading_day(self, d):
                return False
        self.assertFalse(is_trading_day(D(2026, 9, 15, 14, 0), calendar=_Cal()))

    def test_broken_calendar_does_not_silence_reports(self):
        """日曆判斷壞掉時保守回「週末以外照發」，不可整天靜音"""
        class _Boom:
            def is_trading_day(self, d):
                raise RuntimeError('boom')
        self.assertTrue(is_trading_day(D(2026, 9, 15, 14, 0), calendar=_Boom()))

    def test_report_due_skips_non_trading_day(self):
        sat = D(2026, 9, 19, 14, 0)
        self.assertTrue(close_report_window_open(sat), '週六午後本來就在「收盤後窗口」內')
        self.assertFalse(report_due(sat, {}, 'daily_report', trading_day=False))
        self.assertFalse(report_due(sat, {}, 'sleep', trading_day=False))
        self.assertTrue(report_due(D(2026, 9, 15, 14, 0), {}, 'daily_report', trading_day=True))


class TestSleepReportAtClose(unittest.TestCase):
    """睡前報告改到 **13:45 收盤報告同一輪**發送（2026-09-15）。

    背景：VM 依 GCP 執行個體排程在台北 **14:00 關機**，而睡前報告原本要等
    13:31–13:59 區塊結束、約 14:00:3x 才在非交易時段分支發 → 與關機**競態**，
    有可能整份沒送出去（09-10 那類事故就讓收盤/睡前報告全掉）。
    修法：13:45 那一輪同時發「收盤報告＋摘要＋儀表板」與「睡前持倉報告」；
    非交易時段分支**保留為補發路徑**（盤後崩潰後重啟仍會補齊）。
    """

    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def _postclose_blocks(self, src):
        return [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.If)
                and 'm >= 31' in ast.unparse(n.test) and 'h == 13' in ast.unparse(n.test)]

    def test_close_round_sends_both_reports(self):
        for rel, src in self._srcs():
            blocks = self._postclose_blocks(src)
            self.assertTrue(blocks, f'{rel}: 找不到 13:31+ 盤後區塊')
            for b in blocks:
                body = ast.unparse(b)
                self.assertEqual(body.count('report_due('), 2,
                                 f'{rel}: 13:45 那一輪要同時處理收盤報告與睡前報告（避免 14:00 關機競態）')
                self.assertIn("'daily_report'", body, f'{rel}: 13:31+ 區塊缺收盤報告')
                self.assertIn("'sleep'", body, f'{rel}: 13:31+ 區塊缺睡前報告')
                self.assertIn('send_sleep_notification', body,
                              f'{rel}: 13:31+ 區塊要實際送出睡前報告')
                self.assertIn('m >= 45', body,
                              f'{rel}: 報告觸發要用 m >= 45 —— 用「等於 45」時，'
                              f'主迴圈每輪 sleep(60) 的漂移／13:46 才重啟都會讓整天的報告漏發')

    def test_non_trading_branch_keeps_fallback(self):
        """補發路徑必須留著：13:45 兩個 ＋ 非交易時段兩個 = 4 個呼叫點"""
        for rel, src in self._srcs():
            self.assertGreaterEqual(src.count('report_due('), 4,
                                    f'{rel}: 非交易時段的報告補發路徑不可拿掉（崩潰後重啟要補齊）')


class TestStateFileRoundTrip(unittest.TestCase):
    """狀態真的落地：模擬「重啟」＝重新從磁碟載入 state"""

    def test_persisted_state_survives_restart(self):
        import tempfile
        from core.live_state import load_json, save_json

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'report_state.json')
            state = load_json(path, {})
            now = D(2026, 9, 14, 13, 45)
            self.assertTrue(report_due(now, state, 'daily_report'))
            mark_report_sent(state, 'daily_report', now)
            save_json(state, path)

            state2 = load_json(path, {})        # ← 模擬程序重啟後重新載入
            self.assertFalse(report_due(D(2026, 9, 14, 18, 57), state2, 'daily_report'),
                             '同日盤後重啟不得再發一次')
            self.assertFalse(report_due(D(2026, 9, 15, 0, 57), state2, 'daily_report'),
                             '跨午夜那一輪不得再發一次')
            self.assertTrue(report_due(D(2026, 9, 15, 13, 45), state2, 'daily_report'),
                            '隔天收盤後仍要正常發（不可永久靜音）')


class TestReportStatePersisted(unittest.TestCase):
    """原始碼層級防護：報告狀態必須落地、不得退回記憶體變數"""

    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def test_memory_only_flags_removed(self):
        for rel, src in self._srcs():
            self.assertFalse(
                'daily_report_sent_date = None' in src,
                f'{rel}: 報告狀態不可只放記憶體（重啟即重發）')
            self.assertFalse(
                'sleep_notified_date = None' in src,
                f'{rel}: 報告狀態不可只放記憶體（重啟即重發）')

    def test_uses_report_due_and_state_file(self):
        self.assertEqual(REPORT_STATE_PATH, 'logs/report_state.json',
                         '已發送日期必須落地在 logs/report_state.json')
        for rel, src in self._srcs():
            self.assertGreaterEqual(
                src.count('report_due('), 2,
                f'{rel}: 收盤報告的兩個發送點都要用 report_due() 閘門')
            self.assertTrue('REPORT_STATE_PATH' in src and 'save_json(_report_state' in src,
                            f'{rel}: 標記後必須把 REPORT_STATE_PATH 落地（重啟才知道今天發過）')

    def test_every_call_site_gates_on_trading_day(self):
        """每一處 report_due() 都要帶交易日判斷（否則週末/假日又會發）"""
        for rel, src in self._srcs():
            self.assertEqual(
                src.count('trading_day=is_tday'), src.count('report_due('),
                f'{rel}: 每個 report_due() 呼叫都要傳 trading_day=is_tday（迴圈頂端的交易日旗標）')


if __name__ == '__main__':
    unittest.main()
