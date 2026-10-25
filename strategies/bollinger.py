# strategies/bollinger.py
import pandas as pd

def bollinger_reverse_strategy(df: pd.DataFrame, window=20, std_dev=2.0, rsi_period=5, rsi_low=30, rsi_high=70) -> pd.DataFrame:
    """
    布林通道反轉 + RSI 過濾：
    - 價格跌破下軌 + RSI < 30 → 買進
    - 價格漲破上軌 + RSI > 70 → 賣出
    """
    df = df.copy()
    
    # 計算布林通道
    df['BB_Middle'] = df['close'].rolling(window=window, min_periods=1).mean()
    df['BB_Std'] = df['close'].rolling(window=window, min_periods=1).std()
    df['BB_Upper'] = df['BB_Middle'] + (std_dev * df['BB_Std'])
    df['BB_Lower'] = df['BB_Middle'] - (std_dev * df['BB_Std'])
    
    # 計算 RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period, min_periods=1).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 訊號
    df['signal'] = 0
    buy_condition = (df['close'] < df['BB_Lower']) & (df['RSI'] < rsi_low)
    sell_condition = (df['close'] > df['BB_Upper']) & (df['RSI'] > rsi_high)
    
    df.loc[buy_condition, 'signal'] = 1
    df.loc[sell_condition, 'signal'] = -1
    
    return df