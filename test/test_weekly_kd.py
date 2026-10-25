# test/test_weekly_kd.py — g1_strategy_2 週KD黃金交叉策略回歸測試
"""
驗證 user_strategies.py 的 weekly_kd_golden_cross 符合「週 KD 黃金交叉」設計：

1. 持倉狀態機：非零訊號必須嚴格 +1/-1 交替（買進→賣出→買進…），
   且賣出數 ≤ 買進數+1（空手才買、持倉才賣，不會裸賣出）。
2. 低頻：一檔一兩年僅少量訊號（對照課程：2454 預設約 4 筆）。
3. 健壯性：資料不足不崩潰、回傳含 signal、index 與輸入一致、
   自訂參數（k_period/k_threshold/d_period）可跑。

執行：python -m unittest test.test_weekly_kd
"""
import unittest
import pandas as pd
import numpy as np

from user_strategies import weekly_kd_golden_cross


def _make_choppy_df(n=1600, seed=123):
    """製造會讓 KD 在低檔反覆黃金交叉的震盪資料（判別狀態機是否生效）。"""
    np.random.seed(seed)
    dates = pd.date_range('2018-01-01', periods=n, freq='B')
    close = (100
             + 8 * np.sin(np.linspace(0, 20, n))
             + np.concatenate([np.random.randn(n // 2) * 2,
                               np.random.randn(n - n // 2) * 2]))
    return pd.DataFrame({
        'open':  close * 0.999,
        'high':  close + np.random.rand(n) * 1.5,
        'low':   close - np.random.rand(n) * 1.5,
        'close': close,
        'volume': np.random.randint(1_000_000, 5_000_000, n),
    }, index=dates)


class TestWeeklyKDGoldenCross(unittest.TestCase):

    def test_nonzero_signals_strictly_alternate(self):
        """非零訊號必須 +1/-1 嚴格交替（持倉狀態機）。現行裸交叉實作會違反。"""
        df = _make_choppy_df()
        out = weekly_kd_golden_cross(df)
        seq = out.loc[out['signal'] != 0, 'signal'].tolist()

        self.assertGreater(len(seq), 0, '此資料應產生訊號')
        last = 0
        for s in seq:
            self.assertNotEqual(s, last,
                                f'非零訊號 {s} 重複上一個非零訊號 {last}，未先有反向訊號（狀態機失效）')
            last = s

    def test_sell_count_never_exceeds_buys_plus_one(self):
        """持倉狀態機：賣出數 ≤ 買進數+1（空手才買、持倉才賣）。現行會裸賣出大量 -1。"""
        df = _make_choppy_df()
        out = weekly_kd_golden_cross(df)
        buys = int((out['signal'] == 1).sum())
        sells = int((out['signal'] == -1).sum())

        self.assertGreater(buys, 0, '此資料應至少有 1 次買進')
        self.assertLessEqual(sells, buys + 1,
                             f'賣出數({sells}) 超過 買進數({buys})+1，出現未先買進的賣出')

    def test_low_signal_frequency(self):
        """低頻：非零訊號總數應遠小於週數（一檔一兩年僅少量訊號）。"""
        df = _make_choppy_df()
        weeks = len(df.index.to_period('W').unique())
        out = weekly_kd_golden_cross(df)
        total_signals = int((out['signal'] != 0).sum())

        # 超過 weeks/8 就太頻繁（約每 8 週訊號一次）
        self.assertLess(total_signals, max(1, weeks // 8),
                        f'訊號過於頻繁：{total_signals} 個訊號 / 約 {weeks} 週')

    def test_no_sell_without_prior_buy_order(self):
        """訊號序列中每個賣出之前必須先有買進（含跨段），且不限持倉起點。"""
        df = _make_choppy_df()
        out = weekly_kd_golden_cross(df)
        seq = out.loc[out['signal'] != 0, 'signal'].tolist()

        buys_seen = 0
        for i, s in enumerate(seq):
            if s == 1:
                buys_seen += 1
            elif s == -1:
                self.assertGreater(buys_seen, 0,
                                   f'第 {i} 個非零訊號為賣出，但先前從未買進（裸賣出）')

    def test_short_data_returns_zero_signal(self):
        """資料不足（<60 列）應回傳全 0 訊號且不拋例外。"""
        dates = pd.date_range('2023-01-01', periods=40, freq='B')
        df = pd.DataFrame({
            'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0, 'volume': 1000,
        }, index=dates)
        out = weekly_kd_golden_cross(df)
        self.assertIn('signal', out.columns)
        self.assertTrue((out['signal'] == 0).all(), '資料不足時應全為 0')

    def test_output_has_signal_and_same_index(self):
        """回傳 DataFrame 含 signal 欄位，index 與輸入一致。"""
        df = _make_choppy_df(n=300)
        out = weekly_kd_golden_cross(df)
        self.assertIn('signal', out.columns)
        self.assertTrue(out.index.equals(df.index))

    def test_custom_params_runs(self):
        """自訂參數（k_period=12, k_threshold=25, d_period=5，課程建議參數）可正常執行。"""
        df = _make_choppy_df()
        out = weekly_kd_golden_cross(df, k_period=12, k_threshold=25, d_period=5)
        self.assertIn('signal', out.columns)
        self.assertTrue(out.index.equals(df.index))


if __name__ == '__main__':
    unittest.main()
