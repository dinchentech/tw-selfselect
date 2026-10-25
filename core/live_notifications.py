import requests
import os
import json
from utils.telegram import send_telegram_message

def send_line_notification(message):
    line_token = os.getenv("LINE_NOTIFY_TOKEN")
    if not line_token:
        return
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {line_token}"}
    payload = {"message": message}
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=5)
        if response.status_code != 200:
            print(f"LINE Notify 發送失敗: {response.text}")
    except Exception as e:
        print(f"LINE Notify 發送異常: {e}")

def notify_all(message):
    send_telegram_message(message)
    send_line_notification(message)

def _as_date(value):
    """把「呼叫端傳進來的日期提供者」正規化成 `datetime.date`（2026-09-16 修）。

    背景：呼叫端歷史上是 `send_daily_report(pd, datetime)` —— 傳的是 `datetime` **類別**，
    `date.today()` 因此回傳 **datetime**（帶時分秒），而下面拿它跟 `df["timestamp"].dt.date`
    比對 ⇒ 「date vs datetime」**永遠不相等** ⇒ 每天都誤判成「今日無交易紀錄」
    （實盤症狀：09-16 明明有 SELL 2006，日報卻是空的）。
    這裡同時接受 `date` 類別、`datetime` 類別或已正規化的日期物件。
    """
    today = value.today()
    return today.date() if hasattr(today, "date") else today


def send_daily_report(pd, date):
    """讀取 logs/performance.csv，產生今日交易摘要發送到 Telegram

    ⚠️ 第二個參數是**日期提供者**（`datetime.date` 或 `datetime.datetime` 類別，需有 `.today()`），
    不是日期字串；建議呼叫端直接傳 `date`（傳 `datetime` 也能正確運作，見 `_as_date`）。
    """
    from pathlib import Path
    csv_path = Path("logs/performance.csv")
    if not csv_path.exists():
        notify_all("📊 *今日交易日報*\n📅 今日無交易紀錄")
        return

    try:
        df = pd.read_csv(csv_path, on_bad_lines='skip')
        if df.empty:
            return
        today = _as_date(date)
        df["timestamp"] = pd.to_datetime(df["timestamp"], format='mixed')
        today_df = df[df["timestamp"].dt.date == today]
    except Exception as e:
        notify_all(f"❌ 讀取交易紀錄失敗: {e}")
        return

    if today_df.empty:
        notify_all("📊 *今日交易日報*\n📅 今日無交易紀錄")
        return

    buys = today_df[today_df["action"].str.upper() == "BUY"]
    sells = today_df[today_df["action"].str.upper() == "SELL"]

    msg = f"📊 *今日交易日報 ({today.isoformat()})*\n"
    msg += "─" * 20 + "\n"

    if not buys.empty:
        msg += "🔹 *買進*\n"
        for _, row in buys.iterrows():
            t = pd.Timestamp(row["timestamp"]).strftime("%H:%M")
            s = row["symbol"]
            msg += f"  {s}  {t}  @${row['price']:.2f}  {int(row['quantity'])}股\n"
        total_buy = (buys["price"] * buys["quantity"]).sum()
        msg += f"  買進總成本: NT${total_buy:,.0f}\n"

    if not sells.empty:
        msg += "🔸 *賣出*\n"
        for _, row in sells.iterrows():
            t = pd.Timestamp(row["timestamp"]).strftime("%H:%M")
            s = row["symbol"]
            msg += f"  {s}  {t}  @${row['price']:.2f}  {int(row['quantity'])}股\n"
        total_sell = (sells["price"] * sells["quantity"]).sum()
        msg += f"  賣出總收入: NT${total_sell:,.0f}\n"

    msg += "─" * 20
    notify_all(msg)


def _strategy_label(symbol, portfolio_config, auto_resolved):
    """回傳持倉要顯示的策略標籤（2026-09-11 新增）。

    - 一般策略：直接顯示名稱（keep_wait / breakout / bollinger …）
    - `auto`  ：顯示**買入時鎖定的策略**，例如 `auto→bollinger`。
      鎖定值在買入瞬間由 live_trader_multi.py 寫入 `logs/auto_resolved.json`
      （「把 auto 鎖定成固定策略(依當下型態)，之後持有期間不變」），
      所以這裡讀到的是**當初的決定**，不是重新路由的今日結果。
      查不到鎖定紀錄時顯示 `auto→?`（誠實標示未知——例如 0 股殘留或檔案遺失）。

    回傳 None 表示不顯示標籤（該檔不在 `PC_` 設定裡，例如已從 .env 移除）。
    """
    cfg = (portfolio_config or {}).get(str(symbol)) or {}
    sn = cfg.get("strategy")
    if not sn:
        return None
    if sn != "auto":
        return sn
    fixed = (auto_resolved or {}).get(str(symbol))
    return f"auto→{fixed}" if fixed else "auto→?"


