#!/usr/bin/env python3
"""
selector_keep.py — 「選股+抱緊+例外鎖利」精簡策略

規則：
  ① 每季用 momentum 選 top N 檔，等權重買入
  ② 抱滿整季（3 個月），不操作
  ③ 例外：途中漲到 exit_pct 倍（如 1.5x）→ 立即賣出鎖利
  ④ 季末檢討：仍在 top N 就保留，不在就清倉換股

與簡單輪動的差異：持股可能被保留跨越多季（不強制全換）

Usage:
  python scripts/selector_keep.py                     # 回測 2022~2025
  python scripts/selector_keep.py --auto              # auto_momentum
  python scripts/selector_keep.py --exit-pct 2.0      # 2 倍才賣
  python scripts/selector_keep.py --top-n 3            # 只選 3 檔
"""
import argparse, json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.cache_io import load_cache_or_raw

# ── 候選池（市值排名）──
CAP_RANKING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "inst_momentum", "mcap_ranking.pkl")
CANDIDATE_POOL = None
if os.path.exists(CAP_RANKING):
    ranked, _ = load_cache_or_raw(CAP_RANKING)
    ranked = ranked or []
    CANDIDATE_POOL = [s for s in ranked if s.isdigit() and len(s) == 4][:50]
if not CANDIDATE_POOL:
    CANDIDATE_POOL = ["2330","2454","2317","2382","2376","2345","2308","2303","2327",
                       "2408","2412","2881","2882","2884","2885","2886","2891","2892"]

ETF_STOCKS = {"0050","0056","006208","00878","00646","00632R"}
COMMISSION = 0.001425
STOCK_TAX = 0.003; ETF_TAX = 0.001

def tax_rate(sym): return ETF_TAX if sym in ETF_STOCKS else STOCK_TAX

_cache = {}
def load_stock(sym, start="2022-01-01"):
    if sym in _cache: return _cache[sym]
    yf_sym = f"{sym}.TW"
    df = yf.download(yf_sym, start=start, end="2026-12-31", auto_adjust=True, progress=False)
    if df.empty: _cache[sym] = df; return df
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    _cache[sym] = df
    return df

def snap(df, target):
    if target in df.index: return target
    a = df[df.index <= target].index
    return a[-1] if len(a) > 0 else None

def momentum_score(df, date, mdays=21):
    if date not in df.index: return None
    idx = df.index.get_loc(date); si = max(0, idx-mdays)
    sp = float(df.iloc[si]["close"]); ep = float(df.iloc[idx]["close"])
    if sp <= 0: return None
    return (ep-sp)/sp

def quarter_dates(start="2022-01-01", end="2025-12-31"):
    bd = pd.bdate_range(start=start, end=end, freq="B")
    qs = {}
    for d in bd:
        if d.month in (3,6,9,12): qs[(d.year,d.month)] = d
    result = []
    for yr,mo in sorted(qs):
        cands = [d for d in bd if d.year==yr and d.month==mo]
        if cands: result.append(cands[-1])
    return result

def calc_mdays(mf, date):
    """年線斜率判斷：多頭→21d，否則→63d"""
    # Snap to actual trading day
    if date not in mf.index:
        avail = mf[mf.index <= date].index
        if len(avail) > 0: date = avail[-1]
    if date not in mf.index: return 21
    idx = mf.index.get_loc(date)
    if idx < 240: return 21
    c = mf["close"].values; cp = c[idx]
    ma200 = np.mean(c[idx-199:idx+1]); ma200b = np.mean(c[idx-239:idx-199])
    slope = (ma200-ma200b)/ma200b if ma200b>0 else 0
    return 21 if (cp>ma200 and slope>0.002) else 63


