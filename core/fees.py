"""core/fees.py — 台股交易成本（手續費 + 證交稅）**唯一實作**

為什麼需要（2026-09-17）：實盤與儀表板原本**完全沒有費用**——
回測腳本各自有 `BUY_COST` 常數時，請以本模組為準。
`RiskManager.log_trade` 只記 `價 × 股數`、`sell_stock_allocation` 用 `px × shares`
當賣出收入 ⇒ 儀表板顯示的「累積損益」是**毛額**。
按玉山牌告 0.1425%（最低 NT$20）＋ 證交稅 0.3% 估算，同一批交易實際約為 −7,800 而非 +5,516。

規則（台股慣例，皆可用 `.env` 覆寫）：
- **手續費**：`max(MIN_FEE, round(金額 × FEE_RATE))`，買賣**都**收。
- **證交稅**：`round(金額 × SELL_TAX_RATE)`，**只課賣出**（股票 0.3%；ETF 0.1%）。
- 金額一律是「成交價 × 股數」，不含費用本身。

⚠️ **費率依你的券商折數而異**：玉山牌告 0.1425%，常見折扣戶 6 折＝0.0855%。
   請在 `.env` 設 `FEE_RATE` 為**你的實際費率**；設錯會讓所有損益偏掉。
⚠️ 本模組算的是**推定值**（券商回報在模擬環境取不到）；但 `log_trade` 會把當下算出的
   金額寫進 CSV 的 `cost` 欄 → **歷史數字被凍結**，日後改費率不會回改過去。
"""
import os

# 預設＝玉山牌告（可用 .env 覆寫；每次呼叫都重讀，避免 import 時快取住）
DEFAULT_FEE_RATE = 0.001425
DEFAULT_MIN_FEE = 20.0
DEFAULT_SELL_TAX_RATE = 0.003


def _env_float(key, default):
    """讀 .env／環境變數。先看 os.environ（bot 內 dotenv 已載入），再看 .env 檔（手動工具）。"""
    raw = os.getenv(key)
    if raw is None:
        try:
            from core.drawdown_guard import load_env_value
            raw = load_env_value(key, "")
        except Exception:
            raw = ""
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def fee_rate():
    return _env_float("FEE_RATE", DEFAULT_FEE_RATE)


def min_fee():
    return _env_float("MIN_FEE", DEFAULT_MIN_FEE)


def sell_tax_rate():
    return _env_float("SELL_TAX_RATE", DEFAULT_SELL_TAX_RATE)


def _money(x):
    """金額取整到元 —— **四捨五入**（券商慣例）。

    ⚠️ 不能用 Python 內建 `round()`：那是「銀行家進位」，`round(142.5) == 142`，
    與券商算法差 1 元（2026-09-17 寫測試時踩到）。正數用 `int(x + 0.5)` 才是四捨五入。
    """
    return float(int(float(x) + 0.5))


def buy_fee(amount):
    """買進手續費。"""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    return max(min_fee(), _money(amount * fee_rate()))


def sell_fee(amount):
    """賣出手續費（與買進同費率、同最低門檻）。"""
    return buy_fee(amount)


def sell_tax(amount):
    """證交稅（只課賣出）。"""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    return _money(amount * sell_tax_rate())


def sell_cost(amount):
    """賣出總成本 = 手續費 + 證交稅。"""
    return sell_fee(amount) + sell_tax(amount)


def tx_cost(action, amount):
    """依買/賣回傳該筆交易的總成本。"""
    act = str(action or "").strip().upper()
    if act == "SELL":
        return sell_cost(amount)
    if act == "BUY":
        return buy_fee(amount)
    return 0.0


def effective_rate(action, amount):
    """實效費率（＝成本 ÷ 金額）——用來量化「小單吃最低手續費」的浪費。"""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    return tx_cost(action, amount) / amount


def breakeven_amount():
    """最低手續費的損益兩平金額（＝MIN_FEE ÷ FEE_RATE，牌告下約 NT$14,035）。

    低於此金額的委託，實效費率高於牌告 ⇒ 小額補單門檻（`MIN_TOPUP_AMOUNT`）的依據。
    """
    rate = fee_rate()
    if rate <= 0:
        return 0.0
    return min_fee() / rate


def row_cost(row):
    """從 performance.csv 的一列取成本：**有記錄用記錄值**（歷史真實），否則用費率推定。

    舊列沒有 `cost` 欄（2026-09-17 前的歷史）→ 以現行費率推定，並在報表註明。
    """
    raw = row.get("cost") if hasattr(row, "get") else None
    # ⚠️ 舊列（2026-09-17 前）沒有 cost 欄 → pandas 讀成 NaN，不是 None/""
    #    不擋掉的話 NaN 會污染整個總計（sum 出來是 nan）。用 math.isnan 判。
    if isinstance(raw, float) and raw != raw:      # NaN 自身不等於自身
        raw = None
    if raw not in (None, ""):
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    try:
        amount = float(row.get("price", 0)) * float(row.get("quantity", 0))
    except (TypeError, ValueError):
        return 0.0
    return tx_cost(row.get("action", ""), amount)


def total_for_rows(rows):
    """整批交易的費用合計。"""
    return sum(row_cost(r) for r in rows)
