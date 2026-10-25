import json
import os
from datetime import datetime

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(data, filepath):
    """原子寫入 + 跨行程檔案鎖（2026-09-13 改）。

    舊版直接 `open(filepath, "w")` 寫資料檔：
      * 寫到一半被砍（VM cron 曾在盤中關機）→ 留下半截 JSON；
      * 兩個 writer 同時寫（bot 主迴圈 + 子行程／`core/live_capital.py`）
        → 後寫的整份蓋掉先寫的（lost update）。
    實作在 `core/books.py`（與對帳腳本共用同一套鎖語義）。
    """
    from core.books import atomic_write_json
    atomic_write_json(filepath, data, indent=4)

def load_monthly_budget() -> dict: return load_json("logs/monthly_budget.json", {})
def save_monthly_budget(spent: dict): save_json(spent, "logs/monthly_budget.json")

def check_monthly_budget(symbol: str, cost: float, spent: dict, limit: float) -> bool:
    if limit <= 0: return True
    return spent.get(symbol, 0.0) + cost <= limit

def update_monthly_spending(symbol: str, cost: float, spent: dict):
    spent[symbol] = spent.get(symbol, 0.0) + cost
    save_monthly_budget(spent)

def load_stock_allocation() -> dict: return load_json("logs/stock_allocation.json", {})
def save_stock_allocation(alloc: dict): save_json(alloc, "logs/stock_allocation.json")

SYMBOL_LEDGER_DEFAULT = {"total_buy_cost": 0, "total_buy_shares": 0}


def ensure_symbol_ledgers(alloc: dict, symbols) -> dict:
    """確保每個代號在分帳本裡都有完整欄位（就地補齊缺的代號／欄位），回傳同一個 dict。

    為什麼要有這支（2026-10-01 實盤事故，真錢）：
      `logs/stock_allocation.json` 只在**啟動時**載入；而「改 `.env` 名單 → 熱重載當天生效」
      （V4.36／V4.38）會讓 `PORTFOLIO_CONFIG` 冒出新代號，卻沒同步分帳本
      ⇒ 買進後的 `stock_alloc[symbol]['total_buy_cost'] += cost` 直接 `KeyError`。
      實際後果：三筆單**都成交**，但記帳中斷 ⇒ 分帳本缺檔（資金利用率不準）＋
      成交通知沒發（例外在 `send_trade_alert` 之前）＋ 誤發 `⚠️ *2409* 買入失敗：'2409'` 告警。
    """
    for sym in symbols:
        st = alloc.get(sym)
        if not isinstance(st, dict):
            alloc[sym] = dict(SYMBOL_LEDGER_DEFAULT)
            continue
        for k, v in SYMBOL_LEDGER_DEFAULT.items():
            st.setdefault(k, v)
    return alloc


def check_stock_cap(symbol: str, cost: float, alloc: dict, cap: float) -> bool:
    return alloc.get(symbol, 0.0) + cost <= cap

def update_stock_allocation(symbol: str, cost: float, action: str, alloc: dict):
    if action == "buy": alloc[symbol] = alloc.get(symbol, 0.0) + cost
    elif action == "sell": alloc[symbol] = max(0.0, alloc.get(symbol, 0.0) - cost)
    save_stock_allocation(alloc)

def load_holdings() -> dict: return load_json("logs/holdings.json", {})
def save_holdings(h: dict): save_json(h, "logs/holdings.json")

def held_quantities(data: dict) -> dict:
    """把 `logs/holdings.json` 正規化成 `{代號: 股數}`（只留 >0）——**全專案唯一實作**。

    為什麼要有這支（2026-09-22 修 bug）：實盤寫入的是 `{sym: int}`（`save_holdings(holdings)`，
    例：`{"2006": 689}`），但 `scripts/monthly_rebalance_picker.read_actual_holdings()` 只認
    `{sym: {"qty": N}}`（舊/備援格式，`update_holdings()` 才會產生、實盤沒在用）
    ⇒ **picker 的「已持倉一律保留」規則從來沒生效**：它眼中的「已持倉」永遠是空的，
    於是把**實際持有中**的股票也列進「賣出（汰換）」名單（2026-09-22 的 2006／3515 實例）。
    兩種格式都吃，就不會再因為格式假設不同而靜默失效。
    """
    out = {}
    for k, v in (data or {}).items():
        qty = None
        if isinstance(v, dict):
            qty = v.get("qty", 0)
        elif isinstance(v, (int, float, str)):
            qty = v
        try:
            q = int(float(qty))
        except (TypeError, ValueError):
            continue
        if q > 0:
            out[str(k)] = q
    return out


def update_holdings(symbol: str, qty: int, price: float, action: str, h: dict):
    if symbol not in h: h[symbol] = {"qty": 0, "avg_price": 0.0}
    current = h[symbol]
    if action == "buy":
        total_cost = current["qty"] * current["avg_price"] + qty * price
        current["qty"] += qty
        current["avg_price"] = total_cost / current["qty"] if current["qty"] > 0 else 0
    elif action == "sell":
        current["qty"] -= qty
        if current["qty"] <= 0:
            current["qty"] = 0
            current["avg_price"] = 0.0
    save_holdings(h)

def load_last_trade_times() -> dict: return load_json("logs/last_trade_times.json", {})
def save_last_trade_times(times: dict): save_json(times, "logs/last_trade_times.json")

def load_daily_trades():
    data = load_json("logs/daily_trades.json", {})
    if isinstance(data, dict):
        return (data, data.get("_date"))
    return (data, None)

def save_daily_trades(trades: dict, date_str: str):
    trades["_date"] = date_str
    save_json(trades, "logs/daily_trades.json")
    
def load_processed_capital(filepath: str = "logs/processed_capital.json") -> list:
    return load_json(filepath, [])
    
def save_processed_capital(processed: list, filepath: str = "logs/processed_capital.json"):
    save_json(processed, filepath)
