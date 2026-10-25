"""core/drawdown_guard.py — 帳戶層重大回撤保護（MIN_DRAW_BACK）＋總資產口徑

語義（與回測的 `min_drawback` 一致，最多延長一次）：
- 選股／換股日，帳戶總回撤（自歷史峰值）> `MIN_DRAW_BACK`% → **本次不換股、續抱**；
- 若上次已延長且回撤仍超標 → 照常換股（強制）；回撤恢復 → 照常換股。

資產模型：equity = **現金** + 持股市值。
          現金 = TOTAL_CAPITAL + 淨現金流（Σ賣出 − Σ買進 − Σ手續費/稅，`logs/performance.csv` 全歷史）。

口徑關係（2026-09-13 對帳證明）：
    A（本檔 `compute_equity`）        = TC + 淨現金流 + 持股市值(holdings.json)
    B（`scripts/generate_dashboard`）= TC + FIFO已實現 + 持股市值 − Σ分帳本成本
    兩者**代數上恆等**：`B − A ≡ Σ未平倉成本基礎(CSV 推算) − Σ分帳本成本基礎`
    證明：`FIFO 已實現 = 淨現金流 + Σ未平倉成本基礎`
    ⇒ 帳務一致時 A ≡ B；不一致時差額就是「分帳本缺少的成本基礎」（幽靈部位）。

⚠️ 歷史更正（勿再引用舊敘述）：本檔前身 2026-09-13 曾寫「舊版把 TOTAL_CAPITAL 當成現金
   直接加持股市值 → 重複計算」——**該敘述是錯的**。最簡反例：TC=1000、買 10 股 @10 後
   `TC + 淨現金流 + 市值 = 1000` ✓（若再扣成本會得到 900 ✗）。
   `compute_equity` 本來就是對的，真正的問題是分帳本與 performance.csv 不同步。

峰值／延長狀態持久化於 `logs/equity_peak.json` 與 `logs/drawdown_hold.json`。
"""
import csv
import os

from core.live_state import load_json, save_json

# 路徑錨定專案根目錄（__file__），不依賴 CWD ——
# 這樣 bot（container CWD=/app）、手動工具、任何 CWD 都會寫到同一組 logs/ 檔。
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PEAK_FILE = os.path.join(_ROOT, "logs", "equity_peak.json")
HOLD_FILE = os.path.join(_ROOT, "logs", "drawdown_hold.json")
PERF_FILE = os.path.join(_ROOT, "logs", "performance.csv")

ENV_FILE = os.path.join(_ROOT, ".env")
HOLDINGS_FILE = os.path.join(_ROOT, "logs", "holdings.json")


