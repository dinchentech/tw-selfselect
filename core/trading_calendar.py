"""
core/trading_calendar.py — 台灣股市交易日曆
判斷是否為交易日（週末 + 休市日 + 補班日）
"""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path


class TradingCalendar:
    def __init__(self, holidays_file=None):
        if holidays_file is None:
            holidays_file = Path(__file__).parent.parent / 'config' / 'taiwan_holidays.json'
        self._holidays_file = Path(holidays_file)
        self._load_data()

    @lru_cache(maxsize=1)
    def _load_data(self):
        if self._holidays_file.exists():
            data = json.loads(self._holidays_file.read_text(encoding='utf-8'))
            self._holidays = set(data.get('holidays', []))
            self._makeup_days = set(data.get('makeup_workdays', []))
        else:
            self._holidays = set()
            self._makeup_days = set()

    def is_trading_day(self, d):
        ds = d.isoformat() if isinstance(d, date) else d
        if ds in self._makeup_days:
            return True
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if d.weekday() >= 5:
            return False
        if ds in self._holidays:
            return False
        return True

    def get_nth_trading_day(self, year, month, n):
        """回傳該月第 n 個交易日；n=-1 時回傳該月最後交易日（月尾）。"""
        d = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        if n == -1:
            last = None
            while d < end:
                if self.is_trading_day(d):
                    last = d
                d += timedelta(days=1)
            return last
        count = 0
        while d < end:
            if self.is_trading_day(d):
                count += 1
                if count == n:
                    return d
            d += timedelta(days=1)
        return None

    def get_first_trading_day(self, year, month):
        return self.get_nth_trading_day(year, month, 1)
