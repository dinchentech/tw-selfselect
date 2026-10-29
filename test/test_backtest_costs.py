"""回歸測試：母專案的季度換股回測 (backtest_selector) 必須計入交易成本。

Bug 背景：backtest_selector 買賣僅以收盤價計算 shares/市值，未扣
手續費 (0.1425%) 與證交稅 (0.3%)，導致回測績效高估；
成本只在 TWO_BY_TWO 模式有計入。
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import stock_selector_grid as ssg


class TestBacktestTradingCosts(unittest.TestCase):

    def setUp(self):
        self._start, self._end = ssg.START_DATE, ssg.END_DATE
        ssg.START_DATE = "2023-07-01"
        ssg.END_DATE = "2024-06-30"
        self.params = dict(ssg.DEFAULT_PARAMS)
        self.params["use_ma_filter"] = False

    def tearDown(self):
        ssg.START_DATE, ssg.END_DATE = self._start, self._end

    def _price_df(self, first_half_close, second_half_close):
        """2024-03-29(含)前收 first_half_close，之後收 second_half_close。"""
        dates = pd.bdate_range("2023-07-01", "2024-06-30")
        closes = [first_half_close if d <= pd.Timestamp("2024-03-29")
                  else second_half_close for d in dates]
        return pd.DataFrame({
            "open": closes, "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes], "close": closes,
            "volume": [1_000_000] * len(dates),
        }, index=dates)



if __name__ == "__main__":
    unittest.main()
