"""core/park_asset.py — 實盤「閒置資金停泊」（2026-10-31 新增；**預設開啟、停泊 0050**）

## 使用者裁定

1. （2026-10-31 第一版）選項＝「不用停泊」或「使用者指定某個股停泊（慣例 0050）」。
2. （2026-10-31 第二版，**現行**）**預設改為開啟、停泊 0050**：
   - 未設定 `SELFSELECT_PARK_ASSET` ⇒ **停泊 `0050`**（預設行為）
   - `SELFSELECT_PARK_ASSET=`（明確留空）⇒ **不停泊**
   - `SELFSELECT_PARK_ASSET=00878` ⇒ 停泊該檔
3. **只在「本月名單已建倉完成」之後**才把剩下的閒置資金停泊上去，不影響當月建倉。

## 為什麼要有它

回測 `IDLE_CASH_ASSET=0050` 會把每天閒置的錢（平均約 35–40% 的資金）押在 0050，這是主表報酬的一大半
（預設 `revenue`、2016-04~2026-10：停泊 +1445.2% vs 純現金 +656.9%，差 788pp）。實盤原本沒有這一步，
空手期就是現金（領 0%）⇒ 實盤與回測口徑對不上。本模組把「停泊」做成**可選、可控**的實盤行為。

## 設計邊界（刻意保守）

- **只在 immediate 模式**（`SELFSELECT_EXEC_MODE=immediate`）且名單每一檔都「已持有」或「今天已嘗試買進」時才停泊；
  `signal` 模式（等訊號）資金要留給尚未出現的訊號，因此**不停泊**。
- 停泊部位記在 **獨立帳本** `logs/park_position.json`，**不進** `holdings.json`／分帳本
  ⇒ 不會被「總數上限 N=5」「已持倉一律保留」「孤兒清倉」當成自選股。
- 要買股票時**先全部賣掉停泊部位**再買（單一動作、可稽核），不會邊買邊賣。
- 金額太小（< `MIN_PARK_NTD`）不做，避免手續費吃掉收益；以**整股**買進（0050 一張 ≈ 10 萬）。

## 純函式（`test/test_park_asset.py` 釘住）

`park_symbol()`／`idle_amount()`／`park_shares()`／`release_shares()`／`can_park_after_build()`／
`is_build_attempted()`（2026-11-02 新增：今天嘗試買過但沒成交也算建倉已處理）／`enabled()`／
`market_filter_on()`＋`sold_on()`（2026-11-23 新增：停泊「A+B」兩道閘門，見下）

## 停泊三道閘門（2026-11-23 使用者裁定「A+B」＋追加「C」）

背景（11/20 實況）：breakout 把 2603 認賠出場（−14.9%）後，**下一圈停泊就把回款掃進 0050**，
當下大盤正在崩跌 ⇒ 等於「賣在低點、立刻全押另一檔也在跌的 ETF」，而且停泊帳本身已經 −7.2%。

- **A `market_filter_on()`**：停泊前先看大盤年線（沿用 `core.market_filter` 的加權指數 MA200）。
  跌破年線 ⇒ **不買 0050、留現金**；`PARK_MARKET_FILTER=false` 可關（預設開）。
- **B `sold_on()`**：當天只要有一筆**自選股賣出成交**（策略賣訊／硬停損／孤兒清倉；停泊釋出不算），
  當天就**不再停泊**——回款先留現金，到下一個交易日的下單窗口才重新評估（且仍要過 A）。
- **C（追加）**：大盤跌破年線且手上還有停泊部位時，`selfselect_trader.park_idle_if_due()` 直接
  `park_release_all()` 全數賣出變現、留現金（與 A 共用 `PARK_MARKET_FILTER`；排在「名單已建倉完成」之前）。
  回測對應旋鈕：`PARK_MA200=1`（`scripts/backtest_plan2_monthly_3group.py`；預設 0＝舊行為不變）。
"""
from __future__ import annotations

import datetime
import json
import math
import os
from pathlib import Path

# 2026-11-09（v1.1.39）：停泊訊息會直接進 Telegram legacy Markdown，
# 動態內容（失敗原因、券商字串）在**這裡**轉義；`*粗體*` 留在外面由呼叫端原樣送出。
from utils.telegram import escape_md

