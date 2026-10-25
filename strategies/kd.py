# strategies/kd.py
import pandas as pd

def kd_strategy(df: pd.DataFrame, k_period=9, d_period=3, oversold=30, overbought=70) -> pd.DataFrame:
    """
    KD 隨機指標策略（Stochastic Oscillator）：
    - RSV = (C - L9) / (H9 - L9) * 100
    - %K = 3-period SMA of RSV
    - %D = 3-period SMA of %K

    買進條件（空手時）：%K < oversold（超賣）且 %K 向上穿越 %D
    賣出條件（持有時）：%K > overbought（超買）且 %K 向下穿越 %D
    """
    df = df.copy()

    low_min = df['low'].rolling(window=k_period, min_periods=1).min()
    high_max = df['high'].rolling(window=k_period, min_periods=1).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)

    df['K'] = rsv.rolling(window=d_period, min_periods=1).mean()
    df['D'] = df['K'].rolling(window=d_period, min_periods=1).mean()

    df['signal'] = 0
    prev_K = df['K'].shift(1)
    prev_D = df['D'].shift(1)

    # 買進條件：空手、K 在超賣區、K 向上穿越 D
    buy_cond = (
        (df['K'] < oversold) &
        (prev_K <= prev_D) &
        (df['K'] > df['D'])
    )
    # 賣出條件：持有、K 在超買區、K 向下穿越 D
    sell_cond = (
        (df['K'] > overbought) &
        (prev_K >= prev_D) &
        (df['K'] < df['D'])
    )

    # 狀態機：空手才進場，持有才出場，避免重複訊號
    position = 0
    for i in range(len(df)):
        if position == 0 and buy_cond.iloc[i]:
            df.loc[df.index[i], 'signal'] = 1
            position = 1
        elif position == 1 and sell_cond.iloc[i]:
            df.loc[df.index[i], 'signal'] = -1
            position = 0

    df.drop(['K', 'D'], axis=1, inplace=True)

    return df
