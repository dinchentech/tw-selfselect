"""Live trader 公用函式（市場時間、輔助工具）"""
import os

from datetime import datetime, timedelta, time
import pytz

TAIPEI_TZ = pytz.timezone("Asia/Taipei")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(13, 30)


def _is_trading_date(d, calendar=None) -> bool:
    """該日期是否為台股交易日（用 `core.trading_calendar`，與下單判斷同一份日曆）。

    日曆檔壞掉時退回舊的「非週末即交易日」行為（不可因日曆問題讓主迴圈停擺）。
    """
    if d.weekday() >= 5:
        return False
    try:
        cal = calendar if calendar is not None else _get_calendar()
        if cal is None:
            return True
        return bool(cal.is_trading_day(d))
    except Exception:
        return True


def get_next_market_open(now: datetime, calendar=None) -> datetime:
    """
    回傳下一個台股開盤時間 (Asia/Taipei 09:00)。
    考量：
      - 開盤前（交易日）→ 當日 09:00
      - 盤中（交易日）  → 立即回傳（不延遲）
      - 收盤後／休市日  → **下一個交易日** 09:00（跳過週末**與國定假日**）

    ⚠️ 2026-09-25 修（使用者當場發現）：原本只跳過週末、**不認國定假日** ⇒ 2026-09-24（四）收盤後
    回報「下次開盤 09/25 09:00」，但 9/25 是中秋節、9/28 是教師節 ⇒ 正確答案是 **09/29**。影響：
      1. 睡前報告與 `💤 非交易時段，下次開盤 …` 訊息誤導（純訊息）；
      2. **更嚴重**：任何「排定下一個交易日才動作」的流程（例：自選股選股後的買進日）
         都用同一個函式排定 ⇒ 排到休市日就**永遠等不到那次動作**。
    日曆＝`core.trading_calendar`（`config/taiwan_holidays.json`），與 `is_trading_day()` 同一份。
    """
    now_tw = now.astimezone(TAIPEI_TZ) if now.tzinfo else TAIPEI_TZ.localize(now)

    def _ret(dt):
        return dt.astimezone(now.tzinfo) if now.tzinfo else dt.replace(tzinfo=None)

    today_open = now_tw.replace(hour=9, minute=0, second=0, microsecond=0)
    today_close = now_tw.replace(hour=13, minute=30, second=0, microsecond=0)

    if _is_trading_date(now_tw.date(), calendar):
        if now_tw < today_open:
            return _ret(today_open)                 # 開盤前 → 等今天開盤
        if now_tw <= today_close:
            return _ret(now_tw)                     # 盤中 → 立刻回傳（不 sleep）

    # 收盤後，或今天本來就休市 → 下一個「交易日」的 09:00
    next_day = now_tw.date() + timedelta(days=1)
    for _ in range(400):                            # 上限掃描（>1 年）避免萬一日曆壞掉變無窮迴圈
        if _is_trading_date(next_day, calendar):
            next_open = now_tw.replace(year=next_day.year, month=next_day.month, day=next_day.day,
                                       hour=9, minute=0, second=0, microsecond=0)
            return _ret(next_open)
        next_day += timedelta(days=1)
    # 保底：日曆整個壞掉時退回舊行為（只跳週末）
    fallback = now_tw + timedelta(days=1)
    while fallback.weekday() >= 5:
        fallback += timedelta(days=1)
    return _ret(fallback.replace(hour=9, minute=0, second=0, microsecond=0))


def notify_order_failure(symbol, error, notified, today_str, notify_fn, action="交易", retry_hint=None):
    """交易失敗的 TG 警示 — 每檔每日只發一次（避免每分鐘重試洗版）。

    notified: {symbol: 'YYYY-MM-DD'} 已警示紀錄（由呼叫端持有）
    retry_hint: 後續處理說明（預設依買/賣動作給出）
    回傳更新後的 notified dict。
    """
    if notified.get(symbol) == today_str:
        return notified
    notified[symbol] = today_str
    if retry_hint is None:
        if "賣出" in action or "清倉" in action or "trim" in action:
            retry_hint = "系統將於下一個交易日 09:00 自動重試。"
        else:
            retry_hint = "系統會自動重試至收盤；若當日無法成交，該季將少持此檔。"
    try:
        notify_fn(f"⚠️ *{symbol}* {action}失敗：{error}\n{retry_hint}")
    except Exception:
        pass
    return notified