def simulate(initial_capital=500000, start="2022", end="2025",
             top_n=4, auto_momentum=False, exit_pct=99, auto_lock=False, verbose=True):
    """核心模擬引擎：選股+抱緊+季末檢討。auto_lock=True 時，盤整季(63d)自動鎖 1.5x"""
    load_start = str(int(start)-1)+"-01-01"
    data = {}
    for sym in CANDIDATE_POOL:
        df = load_stock(sym, start=load_start)
        if not df.empty and len(df)>100: data[sym] = df
    
    mf = data.get("0050")
    cash = float(initial_capital)
    qds = quarter_dates(start+"-01-01", end+"-12-31")
    positions = {}  # {sym: {shares, cost, avg_px, buy_date}}
    records = []
    early_exits = 0
    
    for qi, qd in enumerate(qds):
        is_last = (qi == len(qds)-1)
        mdays = calc_mdays(mf, qd) if (auto_momentum and mf) else 21
        
        # ── auto_lock: 決定本季鎖利倍數 ──
        quarter_lock = exit_pct  # 手動設定的倍數
        if auto_lock:
            if mdays == 63:  # 盤整季，開鎖利
                quarter_lock = min(quarter_lock, 1.5)
            else:            # 趨勢季，不鎖
                quarter_lock = 99
        
        # ── Step 1: 排名 ──
        scored = []
        for sym, df in data.items():
            if qd not in df.index: continue
            ret = momentum_score(df, qd, mdays)
            if ret is None or ret <= 0: continue
            scored.append((sym, ret, float(df.loc[qd, "close"])))
        scored.sort(key=lambda x: x[1], reverse=True)
        top_picks = [s[0] for s in scored[:top_n]]
        
        if verbose:
            print(f"\n{'─'*55}")
            print(f" 📅 {qd.date()} Q{qd.month//3} 動能{mdays}d  top{top_n}={top_picks}")
        
        # ── Step 2: 區分保留/清倉/新進 ──
        held = {s:p for s,p in positions.items() if p["shares"]>0}
        to_keep = [s for s in held if s in top_picks]
        to_sell = [s for s in held if s not in top_picks]
        to_buy  = [s for s in top_picks if s not in held]
        
        if verbose:
            if to_keep: print(f"   ✅ 保留: {to_keep}")
            if to_sell: print(f"   🔴 清倉: {to_sell}")
            if to_buy:  print(f"   🟢 新進: {to_buy}")
        
        # ── Step 3: 清倉 ──
        for sym in to_sell:
            pos = positions[sym]
            d = snap(data[sym], qd)
            if d is None: continue
            sp = float(data[sym].loc[d, "close"])
            pr = pos["shares"] * sp * (1 - COMMISSION - tax_rate(sym))
            cash += pr
            if verbose:
                hold_days = (qd - pos["buy_date"]).days
                ret = (sp - pos["avg_px"]) / pos["avg_px"]
                print(f"   💰 賣 {sym} {pos['shares']}股 @{sp:.0f} (持{hold_days}天 {ret:+.0%}) +NT${pr:,.0f}")
            del positions[sym]
        
        # ── Step 4: 新進 ──
        if to_buy and not is_last:
            alloc = cash / len(to_buy)
            for sym in to_buy:
                df_sym = data[sym]
                bp = float(df_sym.loc[qd, "close"])
                sh = int(alloc / bp) if bp>0 else 0
                if sh <= 0: continue
                cost = sh * bp * (1 + COMMISSION); cash -= cost
                positions[sym] = {"shares": sh, "cost": cost, "avg_px": bp, "buy_date": qd}
                if verbose:
                    print(f"   📥 買 {sym} {sh}股 @{bp:.0f} NT${cost:,.0f}")
        
        # ── Step 5: 季末鎖利檢查 ──
        if not is_last and quarter_lock < 90:
            for sym in list(positions.keys()):
                pos = positions[sym]
                df_sym = data[sym]
                d = snap(df_sym, qd)
                if d is None: continue
                current_px = float(df_sym.loc[d, "close"])
                
                if current_px >= pos["avg_px"] * exit_pct:
                    sh = pos["shares"]
                    proceeds = sh * current_px * (1 - COMMISSION - tax_rate(sym))
                    cash += proceeds
                    gain = (current_px - pos["avg_px"]) / pos["avg_px"]
                    if verbose:
                        print(f"   🎯 鎖利 {sym} 觸及{exit_pct}x ({gain:+.0%}) {sh}股 @{current_px:.0f} +NT${proceeds:,.0f}")
                    del positions[sym]
                    early_exits += 1
        
        # ── Step 6: 組合總值 ──
        tv = cash
        for sym, pos in positions.items():
            if sym not in data: continue
            d = snap(data[sym], qd)
            if d is None: continue
            tv += pos["shares"] * float(data[sym].loc[d, "close"])
        
        n_held = len([p for p in positions.values() if p["shares"]>0])
        records.append({"date": qd, "value": round(tv), "cash": round(cash), "n_held": n_held})
        
        if verbose:
            held_list = [(s,p["shares"]) for s,p in positions.items() if p["shares"]>0]
            held_str = ", ".join(f"{s}({sh})" for s,sh in held_list)
            print(f"   💼 NT${tv:,.0f} 現金{cash:,.0f} 持{n_held}檔 {held_str}")
        
        if is_last: break
    
    final_val = records[-1]["value"]
    total_ret = (final_val - initial_capital) / initial_capital
    return {"records": records, "final_value": final_val, "total_return": total_ret,
            "initial_capital": initial_capital, "early_exits": early_exits}


