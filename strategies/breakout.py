# strategies/breakout.py
"""突破交易策略（Donchian 20 日通道 ＋ ATR 過濾）。

## 出場確認變體（2026-11-24，兩者皆**預設關閉**、由 `.env` 開關；回測同一支函式）

起因：2603 在 2026-11-20 13:25 依規則出場（報價 236.00 跌破 20 日低點 236.50、−14.9%），
之後 11/23 收 241、11/24 收 257 ⇒ 使用者問「單日跌破就出」是不是太急，要求比較兩個變體：

- `BREAKOUT_CONFIRM_DAYS=2`（變體 1）：要**連續 2 日**收盤都在（各自前 20 日）低點之下才賣。
- `BREAKOUT_MA_CONFIRM=1`（變體 2）：跌破 20 日低點**且**收盤 < MA20 才賣（多一道趨勢確認）。
- 兩個都設 ⇒ 兩個條件都要成立。

未設定（預設 `0`）⇒ 行為與 2026-10 以來的版本完全相同（單日跌破就賣）。
"""
import os

import pandas as pd

from strategies.indicators import atr as _atr, true_range as _true_range


def _confirm_days() -> int:
    """連續確認天數（0/1 ＝ 不啟用；≥2 ＝ 啟用）。壞值回 0（不讓環境變數壞掉改變交易）。"""
    try:
        return max(0, int(os.getenv("BREAKOUT_CONFIRM_DAYS", "0") or 0))
    except (TypeError, ValueError):
        return 0


def _ma_confirm() -> bool:
    """是否要求「收盤 < MA20」的第二道確認（`BREAKOUT_MA_CONFIRM=1/true/yes/on`）。"""
    return str(os.getenv("BREAKOUT_MA_CONFIRM", "0") or "").strip().lower() in ("1", "true", "yes", "on")


def breakout_strategy(df: pd.DataFrame, lookback=20, atr_period=14, atr_threshold=0.01) -> pd.DataFrame:
    """
    突破交易策略（Donchian Channel + ATR 過濾）：
    - 價格突破 N 日最高 → 買進
    - 價格跌破 N 日最低 → 賣出
    - 用 ATR 過濾假突破（波動過小則忽略）

    ATR 口徑：`strategies/indicators.atr()`（Wilder TR 含跳空 ＋ Wilder 平滑），
    **不是**當日振幅的簡單平均。前 `atr_period−1` 根為 NaN ⇒ 該段不發訊號。

    出場確認（選配，見模組說明）：`BREAKOUT_CONFIRM_DAYS`／`BREAKOUT_MA_CONFIRM`。
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
    below_low = df['close'] < df['Donchian_Low'].shift(1)

    # ── 出場確認（2026-11-24，預設關閉；見模組說明）────────────────────────
    _cd = _confirm_days()
    if _cd >= 2:
        # 連續 N 日「各自跌破前 20 日低點」才算（第 N 天才出場）
        confirmed = below_low.rolling(window=_cd, min_periods=_cd).sum() >= _cd
        below_low = confirmed.fillna(False)
    if _ma_confirm():
        _ma20 = df['close'].rolling(window=20, min_periods=20).mean()
        below_low = below_low & (df['close'] < _ma20)
    sell_condition = below_low & (df['ATR'] > df['close'] * atr_threshold)

    df.loc[buy_condition, 'signal'] = 1
    df.loc[sell_condition, 'signal'] = -1

    return df