def reconcile_order_qty(requested, order_ret):
    """券商**實際送出的股數**（有回報就用它，否則沿用我方算出的 `requested`）。

    為什麼需要（2026-09-23 實盤事故）：玉山 provider 對整股單會把數量四捨五入到「張」
    （`data/esun_provider.py`：餘數 ≥500 進位、<500 捨去），但 13:25 送單時 `check_fill()`
    還查不到成交（整股在 13:30 收盤撮合）⇒ `resolve_fill()` 回 `None` ⇒ 主程式沿用計畫股數記帳：

      · 2884 計畫 1584 股 → 實際送 2000 股（2 張），帳上只記 1584 股
      · 5876 計畫 1461 股 → 實際送 1000 股（1 張），帳上卻記 1461 股

    ⇒ `holdings.json`／`performance.csv`（成本基礎、未實現損益、儀表板、賣出股數）與券商庫存不一致。
    以 provider 回報的 `sent_qty`（別名 `qty`）記帳可解；**成交回報（`resolve_fill`→`check_fill`）仍然優先**，
    本函式只在「沒有可信成交回報」時當作保障。
    """
    if isinstance(order_ret, dict):
        for key in ("sent_qty", "qty"):
            q = order_ret.get(key)
            if not q:
                continue
            try:
                q = int(q)
                if q > 0:
                    return q
            except (TypeError, ValueError):
                pass
    try:
        return int(requested)
    except (TypeError, ValueError):
        return 0


def order_fill_price(order_ret, fallback):
    """記帳價：優先用 provider 回報的**實際送單價**（`sent_price`），否則沿用決策價。

    為什麼（2026-10-19 實盤）：6505 決策價來自選股日收盤 123.0，但 provider 送單前會
    重新 `get_current_price()` 取得 123.50 當限價 ⇒ 券商成交 123.50、帳本卻記 123.0
    （成本少記 338 元，`scripts/reconcile_broker_books.py` 每天報「CSV 價 ≠ 券商價」）。
    對稱於 `reconcile_order_qty`（股數）——一個記股數、一個記價格。
    """
    if isinstance(order_ret, dict):
        try:
            p = float(order_ret.get("sent_price"))
            if p > 0:
                return p
        except (TypeError, ValueError):
            pass
    try:
        return float(fallback)
    except (TypeError, ValueError):
        return 0.0


UNKNOWN_ORDERS_FILE = "logs/order_unknown.json"