def net_cash_flow(performance_csv=None):
    """**淨現金流** = Σ賣出金額 − Σ買進金額 − Σ交易成本（performance.csv 全歷史）。

    ⚠️ 這**不是**儀表板的「總已實現損益」（那是 FIFO 配對的平倉損益；兩者相差
    「未平倉部位的成本基礎」等項目）。用途：由身分式
    `現金 = TOTAL_CAPITAL + 淨現金流` 推總資產。

    **2026-09-17 起扣掉交易成本**（手續費＋賣出證交稅）：`Σ賣 − Σ買 − Σ成本`。
    費用取 CSV 的 `cost` 欄（有記錄用記錄值），舊列沒有該欄則以現行費率推定
    （見 `core/fees.row_cost`）。不扣費用會讓總資產虛高。
    """
    performance_csv = performance_csv or PERF_FILE
    buys = 0.0
    sells = 0.0
    costs = 0.0
    if not os.path.exists(performance_csv):
        return 0.0
    from core import fees as _fees
    with open(performance_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                px = float(row.get("price", 0))
                qty = float(row.get("quantity", 0))
            except (TypeError, ValueError):
                continue
            action = str(row.get("action", "")).strip().upper()
            if action == "BUY":
                buys += px * qty
            elif action == "SELL":
                sells += px * qty
            costs += _fees.row_cost(row)
    return sells - buys - costs


def compute_equity(total_capital, holdings, prices, performance_csv=None):
    """總資產 = TOTAL_CAPITAL + 淨現金流 + 持股市值 ＝ **現金 + 持股市值**。

    身分式（每次買賣都即時反映現金）：`現金 = TOTAL_CAPITAL + (Σ賣出 − Σ買進)`。
    → 持股市值與現金是**兩個互斥的資產項**，相加才等於總資產。
    """
    mkt_value = sum(shares * prices.get(sym, 0.0) for sym, shares in holdings.items())
    return total_capital + net_cash_flow(performance_csv) + mkt_value


realized_pnl = net_cash_flow   # 舊名相容；新程式請用 net_cash_flow


def should_hold(min_drawback, equity, peak, state):
    """回傳 (hold, new_state)。min_drawback<=0 或資料異常 → 不延後（照常換股）。"""
    if min_drawback <= 0 or equity <= 0 or peak <= 0:
        return False, {"extended": False}
    dd = equity / peak - 1.0
    extended = bool((state or {}).get("extended"))
    if dd < -min_drawback / 100.0:
        if extended:
            return False, {"extended": False}
        return True, {"extended": True}
    return False, {"extended": False}


def _evaluate_drawdown(min_drawback, equity, total_capital, today_str):
    """讀峰值 → 判回撤 → 寫回狀態。回傳 (hold, dd)。"""
    peak = load_json(PEAK_FILE, {}) or {}
    peak_val = float(peak.get("peak", 0) or 0)
    if peak_val <= 0:
        peak_val = max(float(total_capital), equity)
    hold, new_state = should_hold(min_drawback, equity, peak_val, load_json(HOLD_FILE, {}) or {})
    save_json({"peak": max(peak_val, equity), "updated_at": today_str}, PEAK_FILE)
    save_json(new_state, HOLD_FILE)
    return hold, equity / peak_val - 1.0


def check_drawdown_prices(min_drawback, total_capital, holdings, prices, today_str,
                          performance_csv=None):
    """**選股端守門（B2）**：用呼叫端既有的價格做回撤檢查，**不需要 broker**。

    為什麼要放在選股程式本體（2026-09-13）：檢查若只寫在 bot 的排程區塊，直接跑
    `scripts/stock_selector_grid.py` 的「手動選股」就完全沒有防護（兩條路徑要同一道守門）。

    取不到任一持股價格 → fail-open（hold=False、dd=None），避免資料缺口卡住換股。
    """
    if min_drawback <= 0:
        return False, None
    try:
        px = {}
        for sym in holdings:
            s = str(sym)
            v = prices.get(s)
            if v is None:
                v = prices.get(sym)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = 0.0
            if fv <= 0:
                print(f"⚠️ MIN_DRAW_BACK: {s} 無法取得現價，本次檢查略過（照常換股）")
                return False, None
            px[s] = fv
        holdings_n = {str(k): v for k, v in holdings.items()}
        equity = compute_equity(total_capital, holdings_n, px, performance_csv)
        return _evaluate_drawdown(min_drawback, equity, total_capital, today_str)
    except Exception as e:
        print(f"⚠️ MIN_DRAW_BACK 檢查失敗，照常換股: {e}")
        return False, None


def check_drawdown(min_drawback, total_capital, broker, holdings, today_str,
                   performance_csv=None):
    """（bot 用）以 broker 取價後交給 `check_drawdown_prices`。

    broker=None（或取價失敗）→ 無法取得現價 → fail-open 回 (False, None)。
    """
    if min_drawback <= 0:
        return False, None
    if broker is None:
        print("⚠️ MIN_DRAW_BACK: 未提供 broker，無法取價，本次檢查略過（照常換股）")
        return False, None
    prices = {}
    for sym in holdings:
        s = str(sym)
        try:
            v = broker.get_current_price(s)
        except Exception as e:
            print(f"⚠️ MIN_DRAW_BACK: {s} 取價失敗（{e}），本次檢查略過（照常換股）")
            return False, None
        if v is None or float(v) <= 0:
            print(f"⚠️ MIN_DRAW_BACK: {s} 無法取得現價，本次檢查略過（照常換股）")
            return False, None
        prices[s] = float(v)
    return check_drawdown_prices(min_drawback, total_capital, holdings, prices, today_str,
                                performance_csv=performance_csv)


def load_env_value(key, default="", env_path=None):
    """讀 `.env` 的單一鍵（**剝除行內註解**）。

    為何不用 os.environ：選股程式會被手動執行，且 bot 是用 subprocess 呼叫它，
    `MIN_DRAW_BACK` / `TOTAL_CAPITAL` 不一定在 os.environ 裡。
    註：`.env` 的值常常帶行內註解（`MIN_DRAW_BACK=30   # …`），
    舊的 `int(line.split("=")[1])` 會直接 ValueError 並被 except 吞掉 → 靜默用預設值。
    """
    path = env_path or ENV_FILE
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return default


def load_holdings(path=None):
    """讀持股 {代號: 股數}（只保留 >0 的）。"""
    h = load_json(path or HOLDINGS_FILE, {}) or {}
    out = {}
    for k, v in h.items():
        if isinstance(v, dict):
            v = v.get("qty", 0)
        try:
            q = float(v)
        except (TypeError, ValueError):
            continue
        if q > 0:
            out[str(k)] = v
    return out


def collect_holding_prices(holdings, price_map=None, fallback_loader=None):
    """為每檔持倉取現價：優先用 `price_map`，其次用 `fallback_loader(sym)->df`。

    任一檔取不到 → 回 None（呼叫端據此 fail-open，不卡住換股）。
    """
    price_map = price_map or {}
    out = {}
    for sym in holdings:
        s = str(sym)
        v = price_map.get(s)
        if v is None and fallback_loader is not None:
            try:
                df = fallback_loader(s)
                if df is not None and not getattr(df, "empty", True):
                    v = float(df["close"].iloc[-1])
            except Exception:
                v = None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        if fv <= 0:
            return None
        out[s] = fv
    return out


def mdb_guard(price_map, today_str=None, holdings=None, env_path=None,
              holdings_path=None, perf_path=None, fallback_loader=None):
    """**選股端 MIN_DRAW_BACK 守門（共用進入點）**。回傳 (blocked, dd)。

    blocked=True → 呼叫端應**中止且不輸出 .env**（＝本次續抱）。
    任何一步失敗（讀不到 env / 無持倉 / 取不到價）→ fail-open（False, None）。
    """
    try:
        min_drawback = float(load_env_value("MIN_DRAW_BACK", "0", env_path) or 0)
        if min_drawback <= 0:
            return False, None
        total_capital = float(load_env_value("TOTAL_CAPITAL", "0", env_path) or 0)
        if total_capital <= 0:
            print("⚠️ MIN_DRAW_BACK: 讀不到 TOTAL_CAPITAL，本次檢查略過（照常換股）")
            return False, None
        h = holdings if holdings is not None else load_holdings(holdings_path)
        if not h:
            return False, None
        prices = collect_holding_prices(h, price_map, fallback_loader)
        if prices is None:
            print("⚠️ MIN_DRAW_BACK: 有持股取不到現價，本次檢查略過（照常換股）")
            return False, None
        if today_str is None:
            from datetime import datetime as _dt
            today_str = _dt.now().strftime("%Y-%m-%d")
        return check_drawdown_prices(min_drawback, total_capital, h, prices, today_str,
                                     performance_csv=perf_path or PERF_FILE)
    except Exception as e:
        print(f"⚠️ MIN_DRAW_BACK 檢查失敗，照常換股: {e}")
        return False, None
