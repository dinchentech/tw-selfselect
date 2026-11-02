#!/usr/bin/env python3
"""make_cap_mix.py · 選股結構分析（大型／中型／小型股占比 × 各策略占比）＋ 直式 PPT

資料來源（全部是真的跑出來的回測，不是估的）：
  1. `results/plan2_monthly_3group_2022-01-01_2026-10-23_immediate_mf200_park0050_scorezscore_pool100.json`
     —`scripts/backtest_plan2_monthly_3group.py` 在實盤口徑（`PROFILE=default`＋`PRESET=revenue`＋
     `STRAT_MODE=form`＋`IMM_OVERHEAT=1`）跑 2022-01-01～2026-10-23 的輸出，裡面有每月 `selection_log`。
  2. 市值分類：`core.candidate_pool.build_quarterly_pool()`（歷史股本 × 當期收盤）算**全宇宙市值排名**
     ⇒ 大型＝前 50 名、中型＝51～150 名、小型＝151 名以後（台股通俗切法，約等於台灣 50／中小型／小型）。
  3. 策略：複製回測 `STRAT_MODE=form` 的 `pick_strategy_by_form()` 規則（只用選股日當天以前的資料，無前瞻）
     —— 順勢＝ma_cross／breakout、回歸＝bollinger／vwap。

用法：
    .venv/bin/python plans/ppt/make_cap_mix.py analyse    # 只跑分析、印出統計（寫 TMP/capmix_stats.json）
    .venv/bin/python plans/ppt/make_cap_mix.py deck       # 分析 + 產生 plans/ppt/cap_mix.pptx
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULT_JSON = ROOT / ("results/plan2_monthly_3group_2022-01-01_2026-10-23"
                      "_immediate_mf200_park0050_scorezscore_pool100.json")
OUT_JSON = ROOT / "TMP/capmix_stats.json"
OUT_PPTX = ROOT / "plans/ppt/cap_mix.pptx"

TIERS = ("大型股", "中型股", "小型股")
TIER_RULE = "大型＝市值前 50 名｜中型＝51～150 名｜小型＝151 名以後"
STRATS = ("ma_cross", "breakout", "bollinger", "vwap")
STRAT_LABEL = {"ma_cross": "均線交叉", "breakout": "突破",
               "bollinger": "布林回歸", "vwap": "VWAP 偏離"}
STRAT_SIDE = {"ma_cross": "順勢", "breakout": "順勢", "bollinger": "回歸", "vwap": "回歸"}


# ── 資料載入 ──────────────────────────────────────────────────────────
def load_prices(sid: str, _cache: dict) -> pd.DataFrame | None:
    """與回測同一份價格快取（cache/selector_prices/<sid>.pkl，schema v2）。"""
    if sid in _cache:
        return _cache[sid]
    p = ROOT / f"cache/selector_prices/{sid}.pkl"
    df = None
    if p.exists():
        with open(p, "rb") as f:
            obj = pickle.load(f)
        df = obj.get("data") if isinstance(obj, dict) else obj
        if isinstance(df, pd.DataFrame) and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            df = df.dropna(subset=["close"])
            df.index = pd.to_datetime(df.index)
        else:
            df = None
    _cache[sid] = df
    return df


def route_detail(df: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    """複製 `scripts/backtest_plan2_monthly_3group.pick_strategy_by_form()`（STRAT_MODE=form），
    並把「為什麼走到這一支」的三個條件一起回傳（給說明頁用）。"""
    out = {"strat": "ma_cross", "cp": None, "ma20": None, "ma60": None, "mom20": None,
           "above_ma20": None, "ma20_above_ma60": None, "mom_pos": None}
    if df is None:
        return out
    d = df.loc[:as_of]
    if d.empty:
        return out
    close = d["close"].astype(float)
    cp = float(close.iloc[-1])
    ma20 = float(close.iloc[max(0, len(close) - 20):].mean())
    ma60 = float(close.iloc[max(0, len(close) - 60):].mean())
    ref = float(close.iloc[max(0, len(close) - 21)])
    mom20 = (cp / ref - 1.0) if ref > 0 else 0.0
    above, up, pos = cp > ma20, ma20 > ma60, mom20 > 0
    strat = ("breakout" if mom20 > 0.05 else "ma_cross") if (above and up and pos) \
        else ("bollinger" if cp < ma20 else "vwap")
    out.update({"strat": strat, "cp": cp, "ma20": ma20, "ma60": ma60, "mom20": mom20,
                "above_ma20": above, "ma20_above_ma60": up, "mom_pos": pos})
    return out


def route_strategy(df: pd.DataFrame, as_of: pd.Timestamp) -> str:
    return route_detail(df, as_of)["strat"]


def analyse() -> dict:
    from core.candidate_pool import build_quarterly_pool, load_historical_shares

    res = json.load(open(RESULT_JSON, encoding="utf-8"))
    log = res["groups"]["normal"]["selection_log"]
    picks = [x for x in log if x.get("S")]
    hist, src = load_historical_shares()

    px = {}
    # 先把全宇宙（672 檔）價格載進記憶體，逐選股日算「全宇宙市值排名」
    universe = sorted({k[0] for k in hist})
    for sid in universe:
        load_prices(sid, px)
    print(f"價格載入: {len([1 for v in px.values() if v is not None])} 檔")

    def shares_at(sid: str, ym: str):
        """取該月股本；缺就往前找最近一個月（下市股常有斷點）。"""
        v = hist.get((sid, ym))
        if v:
            return v
        cands = [k[1] for k in hist if k[0] == sid and k[1] <= ym]
        return hist[(sid, max(cands))] if cands else None

    def cap_at(sid: str, d: pd.Timestamp):
        df = px.get(sid)
        if df is None:
            return None
        sub = df.loc[:d]
        if sub.empty:
            return None
        close = float(sub["close"].iloc[-1])
        sh = shares_at(sid, d.strftime("%Y-%m"))
        return (close * sh) if (sh and close > 0) else None

    rows = []
    for x in picks:
        d = pd.Timestamp(x["date"])
        caps = {sid: cap_at(sid, d) for sid in universe}
        caps = {k: v for k, v in caps.items() if v}
        order = sorted(caps, key=caps.get, reverse=True)
        rank_of = {sid: i + 1 for i, sid in enumerate(order)}
        for sid in x["S"]:
            df = px.get(sid)
            if df is None:
                continue
            rk = rank_of.get(sid)
            if rk is None:                     # 當天沒有可用價格／股本（極少數）⇒ 記為不明
                continue
            cap_yi = caps[sid] / 1e8
            tier = ("大型股" if rk <= 50 else "中型股" if rk <= 150 else "小型股")
            det = route_detail(df, d)
            rows.append({"date": x["date"], "year": d.year, "sid": sid,
                         "rank": rk, "universe": len(order), "cap_yi": cap_yi,
                         "tier": tier, "strat": det["strat"],
                         "mom20": det["mom20"],
                         "dist_ma20": (det["cp"] / det["ma20"] - 1.0
                                       if det["ma20"] else None),
                         "above_ma20": det["above_ma20"],
                         "ma20_above_ma60": det["ma20_above_ma60"],
                         "mom_pos": det["mom_pos"]})

    df = pd.DataFrame(rows)
    n = len(df)
    stats = {
        "window": "2022-01-01 ~ 2026-10-23",
        "months": len(picks),
        "skipped_months": sum(1 for x in log if x.get("skipped")),
        "n": n,
        "per_month": round(n / max(1, len(picks)), 2),
        "tier_rule": TIER_RULE,
        "tier_share": {t: round(float((df.tier == t).mean()), 4) for t in TIERS},
        "tier_count": {t: int((df.tier == t).sum()) for t in TIERS},
        "tier_cap_median_yi": {t: (round(float(df.loc[df.tier == t, "cap_yi"].median()), 0)
                                   if (df.tier == t).any() else None) for t in TIERS},
        "strat_share_all": {s: round(float((df.strat == s).mean()), 4) for s in STRATS},
        "side_share_all": {k: round(float((df.strat.map(STRAT_SIDE) == k).mean()), 4)
                           for k in ("順勢", "回歸")},
        "tier_x_strat": {
            t: {s: {"n": int(((df.tier == t) & (df.strat == s)).sum()),
                    "share": round(float(((df.tier == t) & (df.strat == s)).sum()
                                         / max(1, int((df.tier == t).sum()))), 4)}
                for s in STRATS}
            for t in TIERS
        },
        "tier_x_side": {
            t: {k: round(float(((df.tier == t) & (df.strat.map(STRAT_SIDE) == k)).sum()
                               / max(1, int((df.tier == t).sum()))), 4)
                for k in ("順勢", "回歸")}
            for t in TIERS
        },
        "year_tier_share": {
            str(y): {t: round(float((g.tier == t).mean()), 4) for t in TIERS}
            for y, g in df.groupby("year")
        },
        "route": _route_stats(df),
        "unique_sids": int(df.sid.nunique()),
        "top_sids": df.sid.value_counts().head(8).to_dict(),
        "source": {"result": str(RESULT_JSON.relative_to(ROOT)),
                   "picks": str(len(picks)), "rows": n},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    df.to_csv(ROOT / "TMP/capmix_picks.csv", index=False, encoding="utf-8")
    return stats


def _route_stats(df: pd.DataFrame) -> dict:
    """順勢／逆勢的分支是怎麼命中的（給簡報說明頁用）。"""
    n = len(df)
    trend = ((df.above_ma20 == True) & (df.ma20_above_ma60 == True) & (df.mom_pos == True))  # noqa: E712
    reg = ~trend
    reg_df = df[reg]
    boll, vwap = reg_df[reg_df.strat == "bollinger"], reg_df[reg_df.strat == "vwap"]
    # 逆勢時「哪一條趨勢條件不成立」（可複選）
    fail = {
        "價格跌破 20 日線": int((reg_df.above_ma20 == False).sum()),          # noqa: E712
        "20 日均線已跌破 60 日線": int((reg_df.ma20_above_ma60 == False).sum()),  # noqa: E712
        "20 日動能轉負": int((reg_df.mom_pos == False).sum()),               # noqa: E712
    }
    return {
        "n": n,
        "trend_n": int(trend.sum()), "regime_n": int(reg.sum()),
        "trend_share": round(float(trend.mean()), 4), "regime_share": round(float(reg.mean()), 4),
        "breakout_n": int((df.strat == "breakout").sum()),
        "ma_cross_n": int((df.strat == "ma_cross").sum()),
        "bollinger_n": int((df.strat == "bollinger").sum()),
        "vwap_n": int((df.strat == "vwap").sum()),
        "breakout_mom_median": round(float(df.loc[df.strat == "breakout", "mom20"].median()), 4),
        "bollinger_dist_median": round(float(boll["dist_ma20"].median()), 4) if len(boll) else None,
        "vwap_dist_median": round(float(vwap["dist_ma20"].median()), 4) if len(vwap) else None,
        "vwap_mom_median": round(float(vwap["mom20"].median()), 4) if len(vwap) else None,
        "regime_fail": fail,
        "boll_below_ma20": int((boll["above_ma20"] == False).sum()),        # noqa: E712
        "boll_trend_still_ok": int(((boll["ma20_above_ma60"] == True)      # noqa: E712
                                    & (boll["mom_pos"] == True)).sum()),   # noqa: E712
        "vwap_above_ma20": int((vwap["above_ma20"] == True).sum()),        # noqa: E712
        "vwap_ma20_below_ma60": int((vwap["ma20_above_ma60"] == False).sum()),  # noqa: E712
        "regime_only_below_ma20": int(((reg_df.above_ma20 == False)  # noqa: E712
                                       & (reg_df.ma20_above_ma60 == True)  # noqa: E712
                                       & (reg_df.mom_pos == True)).sum()),  # noqa: E712
    }


def _print(st: dict) -> None:
    print(f"\n期間 {st['window']}｜選股 {st['months']} 次（跳過 {st['skipped_months']} 次）、"
          f"{st['n']} 筆（平均 {st['per_month']} 檔／次）、{st['unique_sids']} 檔個股")
    print(f"分級規則：{st['tier_rule']}")
    for t in TIERS:
        print(f"  {t}: {st['tier_count'][t]:3d} 筆（{st['tier_share'][t]:.1%}）"
              f"｜市值中位數 {st['tier_cap_median_yi'][t]} 億")
    print("  策略（全體）: " + "／".join(f"{STRAT_LABEL[s]} {st['strat_share_all'][s]:.1%}" for s in STRATS))
    print("  順勢／回歸: " + "／".join(f"{k} {v:.1%}" for k, v in st["side_share_all"].items()))
    for t in TIERS:
        line = "｜".join(f"{STRAT_LABEL[s]} {st['tier_x_strat'][t][s]['share']:.0%}"
                         f"({st['tier_x_strat'][t][s]['n']})" for s in STRATS)
        print(f"  {t}: {line}｜順勢 {st['tier_x_side'][t]['順勢']:.0%}")
    r = st["route"]
    print(f"  路由：順勢 {r['trend_share']:.1%}（突破 {r['breakout_n']}／均線 {r['ma_cross_n']}）"
          f"｜逆勢 {r['regime_share']:.1%}（布林 {r['bollinger_n']}／VWAP {r['vwap_n']}）")
    print(f"        逆勢時不成立的條件（複選）: {r['regime_fail']}")
    print(f"        突破 mom20 中位數 {r['breakout_mom_median']:+.2%}｜"
          f"布林距 MA20 中位 {r['bollinger_dist_median']:+.2%}｜"
          f"VWAP 距 MA20 中位 {r['vwap_dist_median']:+.2%}、mom20 中位 {r['vwap_mom_median']:+.2%}")
    print("  逐年大型股占比: " + "／".join(f"{y} {v['大型股']:.0%}" for y, v in st["year_tier_share"].items()))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyse"
    st = analyse()
    _print(st)
    if mode == "deck":
        from make_cap_mix_deck import build_deck   # 版面在另一支，避免這支太長
        p = build_deck(st)
        print(f"\n✅ 產生 {p.relative_to(ROOT)}（{p.stat().st_size / 1024:.0f} KB）")
