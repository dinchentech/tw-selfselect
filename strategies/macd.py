import pandas as pd

def macd_strategy(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df['close'].ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False, min_periods=1).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean()

    prev_macd = macd_line.shift(1)
    prev_signal = signal_line.shift(1)

    df['signal'] = 0
    golden = (macd_line > signal_line) & (prev_macd <= prev_signal)
    death = (macd_line < signal_line) & (prev_macd >= prev_signal)
    df.loc[golden, 'signal'] = 1
    df.loc[death, 'signal'] = -1

    return df