def main():
    parser = argparse.ArgumentParser(description="選股+抱緊+季末鎖利")
    parser.add_argument("--start", default="2022"); parser.add_argument("--end", default="2025")
    parser.add_argument("--top-n", type=int, default=4); parser.add_argument("--capital", type=int, default=500000)
    parser.add_argument("--auto", action="store_true", help="auto_momentum 自動切換 21d/63d")
    parser.add_argument("--auto-lock", action="store_true", help="盤整季(63d)自動開 1.5x 鎖利（自動啟用 auto_momentum）")
    parser.add_argument("--lock-profit-pct", type=float, default=0, help="手動固定鎖利倍數")
    args = parser.parse_args()
    
    # auto-lock 自動啟用 auto_momentum
    if args.auto_lock:
        args.auto = True
    
    exit_pct = args.lock_profit_pct if args.lock_profit_pct > 0 else 99
    
    mode_parts = []
    if args.auto: mode_parts.append("auto_momentum")
    if args.auto_lock: mode_parts.append("auto_lock")
    if args.lock_profit_pct > 0: mode_parts.append(f"鎖利{args.lock_profit_pct}x")
    mode_str = ", ".join(mode_parts) if mode_parts else "無鎖利"
    
    print(f"🎯 選股+抱緊+季末鎖利（{mode_str}）")
    print(f"   {args.start}~{args.end} | NT${args.capital:,} | top{args.top_n}")
    
    result = simulate(args.capital, args.start, args.end, args.top_n, args.auto, exit_pct, args.auto_lock)
    
    print(f"\n{'='*55}")
    print(f"🏆 結果")
    print(f"{'='*55}")
    print(f"   起始 NT${args.capital:,} → 終值 NT${result['final_value']:,.0f}")
    print(f"   總報酬 {result['total_return']:+.1%}")
    print(f"   途中鎖利 {result['early_exits']} 次")
    
    records = result["records"]
    prev = args.capital
    for yr in sorted(set(r["date"].year for r in records)):
        yr_recs = [r for r in records if r["date"].year == yr]
        if not yr_recs: continue
        ye = yr_recs[-1]["value"]
        print(f"   {yr}: {(ye-prev)/prev:+.1%} (NT${prev:,.0f}→NT${ye:,.0f}) 持{yr_recs[-1]['n_held']}檔")
        prev = ye


if __name__ == "__main__":
    main()
