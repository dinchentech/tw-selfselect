# strategies/indicators.py
"""共用技術指標 —— 全專案 ATR 口徑的唯一真相（2026-11-05 建立）。

為什麼要獨立成模組：`ma_cross` 與 `breakout` 原本各寫一份 ATR，而 `breakout`
那份把「捕跳空」的項寫成當日收盤（`|high−close|`、`|low−close|`）而不是前一日收盤，
因為 `close` 恆落在 `[low, high]` 內 ⇒ 那兩項永遠贏不過 `high−low`，
整個 max 退化為「當日振幅」、跳空完全不算（實測 28.5 萬根只有 10 根例外，全是還原價瑕疵）。
兩份實作分家後就沒有人發現。抽成一份後「同名不同義」不可能再發生。

口徑（Wilder 1978，《New Concepts in Technical Trading Systems》；與 TA-Lib
`TA_TRANGE` + `TA_RMA`、TradingView `ta.tr` + `ta.rma(…,14)` 一致）：

    TR  = max( high − low , |high − prev_close| , |low − prev_close| )     首根無前收 ⇒ high − low
    ATR = Wilder 平滑（RMA/SMMA：α = 1/N，用前 N 根 TR 的簡單平均起種）

⚠️ 兩點與舊行為不同（刻意）：
1. TR **含跳空缺口**（舊 `breakout` 不含 ⇒ ATR 系統性低估 3%~35%）。
2. ATR 是 **Wilder 平滑**、不是簡單移動平均（舊兩支都用 `rolling().mean()`）。
   RMA 比同週期 SMA 慢、記憶長 ⇒ 波動由低轉高時門檻開得較慢，反之關得也較慢。
3. **前 N−1 根是 NaN**（沒有足夠的 TR 可起種）⇒ 該期間 `ATR > close × threshold`
   一律為 False、不會發訊號。實盤日 K 取 260 天、回測快取有 prepend 歷史，
   實際影響只落在「新上市股剛掛牌」那段。
"""
import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """Wilder True Range（含跳空）。首根沒有前一日收盤 ⇒ 用 `high − low`。"""
    high, low, close = df['high'], df['low'], df['close']
    hl = high - low
    prev_close = close.shift(1)
    tr = pd.concat([hl, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    if len(tr):
        tr = tr.copy()
        tr.iloc[0] = hl.iloc[0]
    return tr


def wilder_smooth(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑（RMA／SMMA）：α = 1/period，用前 period 根的簡單平均起種。

    起種做法與 TA-Lib 相同：第 `period−1` 根＝前 `period` 根的算術平均，
    之後 `RMA[i] = α·x[i] + (1−α)·RMA[i−1]`。
    """
    period = max(1, int(period))
    s = series.astype(float)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) < period:
        return out
    head = s.iloc[:period]
    if head.isna().any():
        return out
    body = s.iloc[period - 1:].copy()
    body.iloc[0] = float(head.mean())          # ← 起種：塞進 SMA
    out.loc[body.index] = body.ewm(alpha=1.0 / period, adjust=False).mean()
    return out


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR（Wilder 平滑的 TR）＝ TA-Lib `TA_ATR` 口徑。前 `period−1` 根為 NaN。"""
    return wilder_smooth(true_range(df), period)