def load_unknown_orders(path=None):
    """讀「下單結果未明（逾時）」清單：`{代號: {"qty": int, "date": "YYYY-MM-DD", "action": "BUY"}}`。

    為什麼需要（2026-10-19）：`data/esun_provider.place_order` 逾時 30 秒就回 `{"error": ...}`，
    但**下單執行緒仍在跑**、稍後可能真的成交（當天 8046 就印了「下單成功」）。
    若成交而帳本沒記：帳上 0 股、券商有 64 股 ⇒ 隔天「未持股的輪替標的每天重試補足」再買一次
    ⇒ **2 倍部位**。故逾時要落地一筆未明，下次要買該檔前先向券商校正。
    """
    import json as _json
    import os as _os
    p = path if path is not None else UNKNOWN_ORDERS_FILE
    try:
        with open(p, encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _save_unknown_orders(data, path=None):
    import json as _json
    import os as _os
    p = path if path is not None else UNKNOWN_ORDERS_FILE
    try:
        d = _os.path.dirname(p)
        if d:
            _os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        _os.replace(tmp, p)
    except Exception:
        pass


def record_unknown_order(symbol, qty, date_str, action="BUY", path=None):
    """落地一筆「下單結果未明」。"""
    data = load_unknown_orders(path)
    try:
        q = int(qty)
    except (TypeError, ValueError):
        q = 0
    data[str(symbol)] = {"qty": q, "date": str(date_str), "action": str(action)}
    _save_unknown_orders(data, path)


def clear_unknown_order(symbol, path=None):
    """已向券商校正（或確認沒成交）⇒ 清掉未明紀錄。"""
    data = load_unknown_orders(path)
    if str(symbol) in data:
        data.pop(str(symbol), None)
        _save_unknown_orders(data, path)


def unknown_order_blocks_buy(symbol, recs, today_str):
    """該檔現在可不可以下買單。

    - 沒有未明紀錄 → 可以
    - 紀錄是**今天**的 → 不行（當日那筆已放棄追蹤，再買必重複；隔天再校正是安全的，
      因為整股 ROD 委託 13:30 收盤就失效，隔天查庫存一定是最終結果）
    - 紀錄是更早的 → 不擋（呼叫端要先向券商校正，校正不到才沿用『擋』的保守行為）
    """
    rec = (recs or {}).get(str(symbol))
    if not rec:
        return False
    return str(rec.get("date", "")) == str(today_str)


def broker_holding_qty(broker, symbol):
    """券商庫存股數（唯讀）；查不到回 `None`。

    股數一律取 `qty_b`：零股列的 `stk_dats[].qty` 是「以 1 股為單位」的表示，不可當總數
    （見 `scripts/reconcile_broker_books.py` 的單位陷阱說明）。
    """
    q = getattr(broker, "query_inventories", None)
    if q is None:
        return None
    try:
        rows = q()
    except Exception:
        return None
    if not isinstance(rows, (list, tuple)):
        return None

    def _num(v):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("stk_no") or "").strip() != str(symbol).strip():
            continue
        qty = int(_num(row.get("qty_b")))
        if qty <= 0:
            qty = int(_num(row.get("cost_qty")))
        return qty
    return 0


def resolve_fill(broker, symbol, action, order_ret, requested):
    """解析實際成交股數（下單後確認，避免「委託成功≠成交」誤判持股）。

    - order_ret 為含 error 的 dict → 0（委託失敗）
    - order_ret 為 mock 的 filled → requested（模擬全成交）
    - 其餘 → 呼叫 broker.check_fill() 查詢；無法查詢（None）→ 維持原行為視為全成交
    回傳: 實際成交股數（int）或 None（無法得知）。
    """
    if isinstance(order_ret, dict):
        if order_ret.get("error"):
            return 0
        if order_ret.get("status") == "filled":
            return requested
    check = getattr(broker, "check_fill", None)
    if check is not None:
        try:
            filled = check(symbol, action, order_ret, requested)
            if filled is not None:
                return int(filled)
        except Exception:
            pass
    return None




def skip_if_overlap_held(symbol, holdings, notify_fn=None, label="策略"):
    """跨策略重疊防護（2026-08-25 規定）：策略選出的股票若已持有 → 通知+跳過。

    不同策略可能撞股。規定：已持有（holdings 股數 > 0）就不再重複建倉，
    直接跳掉並通知。回傳 True = 應跳過此標的；False = 可買入。
    """
    held = int((holdings or {}).get(symbol, 0) or 0)
    if held <= 0:
        return False
    if notify_fn is not None:
        try:
            notify_fn(
                f"⚠️ *{label}* 選出 {symbol} 但已持有 {held} 股 → "
                f"跳過（不重複建倉）")
        except Exception:
            pass
    print(f"⏭️  {label} 跳過 {symbol}：已持有 {held} 股（跨策略防重疊）")
    return True




def sell_with_fill_check(broker, symbol, shares, notified, today_str, notify_fn, action_label):
    """賣出 + 成交確認。回傳 (實際賣出股數, 更新後 notified)。
    未成交 → 警示且回傳 0；部分成交 → 回傳實際數；無法確認 → 視為全成交。"""
    order_ret = broker.place_order(symbol, "sell", shares)
    filled = resolve_fill(broker, symbol, "sell", order_ret, shares)
    if filled is not None and filled <= 0:
        notified = notify_order_failure(symbol, "委託未成交（排隊中）", notified, today_str,
                                        notify_fn, action=action_label)
        return 0, notified
    if filled is not None and filled < shares:
        print(f"⚠️ {symbol} {action_label}部分成交 {filled}/{shares} 股，餘額續留")
        return filled, notified
    return shares, notified



