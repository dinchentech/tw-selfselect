# strategies/ma_cross.py
import pandas as pd

def ma_cross_strategy(df: pd.DataFrame, fast_period=9, slow_period=21, atr_period=14, atr_threshold=0.005) -> pd.DataFrame:
    """
    均線交叉策略 + ATR 波動度過濾：
    - 當快線（MA9）上穿慢線（MA21）且 ATR 波動足夠 → 買進
    - 當快線下穿慢線且 ATR 波動足夠 → 賣出
    - ATR 波動不足時跳過訊號，避免盤整期假訊號
    """
    df = df.copy()
    
    # 計算均線
    df['MA_Fast'] = df['close'].rolling(window=fast_period, min_periods=1).mean()
    df['MA_Slow'] = df['close'].rolling(window=slow_period, min_periods=1).mean()
    
    # 計算 ATR（平均真實波動幅度）
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=atr_period, min_periods=1).mean()
    
    # 訊號：1=買, -1=賣
    df['signal'] = 0
    df['prev_fast'] = df['MA_Fast'].shift(1)
    df['prev_slow'] = df['MA_Slow'].shift(1)
    
    # ATR 波動度過濾：ATR / 股價 < 門檻值 => 視為盤整，跳過訊號
    df['atr_ratio'] = df['ATR'] / df['close']
    df['volatile_enough'] = df['atr_ratio'] >= atr_threshold
    
    # 金叉：今日快 > 慢，昨日快 <= 慢 + ATR 過濾
    golden_cross = (df['MA_Fast'] > df['MA_Slow']) & (df['prev_fast'] <= df['prev_slow']) & df['volatile_enough']
    # 死叉：今日快 < 慢，昨日快 >= 慢 + ATR 過濾
    death_cross = (df['MA_Fast'] < df['MA_Slow']) & (df['prev_fast'] >= df['prev_slow']) & df['volatile_enough']
    
    df.loc[golden_cross, 'signal'] = 1
    df.loc[death_cross, 'signal'] = -1
    
    # 清理臨時欄位
    df.drop(['prev_fast', 'prev_slow', 'atr_ratio', 'volatile_enough'], axis=1, inplace=True)
    
    return df