STATE_PATH = "logs/park_position.json"
MIN_PARK_NTD = 10_000.0      # 低於這個金額不停泊（手續費不划算）
DEFAULT_SYMBOL = "0050"      # 使用者指定要停泊、但沒寫標的時的預設


def park_symbol(env=None) -> str:
    """要停泊的標的。

    - **鍵不存在** ⇒ `DEFAULT_SYMBOL`（`0050`）＝**預設開啟**
    - 鍵存在但值為空（`SELFSELECT_PARK_ASSET=`）⇒ `""`＝**使用者明確關閉停泊**
    - 有值 ⇒ 該代號（ETF／個股皆可）
    """
    src = os.environ if env is None else env
    if "SELFSELECT_PARK_ASSET" not in src:
        return DEFAULT_SYMBOL
    return (src.get("SELFSELECT_PARK_ASSET") or "").strip()


def enabled(env=None) -> bool:
    """是否有停泊（預設 True；`SELFSELECT_PARK_ASSET=` 留空才關閉）。"""
    return bool(park_symbol(env))


def idle_amount(leg_capital: float, stock_value: float, park_value: float = 0.0) -> float:
    """可停泊金額 = 腿額度 − 自選股持股市值 − 目前已停泊市值（不足為 0）。"""
    try:
        return max(0.0, float(leg_capital) - float(stock_value) - float(park_value))
    except (TypeError, ValueError):
        return 0.0


def cash_available(total_capital: float, open_cost: float = 0.0,
                   already_parked_cost: float = 0.0,
                   unverified_proceeds: float = 0.0) -> float:
    """可用現金（保守估計）＝ 本金 − 目前持股成本 − 已停泊成本。

    為什麼需要（2026-11-05）：停泊原本用 `idle_amount()`＝「腿額度 − 持股市值 − 停泊市值」，
    那是**額度**概念；股票跌了額度會變大，但**現金不會變多**。
    實例：腿額度 100 萬、持股市值 69.4 萬 ⇒ idle 30.6 萬，而實際現金只有十幾萬
    ⇒ 照 idle 停泊會下單超過現金，真錢就是交割違約風險。

    ⚠️ **刻意保守**：買進的錢記在 `logs/stock_allocation.json`（`core.books.ledger_cost()`），
    賣出的回款**不加回**（因為模擬帳查不到現金餘額：`get_balance()` 回 0，見
    `cairn/live-order-safety.md`）。寧可少停泊，不要下單超過現金。
    真錢上線前應改成向券商查可用餘額（`get_balance()` 在正式環境應有值）。

    參數壞掉一律回 0（不讓停泊擋住交易，也不會亂買）。
    """
    try:
        tc = float(total_capital)
        oc = float(open_cost or 0.0)
        pc = float(already_parked_cost or 0.0)
        up = float(unverified_proceeds or 0.0)
    except (TypeError, ValueError):
        return 0.0
    # 2026-11-25（v1.1.52）：`unverified_proceeds` ＝「成交未確認的停泊賣出金額」，
    #   保守起見**不計入可用現金**（真錢上若賣單只部分成交，這筆錢根本還沒進來）。
    return max(0.0, tc - oc - pc - up)