def price_date_note(price_dates: dict, today_str: str) -> str:
    """標示「參考市價」的**資料日期**；非當日要示警（2026-09-16）。

    🔗 **TG 持倉報告與 GitHub Pages 儀表板共用這一個 helper**（2026-10-06 起）——
    起因：使用者比對兩邊的 2059 損益（−12,465 vs −64,650）發現不一致，追查後確認
    兩邊都走 TWSE MIS，但**儀表板是靜態快照、TG 是即時**，而儀表板當時沒顯示價格日期 ⇒
    看不出「誰是舊的」。現在兩邊印同一串字（`📈 參考市價：<日期>`，非當日加 `⚠️非當日`），
    口徑不可能漂移。

    為什麼：報告原本走 TWSE STOCK_DAY（盤後才更新）⇒ 13:45 的收盤報告用的是**前一日**收盤價
    （實測 09-16 顯示 09-15 價格），使用者看到的損益系統性偏舊。現在價格改取當日報價，
    這裡再把日期寫出來，讓「舊數字」不可能再默默出現。
    """
    dates = sorted({str(d) for d in (price_dates or {}).values() if d})
    if not dates:
        return ''
    if len(dates) == 1:
        d = dates[0]
        return f"📈 參考市價：{d}" + ('' if d == today_str else ' ⚠️非當日')
    return f"📈 參考市價：{'、'.join(dates)}（部分標的日期不同）"


