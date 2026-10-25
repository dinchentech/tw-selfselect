"""core/candidate_pool.py — 「誠實候選池」（歷史市值前 N 大，無倖存者偏差）

為什麼需要：直接用「今天的市值排名」套到過去，等於用未來資訊選股
（現在市值大的公司，過去多半是因為後來漲了才變大），回測會嚴重高估。
本模組用 **歷史股本 × 當期收盤價** 重建每一期的真實市值排名。

資料來源：
  · `cache/inst_momentum/historical_shares.pkl` — {(代號, 'YYYY-MM'): 股本}
    由 `scripts/build_historical_shares.py` 產生（TWSE/FinMind 公開資料）。
  · 各股日線（`scripts/stock_selector_grid.load_stock`）。
"""
import pandas as pd


def build_quarterly_pool(historical: dict, all_data: dict, top_n: int = 150) -> dict:
    """回傳 { 'YYYY-MM': [sid 依當時市值排序取前 top_n] }。

    當時市值 = 歷史股本（historical_shares.pkl）× 當季點月份最後交易日收盤價。
    用於回測時取代「今天的市值排名套到過去」的固定池。
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
            mask = pd.to_datetime(df["date"]) <= month_end
            if not mask.any():
                continue
            px = df.loc[mask, "close"].iloc[-1]
            if px and px > 0:
                mcap[sid] = shares * px
        pools[qp] = sorted(mcap, key=mcap.get, reverse=True)[:top_n]
    return pools
