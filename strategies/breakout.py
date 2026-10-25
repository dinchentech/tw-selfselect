# strategies/breakout.py
import pandas as pd

def breakout_strategy(df: pd.DataFrame, lookback=20, atr_period=14, atr_threshold=0.01) -> pd.DataFrame:
    """
    突破交易策略（Donchian Channel + ATR 過濾）：
    - 價格突破 N 日最高 → 買進
    - 價格跌破 N 日最低 → 賣出
    - 用 ATR 過濾假突破（波動過小則忽略）
    """
    df = df.copy()
    
    # 計算 Donchian Channel
    df['Donchian_High'] = df['high'].rolling(window=lookback, min_periods=1).max()
    df['Donchian_Low'] = df['low'].rolling(window=lookback, min_periods=1).min()
    
    # 計算 ATR（Average True Range）
    df['TR'] = df['high'] - df['low']
    df['TR'] = df[['TR', 'high', 'low', 'close']].apply(
        lambda row: max(row['TR'], abs(row['high'] - row['close']), abs(row['low'] - row['close'])), axis=1
    )
    df['ATR'] = df['TR'].rolling(window=atr_period, min_periods=1).mean()
    
    # 訊號
    df['signal'] = 0
    # 突破上軌 + ATR 足夠大（避免窄幅震盪）
    buy_condition = (df['close'] > df['Donchian_High'].shift(1)) & (df['ATR'] > df['close'] * atr_threshold)
    # 跌破下軌
    sell_condition = (df['close'] < df['Donchian_Low'].shift(1)) & (df['ATR'] > df['close'] * atr_threshold)
    
    df.loc[buy_condition, 'signal'] = 1
    df.loc[sell_condition, 'signal'] = -1
    
    return df