def park_shares(idle: float, price: float, min_ntd: float = MIN_PARK_NTD) -> int:
    """可買幾股（整股、向下取整）；金額或價格不合理時回 0。"""
    try:
        idle, price, min_ntd = float(idle), float(price), float(min_ntd)
    except (TypeError, ValueError):
        return 0
    if price <= 0 or idle < max(min_ntd, price):
        return 0
    return int(idle // price)


def release_shares(need_cash: float, price: float, held_shares: int) -> int:
    """為了湊足 `need_cash` 要賣幾股（向上取整、不超過持有張數）。"""
    try:
        need_cash, price = float(need_cash), float(price)
        held = int(held_shares)
    except (TypeError, ValueError):
        return 0
    if price <= 0 or held <= 0 or need_cash <= 0:
        return 0
    need = int(math.ceil(need_cash / price))
    return max(0, min(held, need))


def is_build_attempted(symbol: str, holdings: dict, filled: dict,
                       attempted: dict, today: str) -> bool:
    """這一檔是否「本月建倉已處理」：已持有、已買過、**或今天嘗試買過但沒成交**。

    `attempted`（`logs/entry_attempts.json`，`{代號: 'YYYY-MM-DD'}`）是 2026-11-02 新增的：
    選到但買不到（買入過熱閘門擋下、下單失敗）時，那筆錢既沒買到股票、也不會去停泊 0050
    ⇒ 資金就一直閒置。把「今天試過」也算完成，停泊才能接手；真的買到時會先賣掉停泊部位。
    只認**當天**的紀錄：昨天的嘗試不算，隔天照樣會再試一次。
    """
    if (holdings.get(symbol, 0) or 0) > 0:
        return True
    if symbol in (filled or {}):
        return True
    return bool(today) and str((attempted or {}).get(symbol) or "") == str(today)


def can_park_after_build(exec_mode: str, watch_symbols, holdings: dict,
                         filled: dict, park_sym: str,
                         attempted: dict | None = None, today: str | None = None) -> bool:
    """名單是否「已建倉完成」：每一檔（排除停泊標的）都已持有、已買過或今天已嘗試買進。

    `exec_mode` 必須是 `immediate`（`signal` 模式要把資金留給還沒出現的訊號）。
    `attempted`／`today` 見 `is_build_attempted()`；省略時行為與舊版完全相同。
    """
    if (exec_mode or "").strip().lower() != "immediate":
        return False
    syms = [s for s in (watch_symbols or []) if s and s != park_sym]
    if not syms:
        return False
    day = str(today or "")
    return all(is_build_attempted(s, holdings, filled, attempted or {}, day) for s in syms)


def market_filter_on(env=None) -> bool:
    """停泊的 A 閘門：是否先看大盤年線（`PARK_MARKET_FILTER`，**預設開啟**）。

    使用者裁定（2026-11-23）：「大盤也不好，寧可空手留現金」。實作上由呼叫端拿
    `core.market_filter.MarketTrendFilter.is_above_ma200()` 判斷（與自選股買進同一口徑）；
    本函式只決定「要不要問」——`PARK_MARKET_FILTER=0/false/no/off` 才關閉。

    ⚠️ 刻意與 `MARKET_TREND_FILTER`（自選股買進）分開：兩者可以獨立關，
    但預設都開；停泊擋住時**只影響停泊、不影響買股與賣股**。
    """
    src = os.environ if env is None else env
    raw = src.get("PARK_MARKET_FILTER")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def sold_on(rows, date_str: str, park_symbol: str = "") -> bool:
    """停泊的 B 閘門：`date_str` 當天有沒有**自選股賣出成交**。

    `rows` 是 `performance.csv` 的列（`core.books.read_trades()`；欄位 `timestamp`／`symbol`／`action`）。
    只認 `action == 'SELL'` 且 `timestamp` 前 10 碼等於當天；`park_symbol`（停泊標的）本身不算——
    停泊交易本來就不寫 `performance.csv`，這裡再排除一次是防呆。

    為什麼要這條（2026-11-23 使用者裁定）：11/20 把 2603 認賠賣掉後，同一圈的停泊立刻把回款
    買成 0050（約 16.9 萬）⇒ 「賣出後不要馬上停泊，留現金，到下一個買股窗口再判斷」。
    壞資料一律當「沒有賣出」（不讓一個壞列把停泊永久卡住）。
    """
    day = str(date_str or "")[:10]
    if not day:
        return False
    park = str(park_symbol or "")
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            stamp = str(r.get("timestamp") or "")[:10]
        except Exception:
            continue
        if stamp != day:
            continue
        if str(r.get("action") or "").strip().upper() != "SELL":
            continue
        if park and str(r.get("symbol") or "") == park:
            continue
        return True
    return False


def reconcile_pending(pending, tx_rows, inv_rows, today: str,
                      max_days: int = 5, snapshot=None) -> dict:
    """把「成交未確認」的停泊動作，用隔天落地的券商快照校正（2026-11-23，v1.1.46）。

    ## 為什麼要有（2026-11-23 事故）

    `resolve_fill()` 在 13:25 送單時查不到成交會回 `None`，而停泊一路走「查不到 ⇒ 依送單股數記帳」。
    2026-11-20 的服務器實際只成交 1,000 股（`qty_bm=1000`）、帳本記 2,000；11/23 C 的釋出送 4,000 股
    實際 0 成交、帳本照記 4,000 ⇒ 停泊帳從 4,000 一路偏到 **0**，而券商實際還有約 6,000 股。
    ⇒ 送單當下記帳無可厚非（否則會重複送單），但**隔天一定要用券商成交紀錄收斂**。

    ## 判斷順序

    1. 先看快照 `transactions`（成交回報）：買＝`buy_sell=='B'`、賣＝`'S'`，符號符合 ⇒ 加總 `qty`。
    2. `transactions` 沒有該檔 ⇒ 退回 `inventories` 的**成交量欄位**（`qty_bm`／`qty_sm`）。
    3. 兩者都沒有 ⇒ `status='keep'`（把 pending 留著，明天再試）；超過 `max_days` 天 ⇒ `status='expire'`。

    ## 回傳

    `{'status': 'ok'|'keep'|'expire', 'matched': int|None, 'shares_delta': int,
      'cost_delta': float, 'note': str}`

    `shares_delta`／`cost_delta` 是**要套回帳本**的修正量（買：`matched − booked`；
    賣：`booked − matched` 加回沒賣掉的股數，成本用當下的 `avg`）。
    """
    pv = pending if isinstance(pending, dict) else {}
    act = str(pv.get("act") or "").upper()
    sym = str(pv.get("symbol") or "")
    try:
        booked = int(pv.get("shares") or 0)
        price = float(pv.get("price") or 0.0)
        avg = float(pv.get("avg") or 0.0)
    except (TypeError, ValueError):
        return {"status": "expire", "matched": None, "shares_delta": 0, "cost_delta": 0.0,
                "note": "pending_verify 欄位壞掉 ⇒ 放棄（需人工對帳）"}
    if act not in ("BUY", "SELL") or not sym or booked <= 0:
        return {"status": "expire", "matched": None, "shares_delta": 0, "cost_delta": 0.0,
                "note": "pending_verify 不完整 ⇒ 放棄（需人工對帳）"}

    side = "B" if act == "BUY" else "S"
    qty_key = "qty_bm" if act == "BUY" else "qty_sm"

    def _num(v):
        try:
            return int(float(str(v).replace(",", "").strip()))
        except (TypeError, ValueError):
            return 0

    matched = None
    src = ""
    try:
        hits = [r for r in (tx_rows or []) if isinstance(r, dict)
                and str(r.get("stk_no") or "").strip() == sym
                and str(r.get("buy_sell") or "").strip().upper() == side]
        if hits:
            matched = sum(_num(r.get("qty")) for r in hits)
            src = f"transactions ×{len(hits)}"
    except Exception:
        matched = None
    if matched is None:
        try:
            hits = [r for r in (inv_rows or []) if isinstance(r, dict)
                    and str(r.get("stk_no") or "").strip() == sym]
            if hits:
                matched = sum(_num(r.get(qty_key)) for r in hits)
                src = f"inventories.{qty_key}"
        except Exception:
            matched = None

    if matched is None:
        # 2026-11-23（v1.1.47）：**快照檔存在且沒有錯誤** ⇒ 視為「這筆真的沒成交」。
        #   理由：模擬券商沒有成交就不回任何紀錄（11/10–11/19、11/23 快照全空 ⇔ 那幾天確實沒有成交），
        #   一直「等」的結果是帳本停在錯的數字（11/23 的 6,000 股就是這樣憑空消失的）。
        #   只有在「快照檔還沒產生」或「快照本身有錯誤（API 失敗）」時才繼續等。
        _snap_error = False
        _snap_present = isinstance(snapshot, dict)
        if _snap_present:
            try:
                _errs = snapshot.get("errors")
                _snap_error = bool(_errs) or (snapshot.get("ok") is False)
            except Exception:
                _snap_error = False
        if _snap_present and not _snap_error:
            matched = 0
            _note_empty = "（快照檔存在但沒有此檔成交紀錄 ⇒ 視為沒成交）"
            if act == "BUY":
                delta_sh = 0 - booked
                delta_cost = float(delta_sh) * float(price)
            else:
                delta_sh = booked - 0
                delta_cost = float(delta_sh) * float(avg or price)
            return {"status": "ok", "matched": 0,
                    "shares_delta": int(delta_sh), "cost_delta": delta_cost,
                    "note": f"{act} 送 {booked:,} 股、券商 0 股成交{_note_empty}"
                            f" ⇒ 帳本修正 {delta_sh:+,} 股"}
        pv_date = str(pv.get("date") or "")[:10]
        tday = str(today or "")[:10]
        try:
            age = (datetime.date.fromisoformat(tday) - datetime.date.fromisoformat(pv_date)).days
        except Exception:
            age = 0
        if age >= int(max_days):
            return {"status": "expire", "matched": None, "shares_delta": 0, "cost_delta": 0.0,
                    "note": f"券商快照連續 {age} 天沒有這筆成交紀錄 ⇒ 放棄自動收斂（需人工對帳）"}
        return {"status": "keep", "matched": None, "shares_delta": 0, "cost_delta": 0.0,
                "note": ("券商快照本身有錯誤（API 失敗）⇒ 明天再試" if _snap_error
                         else "券商快照還沒產生 ⇒ 明天再試")}

    matched = max(0, int(matched))
    if act == "BUY":
        delta_sh = matched - booked
        delta_cost = float(delta_sh) * float(price)
    else:
        delta_sh = booked - matched          # 沒賣掉的加回帳上
        delta_cost = float(delta_sh) * float(avg or price)
    note = (f"{act} 送 {booked:,} 股、券商成交量 {matched:,} 股（{src}）"
            f" ⇒ 帳本修正 {delta_sh:+,} 股")
    return {"status": "ok", "matched": matched, "shares_delta": int(delta_sh),
            "cost_delta": delta_cost, "note": note}


def unverified_sell_value(state) -> float:
    """停泊「成交未確認」的**賣出金額合計**（`shares × price`）；沒有就 0（2026-11-25，v1.1.52）。

    為什麼：`cash_available()` 的公式是「本金 − 持股成本 − 停泊成本」，賣出時停泊成本被清掉
    ⇒ 賣出回款立刻被算成可用現金。但模擬環境 13:25 查不到成交（`resolve_fill()` 回 `None`），
    2026-11-25 的 SELL 6,000 股**實際只成 1,000** ⇒ 現金被高估約 45 萬；
    若同一天又有股票買訊，真錢上就是**交割款不足（違約）**。
    ⇒ 這筆金額先從可用現金扣掉（隔天 pending 收斂後才會放回）。
    """
    st = state if isinstance(state, dict) else {}
    pvs = st.get("pending_verifies")
    if not isinstance(pvs, list):
        one = st.get("pending_verify")
        pvs = [one] if isinstance(one, dict) else []
    total = 0.0
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        if str(pv.get("act") or "").upper() != "SELL":
            continue
        try:
            total += float(pv.get("shares") or 0) * float(pv.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def released_today(records, date_str: str, symbol: str = "") -> bool:
    """今天有沒有**停泊釋出（SELL）**紀錄（2026-11-25，v1.1.51）。

    為什麼要有：11/25 同一窗口先釋出 6,000 股、5 分鐘後又把 4,000 股買回來（同價 90.30）——
    純粹是白付手續費與證交稅（約 1,800 元），也讓帳本更難對。規則：**當天只要釋出過，
    當天就不再買停泊**（B 閘門的擴充；B 原本只擋「自選股賣出」）。
    `REPAIR` 不算（人工修帳不是交易）。
    """
    d = str(date_str or "")[:10]
    if not d:
        return False
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("action") or "").upper() != "SELL":
            continue
        if symbol and str(rec.get("symbol") or "") not in ("", symbol):
            continue
        if str(rec.get("ts") or rec.get("date") or "")[:10] == d:
            return True
    return False


def load_state(path: str | Path = STATE_PATH) -> dict:
    """讀停泊帳本；不存在或壞掉一律回空狀態（不讓停泊擋住交易）。

    ⚠️ **必須回傳 `last_park_ts`**（2026-11-04 修）：`selfselect_trader.park_idle_if_due()`
    用它做「5 分鐘內不重複下單」的防護；舊版這裡漏掉這個鍵 ⇒ `st.get('last_park_ts')`
    永遠是 `None` ⇒ 防護是死碼 ⇒ 停泊會每 60 秒重複下同一筆單
    （2026-11-04 VM 實例：0050 282 股 @100.60 連 4 筆）。
    """
    try:
        p = Path(path)
        if not p.exists():
            return {"symbol": "", "shares": 0, "cost": 0.0, "last_park_ts": 0.0}
        d = json.loads(p.read_text(encoding="utf-8"))
        try:
            _ts = float(d.get("last_park_ts") or 0.0)
        except (TypeError, ValueError):
            _ts = 0.0
        # 2026-11-23（v1.1.46）：`pending_verify` 必須保留——停泊「成交未確認」時的待對帳紀錄，
        #   丟掉它就等於永遠算不回真實股數（見 `reconcile_pending()` 的說明）。
        # 2026-11-25（v1.1.51）：**改成佇列**（`pending_verifies: [...]`）。舊版只有單一欄位，
        #   11/25 同一窗口先 SELL 6,000、後 BUY 4,000 ⇒ 買進那筆把賣出的待對帳蓋掉 ⇒ 少對 5,000 股。
        _pvs = d.get("pending_verifies")
        if not isinstance(_pvs, list):
            _pvs = []
            _legacy = d.get("pending_verify")
            if isinstance(_legacy, dict):
                _pvs = [_legacy]
        _pvs = [x for x in _pvs if isinstance(x, dict)]
        return {"symbol": str(d.get("symbol") or ""), "shares": int(d.get("shares") or 0),
                "cost": float(d.get("cost") or 0.0),
                "opened": d.get("opened"), "updated": d.get("updated"),
                "last_park_date": d.get("last_park_date"), "last_park_ts": _ts,
                "pending_verify": (_pvs[0] if _pvs else None),   # 相容舊呼叫端
                "pending_verifies": _pvs}
    except Exception:
        return {"symbol": "", "shares": 0, "cost": 0.0, "last_park_ts": 0.0}


def save_state(state: dict, path: str | Path = STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ── 呈現用（報告 / TG）：讓「停泊」看得見（2026-11-05）──────────────────────
def format_position(symbol: str, shares, avg_cost=None, price=None) -> str:
    """停泊部位一行字；沒有部位回 `"無停泊部位"`。"""
    try:
        sh = int(shares or 0)
    except (TypeError, ValueError):
        sh = 0
    if sh <= 0:
        return "無停泊部位"
    seg = f"{symbol} {sh:,} 股"
    try:
        ac = float(avg_cost or 0)
    except (TypeError, ValueError):
        ac = 0.0
    if ac > 0:
        seg += f" @ 均價 {ac:.2f}"
    try:
        px = float(price or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px > 0:
        seg += f"（現價 {px:.2f}，市值 NT${sh * px:,.0f}）"
        # 2026-11-09（v1.1.40）：停泊佔了資產的一大塊卻從來沒有損益數字，
        # 使用者在持倉報告／停泊狀態都得自己按計算機（0050 97.60 → 103.20 的 +11,200 看不到）。
        # 放在外層括號「之後」，避免 `（…（+5.74%））` 這種嵌套。
        if ac > 0:
            _pnl = (px - ac) * sh
            seg += f"　損益 {_pnl:+,.0f}（{(px / ac - 1) * 100:+.2f}%）"
    return seg


def skip_reason(*, shares=0, cash=None, idle=None, min_ntd: float = MIN_PARK_NTD,
                build_done: bool = True, window_open: bool = True,
                cooldown: bool = False) -> str:
    """今天沒有停泊動作的**原因**（依序判斷；全都正常回空字串＝今天本來就不該有動作）。

    為什麼需要：停泊原本「成功才有聲音、沒做與失敗全靜默」——壞了四天沒人發現就是這樣來的。
    """
    try:
        sh = int(shares or 0)
    except (TypeError, ValueError):
        sh = 0
    if cooldown:
        return "5 分鐘冷卻中"
    if not window_open:
        return "不在下單窗口（13:25–13:30）"
    if not build_done:
        return "本月名單尚未建倉完成（等買進）"
    try:
        c = float(cash) if cash is not None else None
    except (TypeError, ValueError):
        c = None
    try:
        i = float(idle) if idle is not None else None
    except (TypeError, ValueError):
        i = None
    if i is not None and i < float(min_ntd):
        return f"閒置額度 NT${i:,.0f} < 最低門檻 NT${float(min_ntd):,.0f}"
    if c is not None and c < float(min_ntd):
        return f"可用現金 NT${c:,.0f} < 最低門檻 NT${float(min_ntd):,.0f}"
    if sh > 0:
        return ""
    return "今天沒有觸發停泊"


def format_plan_vs_actual(plan: dict) -> list[str]:
    """「**應該停泊** vs **實際停泊**」兩行字（+差額）——使用者 2026-11-05 要求。

    `plan` 由 `selfselect_trader.park_idle_if_due()` 落地（`logs/park_plan.json`），欄位：
    `idle`（額度）、`cash`（現金上限）、`cap`（兩者取小＝本次可用金額）、`price`、
    `target_shares`（應該買幾股）、`actual_shares`（實際記帳幾股）、
    `status`（`BUY`／`FAIL`／`SKIP`）、`reason`、`unknown`（成交未確認）。
    """
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    idle, cash, cap = _f(plan.get("idle")), _f(plan.get("cash")), _f(plan.get("cap"))
    px, tgt, act = _f(plan.get("price")), int(_f(plan.get("target_shares"))), int(_f(plan.get("actual_shares")))
    status = str(plan.get("status") or "").upper()
    out = []
    # 應該停泊：同時列出「額度」與「現金上限」，讓使用者看得到是哪一邊卡住
    # 2026-11-09（v1.1.39）：現金上限為 **0** 時也要印（原本 `if cash:` 把它藏起來，
    #   使用者只看到「額度 19,980 ⇒ 目標 0」，得自己猜是哪一邊卡住）。
    seg = f"應該停泊：額度 NT${idle:,.0f}"
    if plan.get("cash") is not None:
        seg += f"｜現金上限 NT${cash:,.0f}"
    seg += f" ⇒ 目標 NT${cap:,.0f}"
    # 2026-11-09（v1.1.39）：目標 0 的原因要說對。舊版一律寫「不足最低門檻 或 取不到報價」，
    #   實際案例（現金 0、報價 97.45）兩者都不成立 ⇒ 說明必須分開判斷。
    if tgt > 0 and px > 0:
        seg += f"（約 {tgt:,} 股 @ {px:.2f}）"
    elif px <= 0:
        seg += "（取不到報價，本輪不判斷）"
    elif cap < float(MIN_PARK_NTD):
        why = "可用現金/額度已用盡" if cap <= 0 else f"低於最低門檻 NT${MIN_PARK_NTD:,.0f}"
        seg += f"（{why}）"
    else:
        seg += f"（@ {px:.2f} 算不出可買張數）"
    out.append(seg)
    # 實際停泊
    tag = "（成交未確認，先依送單股數記帳）" if plan.get("unknown") else ""
    if status == "BUY" and act > 0:
        out.append(f"實際停泊：買進 {act:,} 股" + (f" ≈ NT${act * px:,.0f}" if px > 0 else "") + tag)
    elif status == "FAIL":
        out.append(f"實際停泊：*送單未成交*｜{escape_md(plan.get('reason') or '原因不明')}")
    else:
        out.append(f"實際停泊：*無*｜{escape_md(plan.get('reason') or '今天沒有觸發停泊')}")
    # 差額（只有「應該有、實際沒有」才提，避免噪音）
    if tgt > 0 and act < tgt:
        out.append(f"差額：少停泊 {tgt - act:,} 股"
                   + (f"（約 NT${(tgt - act) * px:,.0f}）" if px > 0 else ""))
    return out


# ── 停泊帳對帳（2026-11-06，v1.1.35）────────────────────────────────────────
# 為什麼要有：2026-11-06 事故「停泊 4,122 股 vs 券商 4,000 股」的 122 股幻影，
#   因為停泊交易寫在 `logs/park_trades.jsonl`（**不在** performance.csv），
#   `scripts/reconcile_broker_books.py` 與 `scripts/broker_shortfall_repair.py` 都看不到它
#   ⇒ 停泊帳是全專案唯一沒有任何自動對帳的記帳路徑。
# 這組函式只做「判定與說法」，**不下單、不改帳**（呼叫端決定要不要發 TG）。
TRADES_PATH = "logs/park_trades.jsonl"


def load_trades(path: str | Path = TRADES_PATH) -> list[dict]:
    """讀停泊稽核檔（append-only JSONL）。壞行跳過，永不拋例外。"""
    out: list[dict] = []
    try:
        p = Path(path)
        if not p.exists():
            return out
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except Exception:
        return out
    return out


def replay_shares(records) -> int:
    """把稽核檔「重播」成股數：BUY 加、SELL 減、**REPAIR 直接覆寫**（絕對值），其他動作忽略。

    為什麼要有這條：帳本（`park_position.json`）與稽核檔（`park_trades.jsonl`）應該互相印證；
    2026-11-06 的幻影就是「帳本記 4,122、券商實際 4,000」而沒有任何東西去比對。
    `REPAIR` 的語意＝「這一行之後，帳上就應該是 shares 這個絕對值」（人工修帳用），
    否則修完帳的帳本會永遠跟歷史重播對不上。
    """
    shares = 0
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        action = str(rec.get("action") or "").upper()
        try:
            qty = int(float(str(rec.get("shares") or 0).replace(",", "")))
        except (TypeError, ValueError):
            qty = 0
        if action == "BUY":
            shares += max(0, qty)
        elif action == "SELL":
            shares -= max(0, qty)
        elif action == "REPAIR":
            shares = max(0, qty)
    return max(0, shares)


def traded_on(records, date_str: str, symbol: str = "") -> bool:
    """該日（`ts` 或 `date` 以 `YYYY-MM-DD` 開頭）有沒有真正的停泊成交（BUY／SELL）。"""
    d = str(date_str or "")[:10]
    if not d:
        return False
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("action") or "").upper() not in ("BUY", "SELL"):
            continue
        if symbol and str(rec.get("symbol") or "") not in ("", str(symbol)):
            continue
        stamp = str(rec.get("ts") or rec.get("date") or "")
        if stamp[:10] == d:
            return True
    return False


def check_position(book_shares, records, broker_shares=None, traded_today: bool = False) -> dict:
    """停泊帳三重比對：**帳本**（`park_position.json`）× **稽核檔重播** × **券商庫存**。

    回傳 `{"status", "note", "book", "replayed", "broker", "diff"}`，`status` 四種：

    | status | 意義 | 呼叫端該做什麼 |
    |---|---|---|
    | `ok` | 三者一致（或券商庫存不足以判斷但不衝突） | 不發通知 |
    | `ledger_mismatch` | 帳本 ≠ 稽核檔重播 ⇒ **我們自己的帳壞了**（人工改過、或寫檔中斷） | 發 TG 告警 |
    | `broker_mismatch` | 帳本 ≠ 券商庫存，**且當日有停泊成交**（此時庫存可信） | 發 TG 告警 |
    | `broker_unverified` | 帳本 ≠ 券商庫存，但當日沒有停泊成交 | 只寫 log（**不告警**，見下） |

    ⚠️ 為什麼「當日沒有成交就不告警」：`get_inventories()` 只回**當日未交割**部位
    （見 `scripts/snapshot_broker.py` 的 API 限制說明），長期持有的停泊部位可能整檔不出現
    ⇒ 那時的「券商 0 股」是 API 限制、不是真的 0；照它告警會天天誤報。
    也就是說：這道檢查抓的是「成交當天就對不上」的 2026-11-06 型缺口。
    """
    book = int(book_shares or 0)
    rep = int(replay_shares(records))
    diff = book - rep
    note = ""
    broker = None if broker_shares is None else int(broker_shares)
    status = "ok"
    if diff != 0:
        status = "ledger_mismatch"
        note = (f"帳本 {book:,} 股 ≠ 稽核檔重播 {rep:,} 股（差 {diff:+,} 股）"
                f"⇒ 帳本被改過或寫檔中斷，請查 logs/park_trades.jsonl 與 park_position.json")
    elif broker is None:
        note = "券商庫存查不到（查詢失敗）⇒ 只做帳本 vs 稽核檔比對"
    elif broker != book:
        if traded_today:
            status = "broker_mismatch"
            note = (f"帳本 {book:,} 股 ≠ 券商庫存 {broker:,} 股（差 {book - broker:+,} 股）"
                    f"；當日有停泊成交 ⇒ 庫存可信，帳本需人工修正（本檢查不會自動改）")
        else:
            status = "broker_unverified"
            note = (f"帳本 {book:,} 股 ≠ 券商庫存 {broker:,} 股，但當日沒有停泊成交"
                    f"（庫存 API 只回當日未交割部位）⇒ 不足以判定，僅記錄")
    return {"status": status, "note": note, "book": book, "replayed": rep,
            "broker": broker, "diff": diff}
