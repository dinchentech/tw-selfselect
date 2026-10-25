#!/usr/bin/env python3
"""
selector_full.py — 完整選股+策略模擬引擎

與 stock_selector_grid.py 的差異：
- 選股時同步分析並建議策略（依股性：金融→vwap、ETF→bollinger、波動大→ma_cross 等）
- 季中真的載入策略函式在日線上產生買賣訊號
- 季末不強制全換，只替換不在 top-N 內的持股

Usage:
  python scripts/selector_full.py                    # 回測 2022~2025
  python scripts/selector_full.py --start 2018       # 回測 2018
  python scripts/selector_full.py --auto             # auto_momentum 模式
  python scripts/selector_full.py --top-n 3          # 只選 3 檔
"""
import argparse, json, os, sys, time
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.keep_wait import keep_wait_strategy

from core.cache_io import load_cache_or_raw

# ── 候選池（從市值排名快取動態載入）──
try:
    CAP_RANKING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "inst_momentum", "mcap_ranking.pkl")
    if os.path.exists(CAP_RANKING):
        ranked, _ = load_cache_or_raw(CAP_RANKING)
        ranked = ranked or []
        CANDIDATE_POOL = [s for s in ranked if s.isdigit() and len(s) == 4][:50]
    else:
        CANDIDATE_POOL = None
except:
    CANDIDATE_POOL = None

if not CANDIDATE_POOL:
    CANDIDATE_POOL = ["2330","2454","2317","2382","2376","2345","2308","2303","2327",
                      "2408","2412","2881","2882","2884","2885","2886","2891","2892"]

# ── 載入資料 ──
_cache = {}
def load_stock(symbol, start="2022-01-01"):
    if symbol in _cache: return _cache[symbol]
    yf_sym = f"{symbol}.TW"
    df = yf.download(yf_sym, start=start, end="2026-12-31", auto_adjust=True, progress=False)
    if df.empty: _cache[symbol] = df; return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    _cache[symbol] = df
    return df

# ── 策略推薦 ──
FINANCIAL = {"2881","2882","2883","2884","2885","2886","2887","2888","2889","2890","2891","2892"}
ETF_STOCKS = {"0050","0056","006208","00878","00646","00632R"}
DEFENSIVE = {"2412","4904","3045"}

def recommend_strategy(sym, df, date):
    """依股性與截至 date 的資料推薦策略"""
    if sym in FINANCIAL:
        return "vwap", {"sigma_mult": 1.5, "rsi_period": 5}
    if sym in ETF_STOCKS:
        return "bollinger", {"window": 20, "std_dev": 2.0, "rsi_period": 5}
    if sym in DEFENSIVE:
        return "keep_wait", {}
    # 計算波動度決定策略
    if date not in df.index: return "ma_cross", {"fast_period": 9, "slow_period": 21}
    idx = df.index.get_loc(date)
    if idx < 60: return "ma_cross", {"fast_period": 9, "slow_period": 21}
    closes = df.iloc[max(0,idx-60):idx+1]["close"].values
    vol = np.std(closes / np.mean(closes))
    if vol > 0.03:
        return "ma_cross", {"fast_period": 5, "slow_period": 20}
    else:
        return "bollinger", {"window": 20, "std_dev": 1.8}

def run_strategy_on_df(df, strategy_name, **params):
    """在 DataFrame 上執行策略，回傳含 signal 列的 DataFrame"""
    if strategy_name == "keep_wait":
        df = df.copy()
        df["signal"] = 0
        return df
    elif strategy_name == "ma_cross":
        return ma_cross_strategy(df, **{k:params.get(k,v) for k,v in {"fast_period":9,"slow_period":21}.items()})
    elif strategy_name == "bollinger":
        return bollinger_reverse_strategy(df, **{k:params.get(k,v) for k,v in {"window":20,"std_dev":2.0,"rsi_period":5}.items()})
    elif strategy_name == "vwap":
        return vwap_deviation_strategy(df, **{k:params.get(k,v) for k,v in {"sigma_mult":1.5,"rsi_period":5}.items()})
    return df

# ── 輔助函數 ──
COMMISSION = 0.001425
STOCK_TAX = 0.003
ETF_TAX = 0.001

def tax_rate(sym): return ETF_TAX if sym in ETF_STOCKS else STOCK_TAX

def snap(df, target):
    if target in df.index: return target
    a = df[df.index <= target].index
    return a[-1] if len(a) > 0 else None

def momentum_score(df, date, mdays=21):
    if date not in df.index: return None
    idx = df.index.get_loc(date)
    si = max(0, idx - mdays)
    sp = float(df.iloc[si]["close"]); ep = float(df.iloc[idx]["close"])
    if sp <= 0: return None
    return (ep - sp) / sp

