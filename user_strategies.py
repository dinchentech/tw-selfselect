# user_strategies.py - 用戶自定義策略檔案
"""
此檔案提供 4 組用戶自訂策略範本（g1_strategy_1／g1_strategy_2／g2_strategy_1／g2_strategy_2）。
使用者可自由修改此檔案，無需更動主程式。

使用方式：
1. 修改下方的策略函式，或新增自己的函式
2. 把函式掛進檔尾的 USER_STRATEGY_MAP（左邊＝策略名、右邊＝函式）
3. 在 .env 的 PC_<代號> 條目把 strategy 填成該策略名，參數寫在同一個 JSON
   （參數還要列進 core/config_loader.py 的 STRATEGY_PARAM_KEYS，否則不會傳給函式）

例如：
PC_2504={"strategy":"g1_strategy_1","alloc":10,"buy_price":250,"sell_price":280}
PC_2330={"strategy":"g1_strategy_2","alloc":10,"k_threshold":20}
"""

import pandas as pd


# ==========================================
# 策略範本 1（g1_strategy_1）— 價格區間策略
# ==========================================
def price_band(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    策略範本 1（g1_strategy_1）- 價格區間低接高賣策略

    當價格低於買入價時發出買進訊號，高於賣出價時發出賣出訊號。
    適用於基本面看好、設定固定價格區間來回操作的股票（如 十銓 250↓買/280↑賣）。

    Parameters:
    - df: 包含 OHLCV 資料的 DataFrame
    - kwargs: 策略參數
        - buy_price: 買進觸發價 (預設 250)，現價 ≤ buy_price 時 signal=1
        - sell_price: 賣出觸發價 (預設 280)，現價 ≥ sell_price 時 signal=-1

    Returns:
    - DataFrame with 'signal' column (1=BUY, -1=SELL, 0=HOLD)
    """
    buy_price = kwargs.get('buy_price', 250)
    sell_price = kwargs.get('sell_price', 280)

    signals = pd.Series(0, index=df.index)

    buy_signal = df['close'] <= buy_price
    sell_signal = df['close'] >= sell_price

    signals[buy_signal] = 1
    signals[sell_signal] = -1

    return pd.DataFrame({'signal': signals}, index=df.index)


# ==========================================
# 策略範本 2（g1_strategy_2）— 週 KD 黃金交叉策略
# ==========================================
_WEEK_CAL = None


def _is_week_final(last_day) -> bool:
    """最後一根週 K 所在的週是否已走完（該週已無更晚的交易日）。

    實盤每輪都會用「今天」那根日 K 重算週 KD（selfselect_trader.py 會把即時價
    合成當日 K），所以未收盤的週也可能出現交叉；回測則把週訊號放在該週最後
    一個交易日。這裡擋掉「未收完的週」，讓兩邊一致。
    """
    global _WEEK_CAL
    try:
        if _WEEK_CAL is None:
            from core.trading_calendar import TradingCalendar
            _WEEK_CAL = TradingCalendar()
        return bool(_WEEK_CAL.is_last_trading_day_of_week(last_day))
    except Exception:
        # 日曆檔壞掉／不在 → 退回「週五才算封週」，不讓策略因日曆問題停擺
        return pd.Timestamp(last_day).weekday() == 4


def weekly_kd_golden_cross(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    策略範本 2（g1_strategy_2）- 週 KD 黃金交叉策略

    將日線資料重新採樣為週線，計算週 KD(9,3,3)，在低檔黃金交叉時買進，
    死亡交叉時賣出。含「持倉狀態機」：空手才買、持倉才賣，使訊號 +1/-1
    嚴格交替，一年一檔約 1~2 次訊號，適合中長期波段操作。

    訊號只放在「該週最後一個交易日」，且**未收完的週不發訊號**（實盤週 KD
    要等該週最後交易日 13:25–13:30 的收盤前窗口才判定；週五休市則提前到該週
    最後一個交易日）。

    Parameters:
    - df: 包含 OHLCV 資料的 DataFrame（日線，DatetimeIndex）
    - kwargs: 策略參數
        - k_period: KD 週期 (預設 9)
        - k_threshold: K 值低檔門檻，低於此值才考慮買進 (預設 30；可設 20 更嚴)
        - d_period: KD 平滑期數 (預設 3；標準遞迴 K=((d-1)*prev_K+RSV)/d)

    Returns:
    - DataFrame with 'signal' column (1=BUY, -1=SELL, 0=HOLD)
    """
    import numpy as np

    k_period = max(2, int(kwargs.get('k_period', 9)))
    d_period = max(2, int(kwargs.get('d_period', 3)))
    k_threshold = float(kwargs.get('k_threshold', 30))

    out = df.copy()
    signals = pd.Series(0, index=out.index)

    # 必需 OHLC 欄位 / 資料長度不足 → 全 0 訊號
    if not {'open', 'high', 'low', 'close'}.issubset(out.columns) or len(out) < 60:
        out['signal'] = signals
        return out

    # ── 日線 → 週線聚合（以最後交易日為週索引） ──
    weeks = pd.to_datetime(out.index).to_period('W')

    weekly_records = []
    for wl, group in out.groupby(weeks):
        if len(group) == 0:
            continue
        weekly_records.append({
            'last_day': group.index[-1],
            'open': group['open'].iloc[0],
            'high': group['high'].max(),
            'low': group['low'].min(),
            'close': group['close'].iloc[-1],
            'volume': group['volume'].sum() if 'volume' in group else 0,
        })

    weekly = pd.DataFrame(weekly_records).set_index('last_day')
    weekly.index = pd.to_datetime(weekly.index)

    if len(weekly) < k_period + d_period:
        out['signal'] = signals
        return out

    # ── 計算週 KD(k,d)：標準遞迴式 (K=((d-1)*prev_K+RSV)/d, D=((d-1)*prev_D+K)/d) ──
    low_n = weekly['low'].rolling(k_period, min_periods=k_period).min()
    high_n = weekly['high'].rolling(k_period, min_periods=k_period).max()

    rsv = pd.Series(np.nan, index=weekly.index)
    valid = (high_n - low_n).abs() > 1e-8
    rsv[valid] = 100.0 * (weekly.loc[valid, 'close'] - low_n[valid]) / (high_n[valid] - low_n[valid])
    rsv = rsv.clip(0, 100)

    alpha = 1.0 / d_period
    k_vals = np.full(len(weekly), np.nan)
    d_vals = np.full(len(weekly), np.nan)
    prev_k, prev_d = 50.0, 50.0
    for i, r in enumerate(rsv):
        if pd.isna(r):
            continue
        k_vals[i] = alpha * r + (1 - alpha) * prev_k
        d_vals[i] = alpha * k_vals[i] + (1 - alpha) * prev_d
        prev_k, prev_d = k_vals[i], d_vals[i]
    k = pd.Series(k_vals, index=weekly.index)
    d = pd.Series(d_vals, index=weekly.index)

    # ── 持倉狀態機：空手且低檔黃金交叉→買；持倉且死亡交叉→賣 ──
    weekly_sig = pd.Series(0, index=weekly.index)
    position = 0
    prev_kv = prev_dv = None
    for i in range(len(weekly)):
        ki, di = float(k.iloc[i]), float(d.iloc[i])
        if pd.isna(ki) or pd.isna(di):
            prev_kv, prev_dv = None, None
            continue
        if prev_kv is None:
            prev_kv, prev_dv = ki, di
            continue
        # 空手 + 低檔黃金交叉（K 上穿 D 且 K < 門檻）→ 買進
        if position == 0 and ki > di and prev_kv <= prev_dv and ki < k_threshold:
            weekly_sig.iloc[i] = 1
            position = 1
        # 持倉 + 死亡交叉（K 下穿 D）→ 賣出（含高檔鈍化後的回落）
        elif position == 1 and ki < di and prev_kv >= prev_dv:
            weekly_sig.iloc[i] = -1
            position = 0
        prev_kv, prev_dv = ki, di

    # ── 未收完的週不發訊號（只有資料最後一週可能未收完，已收盤週不受影響） ──
    if len(weekly) > 0 and not _is_week_final(weekly.index[-1]):
        weekly_sig.iloc[-1] = 0

    # ── 週線訊號映射回日線（放在該週最後一個交易日），其餘為 0 ──
    out['signal'] = weekly_sig.reindex(out.index).fillna(0).astype(int)
    return out


# ==========================================
# 策略範本 3（g2_strategy_1）
# ==========================================
def my_custom_momentum(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    策略範本 3（g2_strategy_1）- 自訂動能策略

    預設：價格動能策略 - 基於過去 N 日的漲跌幅判斷

    Parameters:
    - df: 包含 OHLCV 資料的 DataFrame
    - kwargs: 策略參數
        - lookback: 回看天數 (預設 5)
        - threshold: 漲跌幅門檻百分比 (預設 3)

    Returns:
    - DataFrame with 'signal' column (1=BUY, -1=SELL, 0=HOLD)
    """
    lookback = kwargs.get('lookback', 5)
    threshold = kwargs.get('threshold', 3)  # 百分比

    signals = pd.Series(0, index=df.index)

    if len(df) >= lookback + 1:
        # 計算 N 日漲跌幅
        pct_change = df['close'].pct_change(lookback) * 100

        # 動能策略訊號
        signals[(pct_change >= threshold) & (pct_change.shift(1) < threshold)] = 1  # 動能轉正
        signals[(pct_change <= -threshold) & (pct_change.shift(1) > -threshold)] = -1  # 動能轉負

    return pd.DataFrame({'signal': signals}, index=df.index)


# ==========================================
# 策略範本 4（g2_strategy_2）
# ==========================================
def my_custom_volume_price(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    策略範本 4（g2_strategy_2）- 自訂量價策略

    預設：量價配合策略 - 價格上漲 + 成交量放大 = 買進

    Parameters:
    - df: 包含 OHLCV 資料的 DataFrame
    - kwargs: 策略參數
        - ma_period: 價格均線週期 (預設 10)
        - volume_ma_period: 成交量均線週期 (預設 10)
        - volume_mult: 成交量放大倍數 (預設 1.5)

    Returns:
    - DataFrame with 'signal' column (1=BUY, -1=SELL, 0=HOLD)
    """
    ma_period = kwargs.get('ma_period', 10)
    volume_ma_period = kwargs.get('volume_ma_period', 10)
    volume_mult = kwargs.get('volume_mult', 1.5)

    signals = pd.Series(0, index=df.index)

    if len(df) >= ma_period:
        # 價格均線
        price_ma = df['close'].rolling(window=ma_period, min_periods=1).mean()
        # 成交量均線
        volume_ma = df['volume'].rolling(window=volume_ma_period, min_periods=1).mean()

        # 量價配合訊號
        # 價格站穩均線 + 成交量放大 = 買進
        buy_condition = (df['close'] > price_ma) & (df['volume'] >= volume_ma * volume_mult)
        # pandas 2.x：bool 序列用 shift(fill_value=False)，別用 .fillna(False)（會噴 FutureWarning）
        buy_entry = buy_condition & (~buy_condition.shift(1, fill_value=False))

        # 價格跌破均線 = 賣出
        sell_condition = df['close'] < price_ma
        sell_entry = sell_condition & (~sell_condition.shift(1, fill_value=False))

        signals[buy_entry] = 1
        signals[sell_entry] = -1

    return pd.DataFrame({'signal': signals}, index=df.index)


# ==========================================
# 用戶策略映射表（請勿修改此行以下）
# ==========================================
# 此映射表讓主程式（selfselect_trader.py）知道如何載入你的自訂策略
# 左邊＝PC_<代號> 的 strategy 名稱，右邊＝上方定義的函式
USER_STRATEGY_MAP = {
    # 策略範本 1–2（g1_* 插槽）
    'g1_strategy_1': price_band,
    'g1_strategy_2': weekly_kd_golden_cross,

    # 策略範本 3–4（g2_* 插槽）
    'g2_strategy_1': my_custom_momentum,
    'g2_strategy_2': my_custom_volume_price,
}

# 若要新增策略：寫一支函式（回傳含 signal 欄位的 DataFrame），加進上面的 USER_STRATEGY_MAP，
# 再把策略參數列進 core/config_loader.py 的 STRATEGY_PARAM_KEYS；
# 之後在 .env 用 PC_<代號>={"strategy":"你的名字", ...參數} 指定即可。
# G1_STRATEGY_1／G2_STRATEGY_1 這類舊專案的 .env 鍵在本專案沒有作用。