def calc_topup_need(held, target, buy_offset, market_open):
    """方案 B 補足判定（v3.27）：僅補「已有持股但不足」。

    空倉（held<=0）→ 不補，等策略訊號（2026-09-02 修正：方案 B 是補足不是建倉，
    2454 空倉被直接建倉為 bug）；有持股且 < 目標×(1-offset) → 補差額。
    """
    if held <= 0 or target <= 0:
        return 0
    if not market_open:
        return 0
    if held >= target * (1 - buy_offset):
        return 0
    return target - held




def intraday_trade_window(is_trading_day, hour, minute):
    """孤兒清倉的可下單時段：**交易日 09:00–13:30**。

    為什麼需要（2026-10-08 加）：
      · 孤兒清倉原本只檢查「交易日」⇒ 開機後第一圈（約 08:0x）就會送出委託，
        但**盤中零股 09:00 才開始**（清倉幾乎都是零股：3 位數股數）⇒ 券商退單；
        而清倉用 `_cleaned_orphans` 標記「當日已處理」⇒ **當天不會再試** ⇒ 靜默失敗。
      · 09:00 起同時涵蓋整股（09:00–13:30）與盤中零股，13:30 為台股收盤。
    """
    if not is_trading_day:
        return False
    try:
        return (9, 0) <= (int(hour), int(minute)) <= (13, 30)
    except (TypeError, ValueError):
        return False




def full_position_topup(held, target_shares, buy_offset=0.02):
    """「滿倉不買」判定 → 回傳要補的股數（**0 ＝ 已足額，不該下單**）。

    `held >= target_shares × (1 - buy_offset)` 即視為足額（`buy_offset` ＝ `BUY_AMOUNT_OFFSET`，
    預設 2% ⇒ 允許 2% 的整股進位誤差，避免「價跌一檔 → 目標 +1 股 → 下 1 股單」）。

    為什麼抽成函式（2026-10-06）：實盤原本有兩支買入量分支 ——
    `bollinger/vwap/ma_cross` 有滿倉判定，**`breakout` 沒有**（每個買訊都再算「一整個部位」的股數）。
    而 `breakout` 的訊號是**狀態型**（突破期間每天重發；實測 2884 在 2026-09 連發 8 個交易日），
    ⇒ 持有中再遇買訊、且帳戶有可用資金時，會**重複加碼超過 `alloc` 上限**。
    回測（`scripts/backtest_plan2_monthly_3group.py`：`elif sh == 0 and sig == 1`）對**所有**策略
    都是「空倉才買、買完桶子歸零」⇒ 實盤 breakout 是唯一的例外（live/backtest 口徑落差）。

    回傳：要補的股數（0 ＝ 不動）。
    """
    try:
        held = int(held)
        target_shares = int(target_shares)
        buy_offset = float(buy_offset)
    except (TypeError, ValueError):
        return 0
    if target_shares <= 0:
        return 0
    if held >= target_shares * (1.0 - buy_offset):
        return 0
    return max(0, target_shares - held)








def add_stock_allocation(stock_alloc, symbol, cost, shares):
    """分帳本累加（v3.29）：買入後記錄 total_buy_cost / total_buy_shares。

    方案 B 補買原本只 log_trade 未更新分帳本 → avg_cost 失真（賣出時
    「預估損益 +0」）、check_stock_cap 資金上限失效 → 可能超買。
    主迴圈 BUY 與方案 B 補足共用此函式。

    **2026-09-17 起含買進手續費**：`cost` 傳成交價金，函式內部自己加手續費
    （`core/fees.buy_fee`）⇒ 一處改動即讓所有呼叫端的分帳本都是淨成本，
    `可買股 = TOTAL_CAPITAL − Σtotal_buy_cost` 也才是真的可動用資金。
    """
    if stock_alloc is None:
        return
    from core import fees as _fees
    cost = float(cost or 0) + _fees.buy_fee(cost)
    entry = stock_alloc.setdefault(symbol, {'total_buy_cost': 0.0, 'total_buy_shares': 0})
    entry['total_buy_cost'] = float(entry.get('total_buy_cost', 0) or 0) + cost
    entry['total_buy_shares'] = int(entry.get('total_buy_shares', 0) or 0) + shares