def quarter_dates(start="2022-01-01", end="2025-12-31"):
    bd = pd.bdate_range(start=start, end=end, freq="B")
    qs = {}
    for d in bd:
        if d.month in (3,6,9,12): qs[(d.year, d.month)] = d
    result = []
    for yr, mo in sorted(qs):
        cands = [d for d in bd if d.year==yr and d.month==mo]
        if cands: result.append(cands[-1])
    return result

# ── 核心回測引擎 ──
def simulate(initial_capital=500000, start="2022-01-01", end="2025-12-31",
             top_n=4, auto_momentum=False, verbose=True):
    """
    完整模擬：選股 + 策略建議 + 季中執行策略 + 季末檢討保留
    """
    print(f"📥 載入資料 ({len(CANDIDATE_POOL)} 檔)...")
    data = {}
    load_start = str(int(start[:4]) - 1) + "-01-01"  # 前一年開始 warm-up
    for sym in CANDIDATE_POOL:
        df = load_stock(sym, start=load_start)
        if not df.empty and len(df) > 100: data[sym] = df
    print(f"✅ 載入 {len(data)} 檔")
    
    mf = data.get("0050")  # 市場指標
    
    cash = float(initial_capital)
    qds = quarter_dates(start, end)
    positions = {}  # {sym: {shares, cost, strategy, params}}
    records = []    # [{date, value, holdings, trades}]
    
    for qi, qd in enumerate(qds):
        is_last = (qi == len(qds) - 1)
        
        # ─── Step 1: 選股（momentum ranking）───
        if auto_momentum and mf is not None and qd in mf.index:
            mdays = _calc_momentum_days(mf, qd)
        else:
            mdays = 21
        
        scored = []
        for sym, df in data.items():
            if qd not in df.index: continue
            ret = momentum_score(df, qd, mdays)
            if ret is None or ret <= 0: continue
            scored.append((sym, ret, float(df.loc[qd, "close"])))
        scored.sort(key=lambda x: x[1], reverse=True)
        top_picks = [s[0] for s in scored[:top_n]]
        
        if verbose:
            print(f"\n{'─'*60}")
            print(f" 📅 {qd.strftime('%Y-%m-%d')} (Q{qd.month//3})  動能{mdays}d  top{top_n}={top_picks}")
            print(f"{'─'*60}")
        
        # ─── Step 2: 區分「保留」vs「清倉」vs「新進」───
        held_syms = [s for s, p in positions.items() if p["shares"] > 0]
        
        to_keep = [s for s in held_syms if s in top_picks]
        to_sell = [s for s in held_syms if s not in top_picks and s not in to_keep]
        to_buy  = [s for s in top_picks if s not in held_syms or positions.get(s,{}).get("shares",0) == 0]
        
        if verbose:
            if to_keep:
                print(f"   ✅ 保留: {to_keep}（仍在 top{top_n}）")
            if to_sell:
                print(f"   🔴 清倉: {to_sell}")
            if to_buy:
                print(f"   🟢 新進: {to_buy}")
        
        # ─── Step 3: 清倉 ───
        for sym in to_sell:
            pos = positions[sym]
            shares = pos["shares"]
            px = snap(data[sym], qd)
            if px is None: continue
            sell_px = float(data[sym].loc[px, "close"])
            proceeds = shares * sell_px * (1 - COMMISSION - tax_rate(sym))
            cash += proceeds
            if verbose:
                print(f"   💰 賣出 {sym} {shares}股 @ {sell_px:.0f} → +NT${proceeds:,.0f}")
            del positions[sym]
        
        # ─── Step 4: 新進 + 建議策略 ───
        if to_buy and not is_last:
            n_new = len(to_buy)
            if n_new > 0:
                alloc = cash / n_new
                for sym in to_buy:
                    df_sym = data[sym]
                    strat_name, strat_params = recommend_strategy(sym, df_sym, qd)
                    buy_px = float(df_sym.loc[qd, "close"])
                    shares = int(alloc / buy_px) if buy_px > 0 else 0
                    if shares <= 0: continue
                    cost = shares * buy_px * (1 + COMMISSION)
                    cash -= cost
                    positions[sym] = {
                        "shares": shares, "cost": cost, "avg_px": buy_px,
                        "strategy": strat_name, "strategy_params": strat_params,
                        "buy_date": qd
                    }
                    if verbose:
                        print(f"   📥 買入 {sym} {shares}股 @ {buy_px:.0f} [{strat_name}] → NT${cost:,.0f}")
        
        # ─── Step 5: 季中策略模擬（只執行加碼，不執行賣出）───
        # 賣出由季末檢討統一決定，季中策略只負責逢低加碼
        if not is_last:
            next_qd = qds[qi + 1]
            
            for sym in list(positions.keys()):
                pos = positions[sym]
                if pos["shares"] <= 0: continue
                df_sym = data[sym]
                
                start_d = snap(df_sym, qd)
                end_d = snap(df_sym, next_qd)
                if start_d is None or end_d is None or end_d <= start_d:
                    continue
                
                strat_df = run_strategy_on_df(df_sym, pos["strategy"], **pos["strategy_params"])
                mask = (strat_df.index > start_d) & (strat_df.index <= end_d)
                signals = strat_df.loc[mask]
                
                for di, row in signals.iterrows():
                    sig = int(row.get("signal", 0))
                    px = float(row.get("close", 0))
                    if pd.isna(sig) or px <= 0: continue
                    
                    # 只執行加碼（signal=1），賣出留給季末檢討
                    if sig == 1 and cash > px:
                        # 最多加碼 10% 部位
                        add_shares = max(int(pos["shares"] * 0.1), 0)
                        if add_shares > 0 and pos["strategy"] != "keep_wait":
                            cost = add_shares * px * (1 + COMMISSION)
                            if cost <= cash:
                                old_qty = pos["shares"]
                                pos["shares"] += add_shares
                                pos["cost"] += cost
                                pos["avg_px"] = pos["cost"] / pos["shares"]
                                cash -= cost
                                if verbose:
                                    print(f"   📈 [{di.strftime('%m/%d')}] 策略加碼 {sym} +{add_shares}股 @ {px:.0f} [{pos['strategy']}]")
            
            # 處理保留股：追蹤價格變化
        
        # ─── Step 6: 計算組合總值 ───
        total_val = cash
        for sym, pos in positions.items():
            if sym not in data: continue
            px = snap(data[sym], qd)
            if px is None: continue
            val = pos["shares"] * float(data[sym].loc[px, "close"])
            total_val += val
        
        n_held = len([p for p in positions.values() if p["shares"] > 0])
        records.append({
            "date": qd, "value": round(total_val), "cash": round(cash),
            "n_held": n_held, "holdings": {s:p for s,p in positions.items() if p["shares"]>0}
        })
        
        if verbose:
            held_list = [(s, p["shares"], p["strategy"]) for s,p in positions.items() if p["shares"]>0]
            held_str = ", ".join(f"{s}({sh}股/{st})" for s,sh,st in sorted(held_list))
            print(f"   💼 組合: NT${total_val:,.0f} | 現金 NT${cash:,.0f} | 持股 {n_held}檔: {held_str}")
        
        if is_last: break
    
    final_val = records[-1]["value"]
    total_ret = (final_val - initial_capital) / initial_capital
    return {"records": records, "final_value": final_val, "total_return": total_ret,
            "initial_capital": initial_capital}


