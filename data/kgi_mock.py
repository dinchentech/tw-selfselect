import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class KGIMockAPI:
    def __init__(self):
        self.order_count = 0
        self.positions = {}
    
    def get_current_price(self, symbol: str) -> float:
        """模擬取得當前價格"""
        # 實際應連接真實 API
        base_prices = {"2330": 680.0, "0050": 125.5, "2454": 1100.0}
        base = base_prices.get(symbol, 100.0)
        # 加入隨機波動
        return base * (1 + np.random.normal(0, 0.005))
    
    def get_historical_data(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """模擬取得歷史資料（用於實盤累積）"""
        base_price = self.get_current_price(symbol)
        dates = [datetime.now() - timedelta(days=i) for i in range(days)][::-1]
        
        prices = [base_price]
        for _ in range(1, days):
            prices.append(prices[-1] * (1 + np.random.normal(0, 0.02)))
        
        df = pd.DataFrame({
            'date': dates,
            'open': [p * (1 - np.random.uniform(0, 0.01)) for p in prices],
            'high': [p * (1 + np.random.uniform(0, 0.02)) for p in prices],
            'low': [p * (1 - np.random.uniform(0, 0.02)) for p in prices],
            'close': prices,
            'volume': [np.random.randint(1000000, 5000000) for _ in prices]
        })
        df = df.set_index('date')
        return df
    
    def place_order(self, symbol: str, action: str, quantity: int):
        """模擬下單"""
        self.order_count += 1
        price = self.get_current_price(symbol)
        print(f"📦 模擬下單 #{self.order_count}: {action} {symbol} {quantity} 股 @ {price:.2f}")
        return {"order_id": self.order_count, "status": "filled", "price": price}
    def check_fill(self, symbol, action, order_ret, requested):
        """模擬：一律全數成交"""
        return requested
