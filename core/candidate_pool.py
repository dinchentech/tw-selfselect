"""core/candidate_pool.py — 「誠實候選池」（歷史市值前 N 大，無倖存者偏差）

為什麼需要：直接用「今天的市值排名」套到過去，等於用未來資訊選股
（現在市值大的公司，過去多半是因為後來漲了才變大），回測會嚴重高估。
本模組用 **歷史股本 × 當期收盤價** 重建每一期的真實市值排名。

資料來源：
  · `cache/inst_momentum/historical_shares.pkl` — {(代號, 'YYYY-MM'): 股本}
    由 `scripts/build_historical_shares.py` 產生（TWSE/FinMind 公開資料）。
  · `cache/inst_momentum/historical_shares_delisted.pkl` — 同上格式，補「2016-2025
    已下市個股」（`TMP/build_delisted.py` 產生）。**不補這份就有倖存者偏差**：
    池子只含今天還活著的股票，選股自然不會買到後來下市（含地雷）的公司。
  · 各股日線（`scripts/stock_selector_grid.load_stock`）。

⚠️ 新鮮度閘門（`max_stale_days`）：季點算市值時，若該股在季點月份最後交易日
之前超過 45 天就沒有成交價（＝已下市／長期停牌），視為「當時買不到」而排除。
這條同時保證：已下市個股只會影響**它還活著的那些季點**，不會滲進現在的實盤池。
"""
import os

import pandas as pd

SHARES_PKL = "cache/inst_momentum/historical_shares.pkl"
SHARES_DELISTED_PKL = "cache/inst_momentum/historical_shares_delisted.pkl"


def include_delisted() -> bool:
    """是否把已下市個股納入宇宙（`UNIVERSE_DELISTED=0` 可關，用於量化倖存者偏差）。"""
    return os.environ.get("UNIVERSE_DELISTED", "1").strip() not in ("0", "false", "False")


def _is_plain_stock(sid: str) -> bool:
    """只收 4 碼純數字、且排除 91xx 台灣存託憑證（TDR）。

    存活宇宙（`historical_shares.pkl`）本來就沒有 TDR／ETF／特別股，已下市清單卻含
    `9106`／`9157`／`9188` 這種 DR ⇒ 不排除的話等於兩邊口徑不一致（多了一類標的）。
    """
    sid = str(sid)
    return len(sid) == 4 and sid.isdigit() and not sid.startswith("91")


def load_historical_shares(path: str = SHARES_PKL, delisted_path: str = SHARES_DELISTED_PKL):
    """讀歷史股本；預設把已下市個股一起併進宇宙（回傳 (dict, sources)）。"""
    from core.cache_io import load_cache_or_raw

    hist, _ = load_cache_or_raw(path)
    hist = {k: v for k, v in dict(hist or {}).items() if _is_plain_stock(k[0])}
    src = ["listed"]
    if include_delisted():
        try:
            extra, _ = load_cache_or_raw(delisted_path)
        except FileNotFoundError:
            extra = None
        except Exception:
            extra = None
        if extra:
            extra = {k: v for k, v in dict(extra).items() if _is_plain_stock(k[0])}
            for k, v in extra.items():
                hist.setdefault(k, v)
            src.append(f"delisted({len({k[0] for k in extra})} 檔)")
    return hist, src


def build_quarterly_pool(historical: dict, all_data: dict, top_n: int = 150,
                         max_stale_days: int = 45) -> dict:
    """回傳 { 'YYYY-MM': [sid 依當時市值排序取前 top_n] }。

    當時市值 = 歷史股本（historical_shares.pkl）× 當季點月份最後交易日收盤價。
    用於回測時取代「今天的市值排名套到過去」的固定池。
    `max_stale_days`：季點最後交易日往前 45 天內必須有成交價，否則排除（見模組說明）。
    """
    pools = {}
    quarter_points = sorted({k[1] for k in historical})
    for qp in quarter_points:
        mcap = {}
        month_end = pd.Timestamp(qp + "-01") + pd.offsets.MonthEnd(0)
        for sid in {k[0] for k in historical if k[1] == qp}:
            shares = historical.get((sid, qp))
            df = all_data.get(sid)
            if not shares or df is None or df.empty:
                continue
            dates = pd.to_datetime(df["date"])
            mask = dates <= month_end
            if not mask.any():
                continue
            last = dates[mask].max()
            if max_stale_days and (month_end - last).days > max_stale_days:
                continue
            px = df.loc[mask, "close"].iloc[-1]
            if px and px > 0:
                mcap[sid] = shares * px
        pools[qp] = sorted(mcap, key=mcap.get, reverse=True)[:top_n]
    return pools
