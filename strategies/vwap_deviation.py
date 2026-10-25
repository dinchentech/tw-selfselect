import pandas as pd
import numpy as np

def calculate_rsi(series, period=5):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_vwap(close: pd.Series, volume: pd.Series, window=20) -> pd.Series:
    """成交量加權平均價格 VWAP = Σ(close × volume) / Σ(volume)"""
    pv = (close * volume).rolling(window=window, min_periods=1).sum()
    vol = volume.rolling(window=window, min_periods=1).sum()
    return (pv / vol).fillna(close)  # volume=0 時 fallback 到 close

def vwap_deviation_strategy(df: pd.DataFrame, sigma_mult=1.5, rsi_period=5, rsi_low=30, rsi_high=70) -> pd.DataFrame:
    df = df.copy()
    df['VWAP'] = calculate_vwap(df['close'], df['volume'])
    
    df['RSI'] = calculate_rsi(df['close'], rsi_period)
    df['Deviation'] = df['close'] - df['VWAP']
    df['Std'] = df['Deviation'].rolling(window=20, min_periods=1).std().fillna(0)
    
    df['signal'] = 0
    long_condition = (df['close'] < df['VWAP'] - sigma_mult * df['Std']) & (df['RSI'] < rsi_low)
    short_condition = (df['close'] > df['VWAP'] + sigma_mult * df['Std']) & (df['RSI'] > rsi_high)
    df.loc[long_condition, 'signal'] = 1
    df.loc[short_condition, 'signal'] = -1
    return df