def _build_holdings_message(pd, app_version, title_emoji, title, total_capital=None,
                            portfolio_config=None):
    """讀取 logs/holdings.json 並組裝持倉訊息文字（共用 helper，不發送）

    注意：參數 `pd` 是 **pandas 模組**（供 `pd.read_csv`/`pd.Timestamp` 使用），
    不是投資組合資料；投資組合設定請用 `portfolio_config`。

    `portfolio_config` 為 `{代號: {strategy, alloc, ...}}`（`load_portfolio_config()` 的結果）。
    未傳時自行讀取，方便舊呼叫端與測試。
    """
    import json
    from pathlib import Path
    from datetime import datetime

    holdings_path = Path("logs/holdings.json")
    alloc_path = Path("logs/stock_allocation.json")
    csv_path = Path("logs/performance.csv")
    auto_path = Path("logs/auto_resolved.json")

    if not holdings_path.exists():
        return None

    with open(holdings_path) as f:
        holdings = json.load(f)
    if not holdings:
        return None

    alloc = {}
    if alloc_path.exists():
        with open(alloc_path) as f:
            alloc = json.load(f)

    # auto 買入時鎖定的策略（買入瞬間寫入，持有期間不變）
    auto_resolved = {}
    if auto_path.exists():
        try:
            with open(auto_path) as f:
                auto_resolved = json.load(f) or {}
        except (ValueError, OSError):
            auto_resolved = {}

    if portfolio_config is None:
        try:
            from core.config_loader import load_portfolio_config
            portfolio_config = load_portfolio_config()
        except Exception:
            portfolio_config = {}

    date_str = datetime.now().strftime("%Y-%m-%d")
    msg = f"{title_emoji} *{title} ({date_str})* V{app_version}\n"
    msg += "─" * 20 + "\n"

    market_prices = {}
    price_dates = {}
    try:
        from core.inst_data import fetch_latest_closes_dated
        for _sym, _v in (fetch_latest_closes_dated([str(s) for s in holdings.keys()]) or {}).items():
            market_prices[str(_sym)] = _v.get('price')
            if _v.get('date'):
                price_dates[str(_sym)] = _v['date']
    except Exception:
        pass

    _pd_note = price_date_note(price_dates, date_str)
    if _pd_note:
        msg += _pd_note + "\n"

    total_cost = 0
    total_value = 0
    total_unrealized = 0

    for sym in sorted(holdings.keys()):
        shares = holdings.get(sym, 0)
        if isinstance(shares, dict):
            qty = shares.get("qty", 0)
            if qty <= 0:
                continue
            avg_cost = shares.get("avg_price", 0)
            shares = qty
        else:
            if shares <= 0:
                continue
            avg_cost = 0
            alloc_data = alloc.get(sym, {})
            if isinstance(alloc_data, dict) and alloc_data.get("total_buy_shares", 0) > 0:
                avg_cost = alloc_data["total_buy_cost"] / alloc_data["total_buy_shares"]

        current_price = market_prices.get(str(sym))
        if current_price is None:
            current_price = avg_cost
            if csv_path.exists():
                try:
                    df = pd.read_csv(csv_path, on_bad_lines='skip')
                    sym_df = df[df["symbol"] == str(sym)]
                    if not sym_df.empty:
                        current_price = sym_df["price"].iloc[-1]
                        if avg_cost == 0:
                            avg_cost = current_price
                except Exception:
                    pass

        cost_basis = avg_cost * shares if avg_cost > 0 else 0
        market_value = current_price * shares
        unrealized = market_value - cost_basis
        pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

        total_cost += cost_basis
        total_value += market_value
        total_unrealized += unrealized

        emoji = "🟢" if unrealized >= 0 else "🔴"
        _label = _strategy_label(sym, portfolio_config, auto_resolved)
        _strat_txt = f" | {_label}" if _label else ""
        msg += f"{emoji} {sym}: {shares}股{_strat_txt}\n"
        msg += f"   成本均價 {avg_cost:,.0f} | 參考市價 {current_price:,.0f}\n"
        msg += f"   未實現損益 {unrealized:+,.0f} ({pct:+.2f}%)\n"

    msg += "─" * 20 + "\n"
    msg += f"總成本: NT${total_cost:,.0f}\n"
    msg += f"總市值: NT${total_value:,.0f}\n"
    msg += f"未實現損益: {'+' if total_unrealized >= 0 else ''}{total_unrealized:,.0f}\n"
    # ── 資本三項：原始(env) / 投入(現行) / 現有(投入−已買入成本) ──
    if total_capital is not None:
        _orig = float(os.getenv('TOTAL_CAPITAL_ORIGINAL', total_capital))
        _inv = sum(float(v.get('total_buy_cost', 0) or 0) for v in alloc.values() if isinstance(v, dict))
        _avail = total_capital - _inv
        msg += f"原始投資資本: NT${_orig:,.0f}\n"
        msg += f"投入資本(含滾入): NT${total_capital:,.0f}\n"
        msg += f"現有資本(可買股): NT${_avail:,.0f}\n"
    return msg


def send_sleep_notification(pd, app_version, next_open, total_capital=None, portfolio_config=None):
    """發送睡前持倉報告到 Telegram"""
    import os
    from datetime import datetime
    footer = f"💤 休眠到 {next_open.strftime('%m/%d %H:%M')}" if next_open else ""
    msg = _build_holdings_message(pd, app_version, "💤", "睡前持倉報告", total_capital, portfolio_config)
    if msg is None:
        msg = f"💤 *睡前持倉報告 ({datetime.now().strftime('%Y-%m-%d')})* V{app_version}\n"
        msg += "─" * 20 + "\n📭 目前無持倉\n"

    if footer and "休眠" not in msg:
        msg += footer
    notify_all(msg)
    print("✅ 睡前持倉報告已發送")


def send_startup_holdings(pd, app_version, total_capital=None, portfolio_config=None):
    """發送啟動持倉報告到 Telegram"""
    msg = _build_holdings_message(pd, app_version, "🚀", "啟動持倉報告", total_capital, portfolio_config)
    if msg:
        notify_all(msg)
        print("✅ 啟動持倉報告已發送")


def send_closing_summary(pd, app_version, total_capital=None, portfolio_config=None):
    import os
    from datetime import datetime
    try:
        msg = _build_holdings_message(pd, app_version, "📋", "收盤持倉報告", total_capital, portfolio_config)
        if msg is None:
            return

        notify_all(msg)
        print("✅ 收盤持倉報告已發送")
    except Exception as e:
        print(f"❌ 發送收盤持倉報告失敗: {e}")






# 向後相容：舊名（私有）仍可用
_price_date_note = price_date_note
