""" 讀取 logs/performance.csv（Group 1 + Group 2）→ logs/dashboard.html（Chart.js 儀表板）"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# 確保可從 container(/app) 或 VM repo 根執行：sys.path[0]=scripts/ → 加專案根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

CSV_PATH = Path("logs/performance.csv")
OUT_PATH = Path("logs/dashboard.html")
GROUP2_PNL_PATH = Path("data/inst_momentum_pnl.json")
HOLDINGS_PATH = Path("logs/holdings.json")
STOCK_ALLOC_PATH = Path("logs/stock_allocation.json")

from core.version import APP_VERSION
CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"


def load_trades() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame()
    try:
        # 兼容 6/7 欄混合（2026-09-01 起 log_trade 新增 exclude_daily 欄位）：
        # 舊版 pandas（VM 1.5.3）對欄位數不符會跳行 → 改用 csv 模組手動讀取，
        # 7 欄行的第 7 欄為 exclude_daily，6 欄舊行補 0
        import csv as _csv
        rows = []
        with open(CSV_PATH, newline='', encoding='utf-8') as f:
            reader = _csv.reader(f)
            header = next(reader, None)
            for r in reader:
                if not r:
                    continue
                while len(r) < 6:
                    r.append('')
                rows.append(r[:7])
        df = pd.DataFrame(rows,
                          columns=["timestamp", "symbol", "signal", "price",
                                   "quantity", "action", "exclude_daily"])
        df['exclude_daily'] = pd.to_numeric(df['exclude_daily'], errors='coerce').fillna(0)
        df['symbol'] = df['symbol'].astype(str).str.strip()
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0.0)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0).astype(int)
        df['signal'] = pd.to_numeric(df['signal'], errors='coerce').fillna(0).astype(int)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except pd.errors.ParserError:
        return pd.DataFrame()
    if 'group' not in df.columns:
        df['group'] = 1
    return df
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], format='mixed')
    df["symbol"] = df["symbol"].astype(str)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if "group" not in df.columns:
        df["group"] = 1
    return df


def load_holdings() -> dict:
    """讀取當前持倉"""
    if not HOLDINGS_PATH.exists():
        return {}
    try:
        with open(HOLDINGS_PATH, "r") as f:
            holdings = json.load(f)
        return holdings
    except Exception:
        return {}


def load_stock_allocation() -> dict:
    """讀取股票成本資訊"""
    if not STOCK_ALLOC_PATH.exists():
        return {}
    try:
        with open(STOCK_ALLOC_PATH, "r") as f:
            alloc = json.load(f)
        return alloc
    except Exception:
        return {}


def fetch_current_prices_dated(symbols: list) -> tuple:
    """抓取標的最新價＋**價格資料日期**：回傳 `({sym: close}, {sym: 'YYYY-MM-DD'})`。

    委派 `core.inst_data.fetch_latest_closes_dated`（與 TG 持倉報告**同一支**）：
    先 TWSE MIS 當日報價（盤後＝當日收盤），失敗才退回 TWSE STOCK_DAY 日線。
    失敗時回傳空 dict，讓呼叫端回退到 performance.csv 最後成交價。

    為什麼要日期（2026-10-06）：使用者比對儀表板 vs TG 的 2059 損益（−12,465 vs −64,650）發現不一致 ——
    兩邊都走 MIS，但**儀表板是靜態快照、TG 是即時**，而儀表板沒顯示價格日期 ⇒ 看不出誰是舊的。
    """
    from core.inst_data import fetch_latest_closes_dated
    dated = fetch_latest_closes_dated(list(symbols or [])) or {}
    prices, dates = {}, {}
    for sym, v in dated.items():
        try:
            prices[str(sym)] = v.get("price")
            if v.get("date"):
                dates[str(sym)] = v["date"]
        except Exception:
            continue
    return prices, dates


def fetch_current_prices(symbols: list) -> dict:
    """抓取標的最新價格，回傳 {symbol: close}（薄包裝；日期請用 `fetch_current_prices_dated`）。"""
    return fetch_current_prices_dated(symbols)[0]


def compute_positions(df: pd.DataFrame, holdings: dict, stock_alloc: dict, current_prices: dict = None) -> list:
    if df.empty or not holdings:
        return []

    latest_prices = {}
    for sym in holdings.keys():
        sym_df = df[df["symbol"] == sym]
        if not sym_df.empty:
            latest_prices[sym] = sym_df["price"].iloc[-1]

    if not current_prices:
        current_prices = latest_prices

    positions = []
    for sym, shares in holdings.items():
        if shares <= 0:
            continue

        # 從 stock_allocation 獲取成本（若不存在則從 trade records 推算）
        alloc_data = stock_alloc.get(sym, {})
        total_cost = alloc_data.get("total_buy_cost", 0)
        total_shares = alloc_data.get("total_buy_shares", 0)

        if total_shares <= 0:
            # Fallback: 從 CSV 所有 BUY 推算成本
            sym_df = df[df["symbol"] == sym]
            buy_rows = sym_df[sym_df["action"].str.upper() == "BUY"]
            if not buy_rows.empty:
                total_cost = (buy_rows["price"] * buy_rows["quantity"]).sum()
                total_shares = buy_rows["quantity"].sum()
            else:
                total_cost = current_prices.get(sym, 0) * shares
                total_shares = shares

        if total_shares <= 0:
            continue

        avg_cost = total_cost / total_shares
        current_price = current_prices.get(sym, avg_cost)
        current_value = current_price * shares
        unrealized_pnl = (current_price - avg_cost) * shares
        unrealized_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

        sym_df = df[df["symbol"] == sym]
        last_buy = sym_df[sym_df["action"].str.upper() == "BUY"]["timestamp"].max()
        last_buy_date = last_buy.strftime("%Y-%m-%d") if pd.notna(last_buy) else "-"

        positions.append({
            "symbol": sym,
            "shares": int(shares),
            "avg_cost": round(avg_cost, 2),
            "total_cost": round(total_cost, 0),
            "current_price": round(current_price, 2),
            "current_value": round(current_value, 0),
            "unrealized_pnl": round(unrealized_pnl, 0),
            "unrealized_pct": round(unrealized_pct, 2),
            "last_buy_date": last_buy_date,
        })

    return positions


def compute_pnl(df: pd.DataFrame) -> list:
    """FIFO 配對計算逐筆 P&L，回傳 [{date, symbol, action, price, qty, pnl, cumulative}]

    **2026-09-17 起為淨額**：買進手續費計入該批成本基礎、賣出（手續費＋證交稅）
    從損益扣除（`core.fees`）。舊列沒有 `cost` 欄 → 以現行費率推定。
    在此之前本函式是**毛額**，故歷史上顯示的「累積損益」偏高（同期實測：
    +5,516 毛 → −6,439 淨）。
    """
    if df.empty:
        return []
    from core import fees as _fees
    lots = defaultdict(list)
    results = []
    running_pnl = 0.0
    for _, row in df.iterrows():
        sym = row["symbol"]
        price = row["price"]
        qty = int(row["quantity"])
        ts = row["timestamp"]
        act = row["action"].upper()
        cost = _fees.row_cost(row)
        if act == "BUY":
            # 成本基礎含買進手續費（每股單價）
            unit = ((price * qty) + cost) / qty if qty else price
            lots[sym].append((unit, qty, ts))
        elif act == "SELL":
            remaining = qty
            total_pnl = 0.0
            total_qty = 0
            avg_cost = 0.0
            while remaining > 0 and lots[sym]:
                buy_unit, buy_qty, _ = lots[sym][0]
                matched = min(buy_qty, remaining)
                # 賣出成本（手續費＋證交稅）按成交股數比例分攤
                trade_pnl = (price - buy_unit) * matched - (cost * matched / qty if qty else 0.0)
                total_pnl += trade_pnl
                total_qty += matched
                avg_cost = buy_unit
                remaining -= matched
                if matched >= buy_qty:
                    lots[sym].pop(0)
                else:
                    lots[sym][0] = (buy_unit, buy_qty - matched, _)
            if total_qty > 0:
                running_pnl += total_pnl
                results.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "time": ts.strftime("%H:%M"),
                    "symbol": sym,
                    "action": "SELL",
                    "price": round(price, 2),
                    "qty": total_qty,
                    "pnl": round(total_pnl, 0),
                    "pnl_pct": round(total_pnl / (avg_cost * total_qty) * 100, 2) if avg_cost else 0,
                    "cumulative": round(running_pnl, 0),
                })
    return results


def _books_warning() -> str:
    """⚠️ 帳務不一致警示（2026-09-17 加）。

    為什麼要放這裡：**「未平倉部位」只認 `logs/holdings.json`**，所以
    「已在 performance.csv 買進、卻沒進 holdings.json」的部位**根本不會出現**在
    那一區 —— 使用者的疑問正是「這些股在未平倉區也沒顯示」。
    這種部位不但看不到，還**永遠不會被賣出**（賣出/孤兒清倉都只認 holdings.json）。

    資料源與實盤斷言同一套：`core.books.audit_books()`（唯一實作）。
    失敗一律回空字串（儀表板不可因為帳務檢查而整頁掛掉）。
    """
    try:
        from core import books
        r = books.audit_books()
        if r.get("ok"):
            return ""
        parts = []
        if r.get("phantom"):
            items = "、".join(f"{sym} × {n:,} 股" for sym, n in r["phantom"].items())
            parts.append(f"<b>未入帳部位</b>（已在 CSV、不在 holdings.json）：{items}")
        if r.get("ghost"):
            items = "、".join(f"{sym} × {n:,} 股" for sym, n in r["ghost"].items())
            parts.append(f"<b>持股無買進紀錄</b>：{items}")
        if r.get("unmatched"):
            items = "、".join(f"{sym} × {n:,} 股" for sym, n in r["unmatched"].items())
            parts.append(f"<b>賣出無對應買進</b>：{items}")
        if r.get("memory_drift"):
            items = "、".join(f"{sym} 記憶體 {m}／磁碟 {d}"
                              for sym, (m, d) in r["memory_drift"].items())
            parts.append(f"<b>記憶體與磁碟持股不一致</b>（下一筆寫入會蓋掉對方）：{items}")
        if r.get("missing"):
            import os as _os
            names = "、".join(_os.path.basename(p) for p in r["missing"])
            parts.append(f"<b>缺少狀態檔</b>：{names}（無法對帳）")
        schema = r.get("csv_schema") or {}
        if schema and not schema.get("ok", True):
            parts.append(f"<b>performance.csv 欄位不一致</b>（表頭 {schema.get('header_cols')} 欄、"
                         f"{schema.get('drift_rows')} 列寬度不符）→ 跑 "
                         f"<code>scripts/migrate_performance_csv_schema.py --apply</code>")
        if not parts:
            return ""
        body = "；".join(parts)
        return (
            '<div style="margin:.6rem 0 1rem;padding:.7rem .9rem;border-left:4px solid #e0a800;'
            'background:#2a2416;color:#e8d9a0;border-radius:4px;font-size:.88rem;line-height:1.5;">'
            '⚠️ <b>帳務不一致</b>（三本帳稽核）：' + body +
            '<br><span style="color:#bda86a;">這些部位不在「未平倉部位」清單裡，'
            '而且<b>永遠不會被自動賣出</b>（賣出與孤兒清倉只認 <code>holdings.json</code>）。'
            '持倉市值／總權益也因此未計入它們。</span></div>'
        )
    except Exception:
        return ""


def _fee_note() -> str:
    """損益口徑註記（2026-09-17 加）。

    誠實揭露兩件事：①損益是**淨額**（扣手續費＋證交稅）；②2026-09-17 前的交易
    沒有記錄實際費用（CSV 的 `cost` 欄），是**依現行費率推定**的。
    """
    from core import fees
    return (
        '<div class="note" style="margin:.5rem 0 .9rem;color:#888;font-size:.85rem;">'
        '損益為<b>淨額</b>（已扣手續費與證交稅）；'
        f'費率＝{fees.fee_rate() * 100:.4g}%、最低 NT${fees.min_fee():.0f}/筆、'
        f'證交稅 {fees.sell_tax_rate() * 100:.3g}%（賣出）。'
        '2026-09-17 之前的交易未記錄實際費用，為<b>依現行費率推定</b>。'
        '</div>')


def build_trade_log(df: pd.DataFrame, pnl_list: list) -> list:
    """回傳「完整逐筆交易」清單（**含買進**），供「近 50 筆交易」表格顯示（2026-09-11）。

    - 賣出列：直接取用 `compute_pnl()` 算好的 FIFO 已實現損益與當時累積損益
      （**不重算**，確保顯示值與統計值完全一致）。
    - 買進列：`pnl`/`pnl_pct` 為 `None`（尚無已實現損益），`cumulative` 沿用當下水位。

    ⚠️ **僅供顯示**。統計（交易次數／勝率／總損益）一律走 `pnl_list`，
    不可把買進混進去 —— 否則交易次數會暴增、勝率分母被汙染。
    """
    if df.empty:
        return []

    # 依 (symbol, date, time) 分桶，賣出列依序消耗（同分鐘多筆也不會錯位）
    buckets = defaultdict(list)
    for p in pnl_list:
        buckets[(p["symbol"], p["date"], p["time"])].append(p)

    log = []
    running = 0.0
    for _, row in df.iterrows():
        ts = row["timestamp"]
        sym = row["symbol"]
        act = row["action"].upper()
        d, t = ts.strftime("%Y-%m-%d"), ts.strftime("%H:%M")
        entry = {
            "date": d,
            "time": t,
            "symbol": sym,
            "action": act,
            "price": round(float(row["price"]), 2),
            "qty": int(row["quantity"]),
            "pnl": None,
            "pnl_pct": None,
        }
        if act == "SELL":
            bucket = buckets.get((sym, d, t))
            if bucket:
                p = bucket.pop(0)
                entry["pnl"] = p["pnl"]
                entry["pnl_pct"] = p["pnl_pct"]
                entry["qty"] = p["qty"]           # 用實際配對到的股數
                running = p["cumulative"]         # 賣出後才更新累積水位
        entry["cumulative"] = round(running, 0)
        log.append(entry)
    return log


def _render_trade_rows(trades: list) -> str:
    """把逐筆交易清單渲染成表格列；買進因尚無已實現損益，損益欄顯示「—」。"""
    out = []
    for t in trades:
        cum_cls = "positive" if t["cumulative"] >= 0 else "negative"
        is_buy = t["action"] == "BUY"
        act_cell = f'<span class="act {"buy" if is_buy else "sell"}">{"買" if is_buy else "賣"}</span>'
        if t["pnl"] is None:
            pnl_cells = '<td class="muted">—</td><td class="muted">—</td>'
        else:
            cls = "positive" if t["pnl"] >= 0 else "negative"
            pnl_cells = (f'<td class="{cls}">{t["pnl"]:+,.0f}</td>'
                         f'<td class="{cls}">{t["pnl_pct"]:+.2f}%</td>')
        out.append(
            f'<tr><td>{t["date"]}</td><td>{t["time"]}</td><td>{act_cell}</td>'
            f'<td>{t["symbol"]}</td><td>{t["price"]:,.0f}</td><td>{t["qty"]}</td>'
            f'{pnl_cells}<td class="{cum_cls}">{t["cumulative"]:+,.0f}</td></tr>'
        )
    return "".join(out)


def compute_symbol_stats(df: pd.DataFrame, pnl_list: list) -> list:
    """各標的統計：交易次數、損益、勝率"""
    if df.empty:
        return []
    stats = {}
    for sym in df["symbol"].unique():
        sym_df = df[df["symbol"] == sym]
        buys = len(sym_df[sym_df["action"].str.upper() == "BUY"])
        sells = len(sym_df[sym_df["action"].str.upper() == "SELL"])
        sym_pnl = sum(p["pnl"] for p in pnl_list if p["symbol"] == sym)
        win_trades = sum(1 for p in pnl_list if p["symbol"] == sym and p["pnl"] > 0)
        total_trades = sum(1 for p in pnl_list if p["symbol"] == sym)
        win_rate = round(win_trades / total_trades * 100, 1) if total_trades else 0
        stats[sym] = {
            "trades": total_trades,
            "buys": buys,
            "sells": sells,
            "pnl": round(sym_pnl, 0),
            "win_rate": win_rate,
        }
    return [{"symbol": k, **v} for k, v in stats.items()]


def compute_daily_pnl(pnl_list: list) -> list:
    """逐日匯總損益 for 累積曲線"""
    daily = defaultdict(float)
    for p in pnl_list:
        daily[p["date"]] += p["pnl"]
    if not daily:
        return []
    cumulative = 0.0
    dates = []
    for d in sorted(daily):
        cumulative += daily[d]
        dates.append({"date": d, "daily": round(daily[d], 0), "cumulative": round(cumulative, 0)})
    return dates


def _to_native(obj):
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (int, float)):
        if hasattr(obj, "item"):
            return obj.item()
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def load_group2_json_summary() -> dict:
    """從 inst_momentum_pnl.json 讀取 Group 2 摘要（資本、權益等）"""
    if not GROUP2_PNL_PATH.exists():
        return {}
    try:
        data = json.loads(GROUP2_PNL_PATH.read_text())
        capital = data.get("capital", 0)
        total_buy = data.get("total_buy_cost", 0)
        total_sell = data.get("total_sell_proceeds", 0)
        # 從 state 抓持倉市值（若可讀）
        pos_value = 0
        state_path = Path("data/inst_momentum_state.json")
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                pos_value = sum(p.get("cost", 0) for p in state.get("positions", {}).values())
            except Exception:
                pass
        remaining = capital - total_buy + total_sell
        return {
            "capital": capital,
            "remaining_cash": round(remaining, 0),
            "position_value": round(pos_value, 0),
            "total_equity": round(remaining + pos_value, 0),
            "total_buy_cost": round(total_buy, 0),
            "total_sell_proceeds": round(total_sell, 0),
        }
    except Exception:
        return {}


def build_group_stats(pnl_list: list, df: pd.DataFrame) -> dict:
    """計算單一群組的摘要統計"""
    if not pnl_list:
        return {"total_trades": 0, "total_pnl": 0, "win_count": 0, "lose_count": 0,
                "win_rate": 0, "total_buy_qty": 0, "total_sell_qty": 0, "trade_days": 0}
    total_trades = len(pnl_list)
    total_pnl = round(sum(p["pnl"] for p in pnl_list), 0)
    win_count = sum(1 for p in pnl_list if p["pnl"] > 0)
    lose_count = sum(1 for p in pnl_list if p["pnl"] <= 0)
    win_rate = round(win_count / total_trades * 100, 1) if total_trades else 0
    total_buy_qty = int(df[df["action"].str.upper() == "BUY"]["quantity"].sum())
    total_sell_qty = int(df[df["action"].str.upper() == "SELL"]["quantity"].sum())
    trade_days = df["timestamp"].dt.date.nunique()
    return {
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": win_rate,
        "total_buy_qty": total_buy_qty,
        "total_sell_qty": total_sell_qty,
        "trade_days": trade_days,
    }


def build_html(trades_df: pd.DataFrame) -> str:
    df_g1 = trades_df[trades_df["group"] == 1] if not trades_df.empty else pd.DataFrame()
    df_g2 = trades_df[trades_df["group"] == 2] if not trades_df.empty else pd.DataFrame()

    pnl_g1 = compute_pnl(df_g1)
    pnl_g2 = compute_pnl(df_g2)

    stats_g1 = build_group_stats(pnl_g1, df_g1)
    stats_g2 = build_group_stats(pnl_g2, df_g2)

    symbol_stats_g1 = compute_symbol_stats(df_g1, pnl_g1)
    symbol_stats_g2 = compute_symbol_stats(df_g2, pnl_g2)

    daily_g1 = compute_daily_pnl(pnl_g1)
    daily_g2 = compute_daily_pnl(pnl_g2)

    # Group 2 JSON PnL 補充資料
    g2_json = load_group2_json_summary()

    # 合併曲線資料：以日期為 key
    all_dates = set()
    for d in daily_g1:
        all_dates.add(d["date"])
    for d in daily_g2:
        all_dates.add(d["date"])
    pnl_curve_g1 = {d["date"]: d["cumulative"] for d in daily_g1}
    pnl_curve_g2 = {d["date"]: d["cumulative"] for d in daily_g2}
    combined_daily = sorted(all_dates)
    curve_g1_data = [pnl_curve_g1.get(d, None) for d in combined_daily]
    curve_g2_data = [pnl_curve_g2.get(d, None) for d in combined_daily]

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 「近 50 筆交易」＝完整逐筆紀錄（含買進）；統計仍走 pnl_list，不受影響
    trade_log_g1 = build_trade_log(df_g1, pnl_g1)
    trade_log_g2 = build_trade_log(df_g2, pnl_g2)
    last_trades_g1 = sorted(trade_log_g1, key=lambda x: x["date"] + x["time"], reverse=True)[:50]
    last_trades_g2 = sorted(trade_log_g2, key=lambda x: x["date"] + x["time"], reverse=True)[:50]

    # 計算未平倉部位
    holdings = load_holdings()
    stock_alloc = load_stock_allocation()
    current_prices, price_dates = fetch_current_prices_dated(list(holdings.keys()))
    # 「參考市價」的資料日期（與 TG 持倉報告共用同一 helper/同一串文字；非當日會標 ⚠️非當日）
    try:
        from core.live_notifications import price_date_note as _price_date_note
        price_date_note_html = _price_date_note(price_dates, datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        price_date_note_html = ""
    positions = compute_positions(trades_df, holdings, stock_alloc,
                                  current_prices=current_prices)

    charts_data = _to_native({
        "labels": combined_daily,
        "curve_g1": curve_g1_data,
        "curve_g2": curve_g2_data,
        "symbol_stats_g1": symbol_stats_g1,
        "symbol_stats_g2": symbol_stats_g2,
        "pnl_list_g1": pnl_g1[-30:] if len(pnl_g1) > 30 else pnl_g1,
        "pnl_list_g2": pnl_g2[-30:] if len(pnl_g2) > 30 else pnl_g2,
        "g2_json": g2_json,
    })
    charts_json = json.dumps(charts_data, ensure_ascii=False)

    # 只要有任何交易紀錄就顯示該群組（僅有買進、尚未平倉時也要看得到，不可顯示「尚無交易紀錄」）
    has_g1 = stats_g1["total_trades"] > 0 or bool(trade_log_g1)
    has_g2 = stats_g2["total_trades"] > 0 or bool(trade_log_g2)

    total_pnl = stats_g1["total_pnl"] + stats_g2["total_pnl"]
    total_trades = stats_g1["total_trades"] + stats_g2["total_trades"]

    # ─── 數值格式化 helper ───
    def v(n):
        int_n = int(n)
        return f"{int_n:,}" if int_n < 0 else f"+{int_n:,}"

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TW SelfSelect — 績效儀表板</title>
<script src="{CHART_CDN}"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f5f7fa; color: #1a1a2e; padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: .85rem; margin-bottom: 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 12px; margin-bottom: 16px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .card .label {{ font-size: .75rem; color: #888; text-transform: uppercase; letter-spacing: .5px; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
  .card .value.positive {{ color: #e74c3c; }}  .card .value.negative {{ color: #3498db; }}
  .group-label {{ font-size: .65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
                  margin-bottom: 8px; padding: 2px 8px; border-radius: 4px; display: inline-block; }}
  .group-label.g1 {{ background: #fdeaea; color: #c0392b; }}
  .group-label.g2 {{ background: #eaf5ff; color: #2980b9; }}
  .group-label.total {{ background: #f0f0f0; color: #555; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .chart-box {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .chart-box.full {{ grid-column: 1 / -1; }}
  .chart-box h3 {{ font-size: .9rem; color: #555; margin-bottom: 12px; }}
  .chart-box canvas {{ max-height: 320px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th {{ text-align: left; padding: 8px 10px; border-bottom: 2px solid #e8e8e8; color: #888; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #f0f0f0; }}
  .positive {{ color: #e74c3c; }}  .negative {{ color: #3498db; }}
  .muted {{ color: #c4c4c4; }}
  .act {{ display: inline-block; min-width: 20px; text-align: center; padding: 1px 6px;
          border-radius: 4px; font-size: .75rem; font-weight: 600; }}
  .act.buy {{ background: #e8f5e9; color: #2e7d32; }}
  .act.sell {{ background: #fdecea; color: #c62828; }}
  .section-title {{ font-size: 1.05rem; font-weight: 600; margin: 24px 0 12px; }}
  .empty {{ text-align: center; color: #999; padding: 48px 0; font-size: 1rem; }}
  .group-section {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px;
                    box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .strategy-section {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px;
                        box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .strategy-links {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }}
  .strategy-link {{ display: inline-block; padding: 10px 18px; border-radius: 8px;
                    background: #f0f4ff; color: #2563eb; text-decoration: none; font-weight: 500;
                    font-size: .9rem; transition: background .15s; }}
  .strategy-link:hover {{ background: #dbeafe; }}
  @media (max-width: 640px) {{ .charts {{ grid-template-columns: 1fr; }}
     .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  footer {{ text-align: center; color: #aaa; font-size: .75rem; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">
  <h1>📊 TW SelfSelect 績效儀表板 <span style="font-size:.9rem;color:#999;font-weight:400;">v{APP_VERSION}</span></h1>
  <div class="subtitle">最後更新：{updated_at} · Group 1 + Group 2 雙群組</div>

  <!-- 總覽卡片 -->
   <div class="cards">
     <div class="card"><div class="label">總已實現損益</div><div class="value {"positive" if total_pnl >= 0 else "negative"}">{v(total_pnl)}</div></div>
     <div class="card"><div class="label">總交易次數</div><div class="value">{total_trades}</div></div>
     <div class="card"><div class="label">Group 1 損益</div><div class="value {"positive" if stats_g1['total_pnl'] >= 0 else "negative"}">{v(stats_g1['total_pnl'])}</div></div>
     <div class="card"><div class="label">Group 2 損益</div><div class="value {"positive" if stats_g2['total_pnl'] >= 0 else "negative"}">{v(stats_g2['total_pnl'])}</div></div>
   </div>

   <!-- 未平倉部位卡片 -->
   <div class="cards">
     <div class="card"><div class="label">未實現損益</div><div class="value {"positive" if sum(p["unrealized_pnl"] for p in positions) >= 0 else "negative"}">{v(sum(p["unrealized_pnl"] for p in positions))}</div></div>
     <div class="card"><div class="label">持倉市值</div><div class="value">{sum(p["current_value"] for p in positions):,}</div></div>
     <div class="card"><div class="label">持倉檔數</div><div class="value">{len(positions)}</div></div>
     <div class="card"><div class="label">總權益</div><div class="value {"positive" if (total_pnl + sum(p["unrealized_pnl"] for p in positions)) >= 0 else "negative"}">{v(total_pnl + sum(p["unrealized_pnl"] for p in positions))}</div></div>
   </div>
"""

    # Group 2 JSON 補充卡片（資本、權益）
    if g2_json.get("capital", 0) > 0:
        equity = g2_json.get("total_equity", 0)
        capital = g2_json.get("capital", 0)
        ret = ((equity - capital) / capital * 100) if capital > 0 else 0
        html += f"""
  <div class="cards">
    <div class="card"><div class="label">Group 2 起始資金</div><div class="value">{int(capital):,}</div></div>
    <div class="card"><div class="label">Group 2 總權益</div><div class="value {"positive" if equity >= capital else "negative"}">{int(equity):,}</div></div>
    <div class="card"><div class="label">Group 2 報酬率</div><div class="value {"positive" if ret >= 0 else "negative"}">{ret:+.2f}%</div></div>
  </div>
"""

    # ⚠️ 帳務不一致警示（必須在「未平倉部位」之前，因為那份清單看不到這些部位）
    html += _books_warning()

    # Add open positions section
    if positions:
        html += f"""
  <div class="group-section">
    <div class="section-title">📋 未平倉部位</div>
    {('<div class="subtitle" style="margin:-6px 0 8px;">' + price_date_note_html + '</div>') if price_date_note_html else ''}
    <table><thead><tr><th>標的</th><th>股數</th><th>平均成本</th><th>市價</th><th>市值</th><th>未實現損益</th><th>報酬率</th><th>最後買進日</th></tr></thead><tbody>
"""
        for pos in positions:
            cls = "positive" if pos["unrealized_pnl"] >= 0 else "negative"
            html += f"""      <tr><td>{pos["symbol"]}</td><td>{pos["shares"]}</td><td>{pos["avg_cost"]:,.0f}</td><td>{pos["current_price"]:,.0f}</td>
          <td>{pos["current_value"]:,.0f}</td><td class="{cls}">{pos["unrealized_pnl"]:+,.0f}</td>
          <td class="{cls}">{pos["unrealized_pct"]:+.2f}%</td><td>{pos["last_buy_date"]}</td></tr>
"""
        html += """
    </tbody></table>
  </div>
"""
    else:
        html += """
  <div class="group-section">
    <div class="section-title">📋 未平倉部位</div>
    <div class="empty">📭 無未平倉部位</div>
  </div>
"""

    html += """
  <div class="charts">
    <div class="chart-box full"><h3>📈 累積損益曲線</h3><canvas id="chartPnlCombined"></canvas></div>
    <div class="chart-box"><h3>📊 各標的損益 — Group 1</h3><canvas id="chartSymbolsG1"></canvas></div>
    <div class="chart-box"><h3>📊 各標的損益 — Group 2</h3><canvas id="chartSymbolsG2"></canvas></div>
  </div>
"""

    # ─── Group 1 明細 ───
    if has_g1:
        html += f"""
  <div class="group-section">
    <div class="group-label g1">Group 1 固定標的策略</div>
    <div class="cards">
      <div class="card"><div class="label">已實現損益</div><div class="value {"positive" if stats_g1['total_pnl'] >= 0 else "negative"}">{v(stats_g1['total_pnl'])}</div></div>
      <div class="card"><div class="label">交易次數</div><div class="value">{stats_g1['total_trades']}</div></div>
      <div class="card"><div class="label">勝率</div><div class="value">{stats_g1['win_rate']}%</div></div>
      <div class="card"><div class="label">交易天數</div><div class="value">{stats_g1['trade_days']}</div></div>
    </div>
    <div class="section-title">📋 近 50 筆交易</div>
    <table><thead><tr><th>日期</th><th>時間</th><th>動作</th><th>標的</th><th>價格</th><th>股數</th><th>損益</th><th>報酬率</th><th>累積損益</th></tr></thead><tbody>"""
        html += _render_trade_rows(last_trades_g1)
        html += "</tbody></table>"
        html += _fee_note()

        if symbol_stats_g1:
            html += """
    <div class="section-title">🏷️ 各標的統計</div>
    <table><thead><tr><th>標的</th><th>交易次數</th><th>買進</th><th>賣出</th><th>損益</th><th>勝率</th></tr></thead><tbody>"""
            for s in symbol_stats_g1:
                cls = "positive" if s["pnl"] >= 0 else "negative"
                html += f"""<tr><td>{s["symbol"]}</td><td>{s["trades"]}</td><td>{s["buys"]}</td><td>{s["sells"]}</td>
                    <td class="{cls}">{s["pnl"]:+,.0f}</td><td>{s["win_rate"]}%</td></tr>"""
            html += "</tbody></table>"
    else:
        html += """
  <div class="group-section">
    <div class="group-label g1">Group 1 固定標的策略</div>
    <div class="empty">📭 尚無交易紀錄</div>
  </div>"""

    # ─── Group 2 明細 ───
    if has_g2:
        html += f"""
  <div class="group-section">
    <div class="group-label g2">Group 2 法人抬轎動能策略</div>
    <div class="cards">
      <div class="card"><div class="label">已實現損益</div><div class="value {"positive" if stats_g2['total_pnl'] >= 0 else "negative"}">{v(stats_g2['total_pnl'])}</div></div>
      <div class="card"><div class="label">交易次數</div><div class="value">{stats_g2['total_trades']}</div></div>
      <div class="card"><div class="label">勝率</div><div class="value">{stats_g2['win_rate']}%</div></div>
      <div class="card"><div class="label">交易天數</div><div class="value">{stats_g2['trade_days']}</div></div>
    </div>
    <div class="section-title">📋 近 50 筆交易</div>
    <table><thead><tr><th>日期</th><th>時間</th><th>動作</th><th>標的</th><th>價格</th><th>股數</th><th>損益</th><th>報酬率</th><th>累積損益</th></tr></thead><tbody>"""
        html += _render_trade_rows(last_trades_g2)
        html += "</tbody></table>"

        if symbol_stats_g2:
            html += """
    <div class="section-title">🏷️ 各標的統計</div>
    <table><thead><tr><th>標的</th><th>交易次數</th><th>買進</th><th>賣出</th><th>損益</th><th>勝率</th></tr></thead><tbody>"""
            for s in symbol_stats_g2:
                cls = "positive" if s["pnl"] >= 0 else "negative"
                html += f"""<tr><td>{s["symbol"]}</td><td>{s["trades"]}</td><td>{s["buys"]}</td><td>{s["sells"]}</td>
                    <td class="{cls}">{s["pnl"]:+,.0f}</td><td>{s["win_rate"]}%</td></tr>"""
            html += "</tbody></table>"
    else:
        html += """
  <div class="group-section">
    <div class="group-label g2">Group 2 法人抬轎動能策略</div>
    <div class="empty">📭 尚無交易紀錄</div>
  </div>"""

    # ─── 策略動畫連結（五策略）───
    STRATEGY_VIDEOS = [
        ("布林通道反轉", "bollinger-animation.html"),
        ("VWAP 偏離反轉", "vwap-animation.html"),
        ("均線交叉", "ma_cross-animation.html"),
        ("唐奇安突破", "breakout-animation.html"),
        ("Keep & Wait 低接", "keep_wait策略說明.html"),
    ]
    video_links = "".join(
        f'<a href="{fname}" target="_blank" rel="noopener" class="strategy-link">{name}</a>'
        for name, fname in STRATEGY_VIDEOS
    )

    html += f"""
  <div class="strategy-section">
    <div class="section-title">🎬 六策略動畫說明</div>
    <div class="strategy-links">
      {video_links}
    </div>
  </div>
  <footer>TW SelfSelect · 資料不構成投資建議 · {updated_at}</footer>
</div>
<script>
const DATA = {charts_json};

// ─── 合併累積損益曲線 ───
(function() {{
  const canvas = document.getElementById('chartPnlCombined');
  if (!canvas || !DATA.labels || !DATA.labels.length) return;
  const ds = [];
  if (DATA.curve_g1 && DATA.curve_g1.some(v => v !== null))
    ds.push({{ label: 'Group 1', data: DATA.curve_g1, borderColor: '#e74c3c',
             backgroundColor: 'rgba(231,76,60,.08)', fill: 1, tension: .3, pointRadius: 3 }});
  if (DATA.curve_g2 && DATA.curve_g2.some(v => v !== null))
    ds.push({{ label: 'Group 2', data: DATA.curve_g2, borderColor: '#2980b9',
             backgroundColor: 'rgba(41,128,185,.08)', fill: 2, tension: .3, pointRadius: 3 }});
  if (!ds.length) return;
  new Chart(canvas, {{
    type: 'line',
    data: {{ labels: DATA.labels, datasets: ds }},
    options: {{ responsive: true,
               scales: {{ y: {{ ticks: {{ callback: v=>v+'元' }} }} }} }}
  }});
}})();

// ─── Group 1 各標的損益 ───
(function() {{
  const canvas = document.getElementById('chartSymbolsG1');
  if (!canvas || !DATA.symbol_stats_g1 || !DATA.symbol_stats_g1.length) return;
  new Chart(canvas, {{
    type: 'bar',
    data: {{ labels: DATA.symbol_stats_g1.map(s=>s.symbol),
            datasets: [{{ label: '損益', data: DATA.symbol_stats_g1.map(s=>s.pnl),
                         backgroundColor: DATA.symbol_stats_g1.map(s=>s.pnl>=0?'rgba(231,76,60,.7)':'rgba(52,152,219,.7)') }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }},
               scales: {{ y: {{ ticks: {{ callback: v=>v+'元' }} }} }} }}
  }});
}})();

// ─── Group 2 各標的損益 ───
(function() {{
  const canvas = document.getElementById('chartSymbolsG2');
  if (!canvas || !DATA.symbol_stats_g2 || !DATA.symbol_stats_g2.length) return;
  new Chart(canvas, {{
    type: 'bar',
    data: {{ labels: DATA.symbol_stats_g2.map(s=>s.symbol),
            datasets: [{{ label: '損益', data: DATA.symbol_stats_g2.map(s=>s.pnl),
                         backgroundColor: DATA.symbol_stats_g2.map(s=>s.pnl>=0?'rgba(231,76,60,.7)':'rgba(52,152,219,.7)') }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }},
               scales: {{ y: {{ ticks: {{ callback: v=>v+'元' }} }} }} }}
  }});
}})();
</script>
</body>
</html>"""
    return html