def sell_stock_allocation(stock_alloc, symbol, shares, sell_proceeds=0.0):
    """賣出後扣減分帳本（與 add_stock_allocation 對稱）。

    以分帳本總成本/總股數算加權均價，按賣出股數比例扣減（max(0,..) 防負）。
    symbol 不在帳本或無持股 → 不動作（回傳 (None, None)）。
    回傳 (profit, avg_cost)。
    修正：輪替清倉/trim 與主迴圈賣出共用此函式，避免賣出後分帳本殘留
      （2026-09-08 清除 3665/2886/2880 殘留，即此因：舊賣出走
      sell_with_fill_check / 內嵌路徑，未統一到本處扣減）。

    **2026-09-17 起扣交易成本**：賣出實得 = `sell_proceeds − 手續費 − 證交稅`
    （`core/fees.sell_cost`），損益為**淨額**。
    """
    if stock_alloc is None:
        return None, None
    entry = stock_alloc.get(symbol)
    if not isinstance(entry, dict):
        return None, None
    total_shares = int(entry.get('total_buy_shares', 0) or 0)
    if total_shares <= 0 or shares <= 0:
        return None, None
    from core import fees as _fees
    total_cost = float(entry.get('total_buy_cost', 0) or 0)
    avg_cost = total_cost / total_shares
    if int(shares) >= total_shares:
        net_proceeds = float(sell_proceeds) - _fees.sell_cost(sell_proceeds)
        profit = net_proceeds - total_cost
        entry['total_buy_cost'] = 0.0
        entry['total_buy_shares'] = 0
        return profit, avg_cost
    cost_basis = avg_cost * shares
    # 部分賣出：費用按賣出比例分攤
    net_proceeds = float(sell_proceeds) - _fees.sell_cost(sell_proceeds)
    profit = net_proceeds - cost_basis
    entry['total_buy_cost'] = max(0.0, total_cost - cost_basis)
    entry['total_buy_shares'] = max(0, total_shares - int(shares))
    return profit, avg_cost

def check_buy_fill_shortfall(symbol, held, target_shares, buy_offset, last_buy_date,
                             today, notify_fn, notified, label="策略"):
    """買入未補足檢查（2026-09-01）：持倉 < 目標×(1-offset) 且最後買入已超 3 交易日 →
    TG 通知（每日一次）。回傳更新後 notified。

    last_buy_date: 該檔最後一次 BUY 的日期（str 'YYYY-MM-DD' 或 None）
    """
    if held <= 0 or target_shares <= 0:
        return notified
    if held >= target_shares * (1 - buy_offset):
        return notified
    if last_buy_date is None:
        return notified
    try:
        lb = datetime.strptime(last_buy_date[:10], "%Y-%m-%d").date()
    except Exception:
        return notified
    days_since = (today - lb).days
    if days_since <= 3:
        return notified
    if notified.get(symbol) == today.isoformat():
        return notified
    notified[symbol] = today.isoformat()
    shortfall_pct = (1 - held / target_shares) * 100
    msg = (f"⚠️ *{label}* {symbol} 買入未補足！\n"
           f"持倉 {held} 股 / 目標 {target_shares} 股（差 {shortfall_pct:.1f}%）\n"
           f"最後買入 {last_buy_date[:10]} 已逾 3 交易日，請確認是否需手動補足。")
    if notify_fn is not None:
        try:
            notify_fn(msg)
        except Exception:
            pass
    print(f"⚠️ 買入未補足 {symbol}: {held}/{target_shares}（{last_buy_date[:10]} 買入已逾 3 交易日）")
    return notified


