# test/test_weekly_kd.py — g1_strategy_2 週KD黃金交叉策略回歸測試
"""
驗證 user_strategies.py 的 weekly_kd_golden_cross 符合「週 KD 黃金交叉」設計：

1. 持倉狀態機：非零訊號必須嚴格 +1/-1 交替（買進→賣出→買進…），
   且賣出數 ≤ 買進數+1（空手才買、持倉才賣，不會裸賣出）。
2. 低頻：一檔一兩年僅少量訊號（對照課程：2454 預設約 4 筆）。
3. 健壯性：資料不足不崩潰、回傳含 signal、index 與輸入一致、
   自訂參數（k_period/k_threshold/d_period）可跑。
4. 訊號語意：低檔門檻（K < k_threshold）真的擋掉高檔交叉；高檔鈍化時
   一路抱牢（不提早賣）：模型上漲段只能看到 1 個買訊、0 個賣訊。
5. 週收盤對齊：訊號只落在「該週最後一個交易日」；**未收完的週不發訊號**
   （實盤會用當週半成品週 K 重算，若不擋就會在週三進場、與回測不一致）。

執行：
    python -m unittest test.test_weekly_kd
    python -m pytest test/test_weekly_kd.py
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np

from core.trading_calendar import TradingCalendar
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


def _make_rise_after_decline_df():
    """前 300 根緩跌、後 400 根指數型單邊上漲（high=close、low=close*0.999）。

    這種「漲不停」的走勢會把 K/D 一路推到高檔（鈍化）；KD 策略在此不該賣，
    只有走勢真的死亡交叉才出場。期間共 700 個交易日，最後一根剛好是週五。
    """
    n = 700
    dates = pd.date_range('2018-01-01', periods=n, freq='B')
    close = np.concatenate([
        200 * np.exp(-np.linspace(0, 0.6, 300)),
        200 * np.exp(-0.6) * np.exp(np.linspace(0, 0.45, n - 300)),
    ])
    assert dates[-1].weekday() == 4, '資料最後一根要是週五（已收完的週）'
    return pd.DataFrame({
        'open': close, 'high': close, 'low': close * 0.999,
        'close': close, 'volume': 1000,
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

    # ── 低檔門檻 ──────────────────────────────────────────────────────────

    def test_threshold_gate_controls_buys(self):
        """K < k_threshold 的門檻真的生效：0＝永不買；門檻放寬只會多買、不會少買。"""
        df = _make_choppy_df()
        buys = {
            t: int((weekly_kd_golden_cross(df.copy(), k_threshold=t)['signal'] == 1).sum())
            for t in (0, 30, 100)
        }
        self.assertEqual(buys[0], 0, 'k_threshold=0 時不可能有 K<0，不應買進')
        self.assertGreater(buys[30], 0, '門檻 30 應至少有一次低檔黃金交叉')
        self.assertGreaterEqual(buys[100], buys[30], '門檻放寬（100）買進次數不應少於 30')

    def test_high_zone_hold_keeps_position(self):
        """高檔鈍化一路抱牢：底部反轉後長段單邊上漲，只能有 1 買、0 賣。"""
        df = _make_rise_after_decline_df()
        out = weekly_kd_golden_cross(df)
        seq = out.loc[out['signal'] != 0, 'signal'].tolist()

        self.assertEqual(seq, [1], f'上漲段不該出現死亡交叉賣出，實際訊號序列={seq}')

    # ── 週收盤對齊 ────────────────────────────────────────────────────────

    def test_signals_only_on_week_last_day(self):
        """每個非零訊號都必須落在該週（週一～週日）最後一個交易日。"""
        df = _make_choppy_df()
        out = weekly_kd_golden_cross(df)
        last_day_by_week = {
            d.to_period('W'): d for d in df.index
        }  # 迭代是時間序，同一週後面的日期會覆蓋前面 → 最後剩最後一個交易日
        signal_days = out.index[out['signal'] != 0]

        self.assertGreater(len(signal_days), 0, '此資料應產生訊號')
        for d in signal_days:
            self.assertEqual(d, last_day_by_week[d.to_period('W')],
                             f'訊號 {d} 不在該週最後一個交易日 {last_day_by_week[d.to_period("W")]}')

    def test_partial_week_emits_no_signal(self):
        """未收完的週不發訊號：同一段行情截到週一不買、截到週五才買。

        2019-02-18（週一）在未擋封週的版本會觸發低檔黃金交叉；但當週還沒收盤，
        實盤若在此時進場就等於用半成品週 K 做決策（回測不會有這筆）。
        """
        df = _make_choppy_df()
        monday = pd.Timestamp('2019-02-18')
        friday = pd.Timestamp('2019-02-22')

        out_mon = weekly_kd_golden_cross(df.loc[:monday].copy())
        self.assertEqual(int(out_mon['signal'].iloc[-1]), 0,
                         '週一（當週未收完）不得發買訊')

        out_fri = weekly_kd_golden_cross(df.loc[:friday].copy())
        self.assertEqual(int(out_fri['signal'].iloc[-1]), 1,
                         '同週週五（已收完）應正常發出買訊')

    def test_last_trading_day_of_week_helper(self):
        """TradingCalendar：週五放假時，該週最後交易日提前到週四。"""
        with tempfile.TemporaryDirectory() as td:
            holidays = Path(td) / 'holidays.json'
            holidays.write_text(
                json.dumps({'holidays': ['2026-10-23'], 'makeup_workdays': []}),
                encoding='utf-8')
            cal = TradingCalendar(holidays)

            self.assertTrue(cal.is_last_trading_day_of_week(date(2026, 10, 22)))
            self.assertFalse(cal.is_last_trading_day_of_week(date(2026, 10, 21)))
            self.assertFalse(cal.is_last_trading_day_of_week(date(2026, 10, 23)),
                             '休市日不可能是該週最後交易日')
            self.assertTrue(cal.is_last_trading_day_of_week('2026-10-22'),
                            'ISO 字串也要吃得下')


if __name__ == '__main__':
    unittest.main()
