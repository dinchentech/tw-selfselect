import unittest
import pandas as pd
import numpy as np
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.breakout import breakout_strategy

class TestStrategies(unittest.TestCase):
    
    def setUp(self):
        """建立測試資料"""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        prices = 100 + np.random.randn(100).cumsum()
        
        self.test_data = pd.DataFrame({
            'open': prices * 0.995,
            'high': prices * 1.005,
            'low': prices * 0.990,
            'close': prices,
            'volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)
    
    def test_vwap_strategy(self):
        """測試 VWAP 策略"""
        df = vwap_deviation_strategy(self.test_data, sigma_mult=1.0, rsi_period=5)
        self.assertIn('signal', df.columns)
        signal = df['signal'].iloc[-1]
        self.assertIn(signal, [-1, 0, 1])
    
    def test_ma_cross_strategy(self):
        """測試均線交叉策略"""
        df = ma_cross_strategy(self.test_data, fast_period=5, slow_period=10)
        self.assertIn('signal', df.columns)
        signal = df['signal'].iloc[-1]
        self.assertIn(signal, [-1, 0, 1])
    
    def test_bollinger_strategy(self):
        """測試布林通道策略"""
        df = bollinger_reverse_strategy(self.test_data, window=10, std_dev=1.5)
        self.assertIn('signal', df.columns)
        signal = df['signal'].iloc[-1]
        self.assertIn(signal, [-1, 0, 1])
    
    def test_breakout_strategy(self):
        """測試突破策略"""
        df = breakout_strategy(self.test_data, lookback=10)
        self.assertIn('signal', df.columns)
        signal = df['signal'].iloc[-1]
        self.assertIn(signal, [-1, 0, 1])

if __name__ == '__main__':
    unittest.main()
