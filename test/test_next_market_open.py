"""迴歸測試：`get_next_market_open()` 必須跳過**國定假日**（不能只看週末）。

## 事故（2026-09-25 使用者當場發現）

VM log 2026-09-24 15:33 啟動時印：

```
💤 非交易時段，下次開盤 09/25 09:00，休眠中...
```

但 **9/25 是中秋節、9/28 是教師節**（`config/taiwan_holidays.json` 都有），下一個交易日是
**9/29（二）**。原實作 `core/live_utils.get_next_market_open()` 只跳過週末（`weekday() >= 5`）。

影響不只訊息：
1. 睡前報告與閒置訊息誤導使用者（使用者因此懷疑日曆壞了——日曆其實是對的）；
2. **更嚴重**：全輪替「買賣日」`logs/rotation_pending.json` 用同一個函式排定，而買賣日只在
   `buy_date == today_str` 當天成立 ⇒ **排到休市日就永遠等不到那次輪替買進**（例：長假前一天選股）。
"""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_utils import get_next_market_open   # noqa: E402
from core.trading_calendar import TradingCalendar  # noqa: E402

CAL = TradingCalendar()


def _dt(s):
    return datetime.datetime.fromisoformat(s)


class TestHolidayAware(unittest.TestCase):
    def test_after_close_before_holidays_skips_to_next_trading_day(self):
        """9/24（四）盤後 ⇒ 9/29（二），不可回 9/25（中秋）或 9/28（教師節）。"""
        got = get_next_market_open(_dt("2026-09-24 15:33:22"))
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-09-29 09:00")

    def test_holiday_morning_skips_to_next_trading_day(self):
        """9/25（休市）早上啟動 ⇒ 9/29 09:00（不是今天 09:00）。"""
        got = get_next_market_open(_dt("2026-09-25 08:01:13"))
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-09-29 09:00")

    def test_holiday_during_market_hours_is_not_immediate(self):
        """休市日的 09:00–13:30 **不可以**回『現在』（那會讓主迴圈以為盤中）。"""
        got = get_next_market_open(_dt("2026-09-25 10:00:00"))
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-09-29 09:00")

    def test_weekend_still_skipped(self):
        self.assertEqual(get_next_market_open(_dt("2026-09-26 10:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-09-29 09:00")
        self.assertEqual(get_next_market_open(_dt("2026-09-27 23:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-09-29 09:00")

    def test_holiday_across_weekend(self):
        """10/8（四）盤後 ⇒ 10/9 國慶日、10/10-11 週末 ⇒ 10/12（一）。"""
        self.assertEqual(get_next_market_open(_dt("2026-10-08 14:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-10-12 09:00")

    def test_next_open_is_never_a_holiday(self):
        """掃 9/20–10/31 的每個時刻：回傳日必須是交易日。"""
        d = datetime.date(2026, 9, 20)
        while d <= datetime.date(2026, 10, 31):
            for hm in ((8, 0), (10, 0), (14, 0), (20, 0)):
                got = get_next_market_open(datetime.datetime(d.year, d.month, d.day, *hm))
                self.assertTrue(CAL.is_trading_day(got.date()),
                                f"{d} {hm} → {got} 落在休市日")
            d += datetime.timedelta(days=1)


class TestNormalBehaviourUnchanged(unittest.TestCase):
    def test_before_open_returns_today_open(self):
        self.assertEqual(get_next_market_open(_dt("2026-09-29 08:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-09-29 09:00")

    def test_intraday_returns_now(self):
        got = get_next_market_open(_dt("2026-09-29 10:00:00"))
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-09-29 10:00")

    def test_after_close_normal_weekday(self):
        self.assertEqual(get_next_market_open(_dt("2026-09-29 14:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-09-30 09:00")

    def test_friday_after_close_to_monday(self):
        self.assertEqual(get_next_market_open(_dt("2026-10-02 14:00:00")).strftime("%Y-%m-%d %H:%M"),
                         "2026-10-05 09:00")

    def test_naive_and_aware_inputs(self):
        import pytz
        tw = pytz.timezone("Asia/Taipei")
        aware = tw.localize(_dt("2026-09-24 15:33:22"))
        got = get_next_market_open(aware)
        self.assertIsNotNone(got.tzinfo, "tz-aware 進、tz-aware 出")
        self.assertEqual(got.astimezone(tw).strftime("%Y-%m-%d %H:%M"), "2026-09-29 09:00")
        naive = get_next_market_open(_dt("2026-09-24 15:33:22"))
        self.assertIsNone(naive.tzinfo, "naive 進、naive 出（呼叫端在原行為上做減法）")
        self.assertEqual(naive.strftime("%Y-%m-%d %H:%M"), "2026-09-29 09:00")

    def test_broken_calendar_falls_back_to_weekday_only(self):
        """日曆壞掉不可拋例外（主迴圈不能停）：退回『只跳週末』且不炸。"""
        class Boom:
            def is_trading_day(self, d):
                raise RuntimeError("calendar broken")
        got = get_next_market_open(_dt("2026-09-24 15:33:22"), calendar=Boom())
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-09-25 09:00", "退回舊行為")


class TestConfigCalendarMatchesDocs(unittest.TestCase):
    def test_holidays_file_has_mid_autumn_and_teachers_day(self):
        import json
        data = json.loads((ROOT / "config" / "taiwan_holidays.json").read_text(encoding="utf-8"))
        hol = data.get("holidays") or []
        self.assertIn("2026-09-25", hol, "中秋節必須在日曆裡（日曆本來就是對的）")
        self.assertIn("2026-09-28", hol, "教師節必須在日曆裡")


if __name__ == "__main__":
    unittest.main(verbosity=2)
