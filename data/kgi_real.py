# data/kgi_real.py
import os
import requests
import pandas as pd
from datetime import datetime, timedelta

class KGIRealAPI:
    def __init__(self):
        self.api_key = os.getenv("KGI_API_KEY")
        self.api_secret = os.getenv("KGI_API_SECRET")
        self.base_url = "https://api.kgi.com.tw"  # 實際 URL 需向凱基確認
        
        if not self.api_key or not self.api_secret:
            raise ValueError("❌ 未設定 KGI_API_KEY 或 KGI_API_SECRET")
        
        # 驗證 API 權限
        self._verify_connection()
    
    def _verify_connection(self):
        """驗證 API 連接"""
        try:
            response = self._make_request("GET", "/account/info")
            if response.get("status") == "success":
                print("✅ 凱基 API 連接成功")
            else:
                raise Exception("API 驗證失敗")
        except Exception as e:
            print(f"❌ 凱基 API 連接失敗: {e}")
            raise
    
    def _make_request(self, method, endpoint, params=None, data=None):
        """發送 API 請求（需根據凱基實際規格調整）"""
        url = self.base_url + endpoint
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=10)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ API 請求失敗: {e}")
            return {"error": str(e)}
    
    def get_current_price(self, symbol: str) -> float:
        """取得當前價格"""
        response = self._make_request("GET", f"/market/quote/{symbol}")
        if "error" not in response:
            return float(response.get("last_price", 0))
        return 0.0
    
    def get_minute_bars(self, symbol: str, minutes: int = 60) -> pd.DataFrame:
        """取得分鐘 K 線資料"""
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        
        response = self._make_request("GET", f"/market/bars/{symbol}", params={
            "start": start_time,
            "end": end_time,
            "interval": "1m"
        })
        
        if "error" in response or not response.get("bars"):
            return pd.DataFrame()
        
        bars = response["bars"]
        df = pd.DataFrame(bars)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        return df[['open', 'high', 'low', 'close', 'volume']]
    
    def place_order(self, symbol: str, side: str, quantity: int, order_type: str = "market"):
        """下單"""
        data = {
            "symbol": symbol,
            "side": side.lower(),  # "buy" or "sell"
            "quantity": quantity,
            "order_type": order_type,
            "time_in_force": "day"
        }
        
        response = self._make_request("POST", "/orders", data=data)
        if "error" not in response:
            print(f"✅ 真實下單成功: {side} {symbol} {quantity} 股")
            return response
        else:
            print(f"❌ 下單失敗: {response.get('error', 'Unknown error')}")
            return response
    
    def get_account_info(self):
        """取得帳戶資訊（用於風險控管）"""
        return self._make_request("GET", "/account/info")
    def check_fill(self, symbol, action, order_ret, requested):
        """KGI 真實 API 尚未實作委託/成交查詢（需向凱基確認規格）→ 回傳 None 維持原行為"""
        return None