def trade_count_summary(df) -> dict:
    """儀表板產生後的摘要計數：已實現（賣出配對）／買進／總列數。

    ⚠️ 2026-10-19：原本 main() 只印「（N 筆交易）」，N 取自 `compute_pnl()` 的長度，
    而 `compute_pnl()` 回的是**已實現（賣出配對）** ⇒ 只有買進的日子永遠印「0 筆交易」，
    看起來像沒成交（當天 13:26 五檔自選股全成交、頁面也有，卻印 0）。改成三個數字都印。
    """
    if df is None or getattr(df, 'empty', True):
        return {"realized": 0, "buys": 0, "rows": 0}
    if 'group' in df.columns:
        realized = len(compute_pnl(df[df['group'] == 1])) + len(compute_pnl(df[df['group'] == 2]))
    else:
        realized = len(compute_pnl(df))
    buys = 0
    if 'action' in df.columns:
        buys = int((df['action'].astype(str).str.upper().str.strip() == 'BUY').sum())
    return {"realized": realized, "buys": buys, "rows": int(len(df))}


def main():
    df = load_trades()
    if df.empty:
        print("⚠️  performance.csv 不存在或為空，產生空白儀表板")
    html = build_html(df)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    # count total trades
    s = trade_count_summary(df)
    print(f"✅ dashboard.html 已產生（已實現 {s['realized']} 筆／買進 {s['buys']} 筆／共 {s['rows']} 列）")


if __name__ == "__main__":
    main()