# ── 收盤／睡前報告「一天一次」閘門（2026-09-15）────────────────────────────
# 症狀（VM 容器日誌實證）：
#   ① 09-14 18:57 重啟（deploy 後）→ 立刻又發一輪「收盤報告＋dashboard＋睡前報告」
#   ② 09-15 00:57 跨午夜 → 再發同一輪
# 根因：`daily_report_sent_date`/`sleep_notified_date` 只活在記憶體，且判斷式是
#       `!= now.date()`；非交易時段分支只要 sleep_seconds >= 3600 就會送。
# 修法：狀態落地（logs/report_state.json）＋ 限定「同日收盤後窗口」。
# ⚠️ 不可因此砍掉「盤後崩潰補發」：2026-09-10 主迴圈卡死 8 小時、收盤/睡前報告全掉，
#    17:16 重啟才補發 —— 同日下午（13:31 之後）仍必須補發。
CLOSE_REPORT_START = time(13, 31)   # 與交易時段分支的 13:31 換股/收盤報告一致
REPORT_STATE_PATH = 'logs/report_state.json'


def close_report_window_open(now: datetime) -> bool:
    """是否已進入「當日收盤後」報告窗口（13:31 之後）。

    跨午夜（00:0x~13:30）不在此窗口內 ⇒ 換日那一輪不會再發前一天的收盤/睡前報告。
    """
    return now.time() >= CLOSE_REPORT_START


# ── 日K策略的「收盤前下單窗口」（2026-09-16）──────────────────────────────
# 為什麼：回測（scripts/backtest_plan2_monthly_3group.py）是「**當日收盤判定、以收盤價成交**」
# （`_SIG = STRAT(df)` ＋ 全部走 `close_at()`）；實盤舊行為是 08:45–13:30 每輪用「日K＋當下報價」
# 合成當日一根 K 就判定、**第一時間下單** ⇒ 等於拿開盤價當收盤價。
# 實例（2026-09-16 2006）：09:00:07 賣在 80.70（≈當日最低區），當日高 82.20、10:51 回到 82.00；
# 且那根死叉貼在邊界（收盤 ≥約 82.3 就不成立）⇒ 實盤做了**回測不會做**的交易，績效不可比。
# 修法：日K策略只在收盤前窗口（預設 13:25 起，交易時段至 13:30）判定與下單。
# ⚠️ `keep_wait` 是分鐘級補足/停利機制，**不套用本窗口**。
# ⚠️ 2026-10-19：原本是寫死的字串，但 `.env.example.txt` 一直寫成可用 `CLOSE_ORDER_FROM` 調整
#    ⇒ 改了沒反應。這裡改成讀 env（預設仍 13:25，行為不變）。
CLOSE_ORDER_FROM = os.getenv('CLOSE_ORDER_FROM', '13:25')


def _parse_hhmm(value, fallback=(13, 25)):
    try:
        hh, mm = str(value).split(':')
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return (hh, mm)
    except Exception:
        pass
    return fallback


def close_order_window_open(now: datetime, start=None) -> bool:
    """日K策略是否已進入「收盤前下單窗口」（預設 13:25 起；交易時段到 13:30）。

    start 可覆寫（'HH:MM'，測試/調參用）；設定值壞掉時回退預設 13:25，**不拋例外**
    （不可因一個設定值讓主迴圈停擺）。
    """
    return (now.hour, now.minute) >= _parse_hhmm(start if start is not None else CLOSE_ORDER_FROM)


_CALENDAR = None


def _get_calendar():
    """延遲建立 TradingCalendar（與選股工具同一份日曆）；失敗回 None。"""
    global _CALENDAR
    if _CALENDAR is None:
        try:
            from core.trading_calendar import TradingCalendar
            _CALENDAR = TradingCalendar()
        except Exception:
            return None
    return _CALENDAR


