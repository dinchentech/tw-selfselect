"""strategies/auto_sensing.py — 型態感知策略路由器 + 自動感知策略

- route_strategy(df, as_of=None): 「型態感知策略路由器」。依「截至 as_of（預設最後一筆收盤）」
  的股價型態（股價 vs MA20/MA60、20日動能），回傳該股當下最合適的 4 策略之一
  (ma_cross / breakout / bollinger / vwap)。適合「每天開盤前或收盤後」呼叫一次（看你要用昨日收盤 or 今日收盤）。
- auto_sensing_strategy(df, as_of=None): 「自動感知」策略函式（**固定式**）。依「as_of(預設最後一天)」
  的型態『選定一個』策略，全程用該策略訊號；**不再每日重路由**。傳 as_of=進場日 → 買入時定策略、後續固定
  （與回測 `STRAT_MODE=form` 一致）。回傳含 signal 欄位 DataFrame，可 drop-in。若省略 as_of，則依最新(最後一天)型態選該策略。

規則（僅用 ≤ 當日資料，無前瞻）:
  趨勢(價>MA20 且 MA20>MA60 且 20日動能>0)  → 順勢: 20日動能>5% 用 breakout，否則 ma_cross
  否則(盤整/下跌)                          → 回歸: 價<MA20 用 bollinger(買低)，否則 vwap
"""
import pandas as pd

from strategies.ma_cross import ma_cross_strategy
from strategies.breakout import breakout_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.vwap_deviation import vwap_deviation_strategy

UNDERLYING = {
    "ma_cross": ma_cross_strategy,
    "breakout": breakout_strategy,
    "bollinger": bollinger_reverse_strategy,
    "vwap": vwap_deviation_strategy,
}


def route_strategy(df: pd.DataFrame, as_of=None) -> str:
    """型態感知策略路由器：回傳 ['ma_cross','breakout','bollinger','vwap'] 之一。

    df: 日K DataFrame（index=date，至少含 close 欄位；建議也有 open/high/low/volume）。
    as_of: 只看 ≤ as_of 的資料（日期 Timestamp）；None=用 df 最後一筆（適合收盤後）。
    """
    d = df if as_of is None else df.loc[:as_of]
    if len(d) == 0:
        return "ma_cross"
    close = d["close"].astype(float)
    cp = float(close.iloc[-1])
    if cp <= 0:
        return "ma_cross"
    ma20 = float(close.rolling(20, min_periods=1).mean().iloc[-1])
    ma60 = float(close.rolling(60, min_periods=1).mean().iloc[-1])
    ref = float(close.iloc[max(0, len(close) - 21)])
    mom20 = (cp / ref - 1.0) if ref > 0 else 0.0

    trend_up = (cp > ma20) and (ma20 > ma60) and (mom20 > 0)
    if trend_up:
        return "breakout" if mom20 > 0.05 else "ma_cross"
    return "bollinger" if cp < ma20 else "vwap"


def auto_sensing_strategy(df: pd.DataFrame, as_of=None, **kwargs) -> pd.DataFrame:
    """『固定式』型態感知策略：依 as_of(預設最後一天)的型態『選定一個』策略，全程用該策略訊號。

    傳入 as_of=進場日 → 買入時依型態定策略、之後固定(與回測 STRAT_MODE=form 一致)。
    不傳 as_of → 依最新(最後一天)型態選該策略。不再『每日重路由』。
    """
    strat = route_strategy(df, as_of)
    return UNDERLYING[strat](df)


if __name__ == "__main__":
    # 快速自檢：載入 2330 範例資料
    import os, sys
    # 專案根：不要寫死家目錄（container 內是 /app）
    _f = globals().get("__file__", "")
    _ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
             if _f and not str(_f).startswith("<") else os.getcwd())
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    if os.path.isdir(_ROOT):
        os.chdir(_ROOT)
    import scripts.stock_selector_grid as ssg
    df = ssg.load_stock("2330")
    print("2330 近3日路由:", [route_strategy(df, d) for d in df.index[-3:]])
    r = auto_sensing_strategy(df)
    print("auto_sensing_strategy 訊號分布:", r["signal"].value_counts().to_dict())
