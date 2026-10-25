#!/usr/bin/env python
"""回歸測試：「今日交易日報」必須真的列出今天的成交（2026-09-16 實盤發現永遠空白）。

症狀：09-16 收盤時收到
    📊 *今日交易日報*
    📅 今日無交易紀錄
但當天 09:00:07 明明有一筆 `SELL 2006 735 股`（`performance.csv` 有列、儀表板也計入）。

根因：呼叫端是 `send_daily_report(pd, datetime)` —— 傳的是 `datetime` **類別**（不是模組），
而函式內寫 `today = date.today()` ⇒ 拿到的是 **datetime**（帶時分秒）；
`df["timestamp"].dt.date == today` 是「date 比 datetime」⇒ **永遠不相等** ⇒ 每天都走空表分支。
（`core/live_notifications.py` 本身沒有 import datetime，所以 `date` 只能是參數。）

修法：把 `arg.today()` 正規化成 `date`（並讓呼叫端傳 `date`），兩種呼叫端都必須正確。
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import core.live_notifications as LN


class TestDailyReportDateFilter(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        logs = Path("logs")
        logs.mkdir()
        today = date.today()
        self.today = today
        rows = [
            # 今天：一筆賣出（實盤 09-16 這筆就是被漏掉的）
            {"timestamp": datetime.combine(today, datetime.min.time()).replace(hour=9, minute=0, second=7).isoformat(),
             "symbol": "2006", "signal": -1, "price": 80.7, "quantity": 735,
             "action": "SELL", "exclude_daily": 0, "cost": 263.0},
            # 昨天：不該被算進今日日報
            {"timestamp": (datetime.combine(today, datetime.min.time()) - timedelta(days=1)).replace(hour=10, minute=0).isoformat(),
             "symbol": "3008", "signal": -1, "price": 6795.0, "quantity": 13,
             "action": "SELL", "exclude_daily": 1, "cost": 0},
        ]
        pd.DataFrame(rows).to_csv(logs / "performance.csv", index=False)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _capture(self, date_arg):
        sent = []
        with patch.object(LN, "notify_all", side_effect=sent.append):
            LN.send_daily_report(pd, date_arg)
        return "\n".join(sent)

    def test_datetime_class_caller_lists_today_trades(self):
        """實盤呼叫端：send_daily_report(pd, datetime)"""
        msg = self._capture(datetime)
        self.assertNotIn("今日無交易紀錄", msg,
                         "傳 datetime 類別時仍被判成「今日無交易紀錄」（date 比 datetime 永遠不等）")
        self.assertIn("2006", msg, "今天那筆 SELL 2006 必須出現在日報裡")
        self.assertIn("賣出", msg)
        self.assertNotIn("3008", msg, "昨天的成交不該出現在今日日報")

    def test_date_class_caller_also_works(self):
        """建議呼叫端：send_daily_report(pd, date)"""
        msg = self._capture(date)
        self.assertNotIn("今日無交易紀錄", msg)
        self.assertIn("2006", msg)

    def test_includes_today_in_date_header(self):
        msg = self._capture(date)
        self.assertIn(self.today.isoformat(), msg, '日報標題應帶當天日期')


if __name__ == '__main__':
    unittest.main()