def is_trading_day(now: datetime, calendar=None) -> bool:
    """是否為台股**交易日**（週末／國定假日 → False）。

    日曆＝`core.trading_calendar.TradingCalendar`（`config/taiwan_holidays.json`，
    與選股工具同一份，不另建一套）。
    calendar 可注入（測試用）。日曆壞掉時保守回「週末以外照發」——
    不可因為日曆檔問題就整天不發持倉報告。
    """
    if now.weekday() >= 5:
        return False
    cal = calendar if calendar is not None else _get_calendar()
    if cal is None:
        return True
    try:
        return bool(cal.is_trading_day(now.date()))
    except Exception:
        return True


def report_due(now: datetime, state: dict, key: str, trading_day: bool = True) -> bool:
    """該報告是否該在這一輪發送：需為交易日、且在收盤後窗口內、且「當日」尚未發過。

    key: 'daily_report'（收盤＋儀表板）或 'sleep'（睡前持倉報告），各自獨立。
    trading_day: 呼叫端傳 `is_trading_day(now)`；週末/假日不發（2026-09-15 收緊）。
    """
    if not trading_day:
        return False
    if not close_report_window_open(now):
        return False
    return state.get(key) != now.strftime('%Y-%m-%d')


def mark_report_sent(state: dict, key: str, now: datetime) -> str:
    """標記已發送（呼叫端負責把 state 寫回 REPORT_STATE_PATH）。回傳寫入的日期字串。"""
    state[key] = now.strftime('%Y-%m-%d')
    return state[key]


