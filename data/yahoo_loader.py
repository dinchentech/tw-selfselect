# data/yahoo_loader.py
import yfinance as yf
import pandas as pd

def load_historical_data(symbol: str, start: str = "2023-01-01") -> pd.DataFrame:
    """
    從 Yahoo Finance 載入歷史資料（自動處理除權息）
    
    :param symbol: 股票代號（如 "2330.TW"）
    :param start: 開始日期（格式: "YYYY-MM-DD"）
    :return: 包含 OHLCV 的 DataFrame
    """
    try:
        # auto_adjust=True 會自動處理除權息
        df = yf.download(symbol, start=start, auto_adjust=True)
        
        if df.empty:
            return df
            
        # 處理 yfinance 新版 MultiIndex columns（如 ('Close', '2330.TW')）
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 重新命名欄位為小寫（與系統其他部分一致）
        df = df.rename(columns={
            "Open": "open", 
            "High": "high", 
            "Low": "low", 
            "Close": "close", 
            "Volume": "volume"
        })
        return df
        
    except Exception as e:
        print(f"❌ 載入 {symbol} 資料失敗: {e}")
        return pd.DataFrame()