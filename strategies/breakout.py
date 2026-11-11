# strategies/breakout.py
import pandas as pd

from strategies.indicators import atr as _atr, true_range as _true_range

def breakout_strategy(df: pd.DataFrame, lookback=20, atr_period=14, atr_threshold=0.01) -> pd.DataFrame:
    """
    突破交易策略（Donchian Channel + ATR 過濾）：
    - 價格突破 N 日最高 → 買進
    - 價格跌破 N 日最低 → 賣出
    - 用 ATR 過濾假突破（波動過小則忽略）

    ATR 口徑：`strategies/indicators.atr()`（Wilder TR 含跳空 ＋ Wilder 平滑），
    **不是**當日振幅的簡單平均。前 `atr_period−1` 根為 NaN ⇒ 該段不發訊號。
    """
    df = df.copy()

    # 計算 Donchian Channel
    df['Donchian_High'] = df['high'].rolling(window=lookback, min_periods=1).max()
    df['Donchian_Low'] = df['low'].rolling(window=lookback, min_periods=1).min()

    # 計算 ATR（Average True Range）——口徑見 strategies/indicators.py
    df['TR'] = _true_range(df)
    df['ATR'] = _atr(df, atr_period)
    
    # 訊號
    df['signal'] = 0
    # 突破上軌 + ATR 足夠大（避免窄幅震盪）
    buy_condition = (df['close'] > df['Donchian_High'].shift(1)) & (df['ATR'] > df['close'] * atr_threshold)
    # 跌破下軌
    sell_condition = (df['close'] < df['Donchian_Low'].shift(1)) & (df['ATR'] > df['close'] * atr_threshold)
    
    df.loc[buy_condition, 'signal'] = 1
    df.loc[sell_condition, 'signal'] = -1
    
    return df