def holdings_context_check(log_dir=None, env_path=None, max_idle_days: float = 5.0):
    """判斷「本機的 logs/holdings.json 是否可信」——2026-09-22 使用者要求「由程式把控」。

    為什麼需要：`monthly_rebalance_picker.py` 會用 `logs/holdings.json` 判斷「已持倉一律保留」。
    若在**非實盤機**（例如開發機、或 VM 關機期間的本機）跑，那份檔案是舊的／空的
    ⇒ picker 會把**實際有持倉**的股票列進「汰換」名單；照著改 `.env` 之後，實盤的
    「孤兒清倉」會在下一個交易日開盤把它賣掉（繞過策略賣訊）。2026-09-22 實際發生
    （本機 logs 停在 9/14，實盤已到 9/22，2006／3515 被誤列為汰換）。

    判定（回傳 `(ok, msg, detail)`）：
    1. `logs/holdings.json` 必須存在且可解析。
    2. `.env` 若有非 `keep_wait` 的策略（auto 等）在監控，卻**一檔持倉都沒有** ⇒ 不可信。
    3. `logs/` 的活動時間（holdings／performance／report_state／daily_trades 的最大 mtime）
       距今超過 `max_idle_days` 天 ⇒ 不可信（正常情況每天都會有報告或交易寫檔；週末＋國定假日
       連假最多 4 天，故預設 5 天）。
    `log_dir` / `env_path` 可覆寫（測試與 `--holdings-json` 情境用）。
    """
    import json as _json
    from pathlib import Path as _Path
    log_dir = _Path(log_dir) if log_dir else _Path("logs")
    env_path = _Path(env_path) if env_path else _Path(".env")
    detail = {"log_dir": str(log_dir), "idle_days": None, "held_count": None}

    hp = log_dir / "holdings.json"
    data = {}
    if hp.exists():
        try:
            data = _json.loads(hp.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"logs/holdings.json 無法解析（{type(e).__name__}）⇒ 持倉判斷不可信", detail
    else:
        return False, "找不到 logs/holdings.json ⇒ 這台不是實盤機（或還沒跑過），持倉判斷不可信", detail
    from core.live_state import held_quantities
    held = held_quantities(data)
    detail["held_count"] = len(held)

    watch = []
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PC_") and "=" in line:
                    cfg = _json.loads(line.split("=", 1)[1].split("#")[0].strip())
                    if cfg.get("strategy") != "keep_wait":
                        watch.append(line.split("=", 1)[0][3:])
        except Exception:
            watch = []
    detail["watched_nonkeep"] = len(watch)
    if watch and not held:
        return (False,
                f".env 有 {len(watch)} 檔非 keep_wait 監控（如 {', '.join(watch[:5])}）但 logs/holdings.json "
                f"顯示一檔持倉都沒有 ⇒ 這份 holdings 不是實盤最新狀態，持倉判斷不可信", detail)

    newest = None
    for name in ("holdings.json", "performance.csv", "report_state.json", "daily_trades.json"):
        p = log_dir / name
        if p.exists():
            m = p.stat().st_mtime
            newest = m if newest is None else max(newest, m)
    if newest is not None:
        idle_days = (datetime.now().timestamp() - newest) / 86400.0
        detail["idle_days"] = round(idle_days, 1)
        if idle_days > max_idle_days:
            return (False,
                    f"logs/ 最後活動在 {idle_days:.1f} 天前（>{max_idle_days:g} 天）⇒ 這台不是實盤機，"
                    f"holdings 可能過期，持倉判斷不可信", detail)
    return True, "ok", detail


def should_emit_idle_notice(state: dict, key: str) -> bool:
    """非交易時段的「休眠中」訊息去重：同一把 key 只回 True 一次（key 改變才再 True）。

    2026-09-22（使用者反映）：VM 日誌被每輪重複的
    `💤 非交易時段，下次開盤 09/22 09:00，休眠中...` 洗版 ——
    `docker logs --tail 50` 幾乎全是同一行，真正的啟動 banner／報告／選股／錯誤都被擠掉。
    呼叫端把「下次開盤時間」當 key 傳入 ⇒ 同一段非交易時段只印一次，
    跨日（或開盤時間變動）與行程重啟（state 重新開始）才會再印一次。

    state 用呼叫端自己的 dict（不落地），語意與 `report_due` 相同。
    """
    if state.get('idle_notice') == key:
        return False
    state['idle_notice'] = key
    return True


def run_with_heartbeat(cmd, timeout, heartbeat=None, interval=5.0, env=None, cwd=None):
    """執行子程序，並在**等待期間持續更新心跳**；逾時殺掉子程序並拋 `TimeoutExpired`（附已收到的輸出）。

    為什麼要有這支（2026-10-01 實盤事故）：
      長時間子程序（例：選股）若用 `subprocess.run(..., timeout=900)` 同步等待，而主迴圈 watchdog 的門檻是
      `STALL_EXIT_SEC=600` ⇒ **只要選股跑超過 10 分鐘，watchdog 一定先把整個行程砍掉**
      （而且砍在「寫 `.env`」之前）⇒ 該季換股直接消失。選股自己的 900 秒 timeout 形同虛設。
      這裡改成 `Popen` + 輪詢：等待期間照樣推進心跳（watchdog 只該抓「真的卡住」），
      timeout 由本函式自己掌握；逾時會 `kill()` 子程序並把已收到的 stdout/stderr 放進例外
      —— 舊版用 `capture_output=True`，逾時時輸出全被吃掉，事後查不出卡在哪。

    `heartbeat` 是呼叫端持有的 dict（例如主迴圈的 `_HEARTBEAT = {'ts': ...}`），本函式只更新 `['ts']`。
    """
    import subprocess as _sp
    import time as _t

    if env is None:
        env = os.environ.copy()
    proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, env=env, cwd=cwd)
    deadline = _t.time() + float(timeout)
    while True:
        if heartbeat is not None:
            heartbeat['ts'] = _t.time()
        remain = deadline - _t.time()
        if remain <= 0:
            _kill_and_collect(proc, cmd, timeout)
        try:
            out, err = proc.communicate(timeout=min(float(interval), remain))
        except _sp.TimeoutExpired:
            continue
        return _sp.CompletedProcess(cmd, proc.returncode, out, err)


def _kill_and_collect(proc, cmd, timeout):
    """殺掉逾時的子程序並把已收到的輸出附在例外上（診斷用）。"""
    import subprocess as _sp
    proc.kill()
    try:
        out, err = proc.communicate(timeout=5)
    except Exception:
        out, err = '', ''
    raise _sp.TimeoutExpired(cmd, timeout, output=out, stderr=err)


