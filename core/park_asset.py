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
`is_build_attempted()`（2026-11-02 新增：今天嘗試買過但沒成交也算建倉已處理）／`enabled()`
"""
from __future__ import annotations

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
                   already_parked_cost: float = 0.0) -> float:
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
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, tc - oc - pc)


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
        return {"symbol": str(d.get("symbol") or ""), "shares": int(d.get("shares") or 0),
                "cost": float(d.get("cost") or 0.0),
                "opened": d.get("opened"), "updated": d.get("updated"),
                "last_park_date": d.get("last_park_date"), "last_park_ts": _ts}
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