def _calc_momentum_days(mf, date):
    """auto_momentum: 年線斜率判斷"""
    if date not in mf.index: return 21
    idx = mf.index.get_loc(date)
    if idx < 240: return 21
    c = mf["close"].values
    cp = c[idx]
    ma200 = np.mean(c[idx-199:idx+1])
    ma200b = np.mean(c[idx-239:idx-199])
    slope = (ma200 - ma200b) / ma200b if ma200b > 0 else 0
    if cp > ma200 and slope > 0.002: return 21
    return 63


# ── 主程式 ──
def main():
    parser = argparse.ArgumentParser(description="完整選股+策略模擬引擎")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--capital", type=int, default=500000)
    parser.add_argument("--auto", action="store_true", help="啟用 auto_momentum")
    args = parser.parse_args()
    
    print(f"🚀 完整選股+策略模擬")
    print(f"   期間 {args.start} ~ {args.end} | 資金 NT${args.capital:,} | top {args.top_n}")
    print(f"   auto_momentum: {'ON' if args.auto else 'OFF'}")
    
    result = simulate(
        initial_capital=args.capital, start=args.start, end=args.end,
        top_n=args.top_n, auto_momentum=args.auto, verbose=True
    )
    
    print(f"\n{'='*60}")
    print(f"🏆 總績效")
    print(f"{'='*60}")
    print(f"   起始: NT${args.capital:,}")
    print(f"   終值: NT${result['final_value']:,.0f}")
    print(f"   總報酬: {result['total_return']:+.1%}")
    
    # 逐年績效
    records = result["records"]
    prev_val = args.capital
    for yr in sorted(set(r["date"].year for r in records)):
        yr_recs = [r for r in records if r["date"].year == yr]
        if not yr_recs: continue
        yr_end = yr_recs[-1]["value"]
        yr_ret = (yr_end - prev_val) / prev_val
        print(f"   {yr}: {yr_ret:+.1%} (NT${prev_val:,.0f} → NT${yr_end:,.0f}) 持有 {yr_recs[-1]['n_held']} 檔")
        prev_val = yr_end


if __name__ == "__main__":
    main()
