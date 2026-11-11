"""core/broker_sync.py — 收盤後「券商成交 vs 本機帳本」對帳與**只修正帳本**（2026-11-05）

## 為什麼需要

2026-11-05 實例：2615 送出 **2 張（2,000 股）整股賣單**，券商成交回報只有 **1,000 股**
（`qty_s=2000`／`qty_sm=1000`），但 `resolve_fill()` 在 13:27 查不到成交時走「查不到＝視為全成交」，
帳本因此記成「賣出 2,000 股、2615 = 0 股」。若那 1,000 股其實還在手上，明天同一檔若出現買訊，
程式會再買一整個部位 ⇒ 實際部位超過額度。

既有的校正關卡只覆蓋「下單逾時（unknown）的**買單**」（`broker_holding_qty`），
**賣出部分成交完全沒有防護**。

## 設計原則（刻意不對稱）

| 情況 | 意義 | 處置 |
|---|---|---|
| 帳本說賣 Q、券商只成交 M < Q | **還有 Q−M 股在手上** | **預設直接補回** holdings（避免明天重複買） |
| 帳本說買 Q、券商只成交 M < Q | 帳本高估持股 | **預設只告警**（`BROKER_SYNC_TRIM=1` 才真的減）——減錯會讓程式明天多買 |
| 該代號在券商成交回報裡完全沒有 | 模擬環境 API 只回當日、可能缺漏 | **不動帳**，只告警（「查不到 ≠ 沒發生」） |

賣出方向之所以敢自動修：**補回持股是保守方向**（最壞情況是少買一次）；買入方向的減帳是激進方向
（最壞情況是重複建倉）。真錢上線前應改成以券商庫存 `qty_b` 為主，並人工確認。

## 可用介面

- `matched_by_symbol(broker_transactions)` — 券商成交回報 → `{(代號, 'BUY'/'SELL'): 股數}`
- `book_trades_on(trades, date_str)` — `performance.csv` 的列 → `{(代號, side): 股數}`
- `plan_adjustments(book, matched)` — 純函式，產出 `[{sid, side, book, broker, delta, action, apply}]`
- `apply_adjustments(holdings, adjustments)` — 回傳新 holdings（不寫檔）
- `run_daily(broker, ...)` — 讀檔／查券商／修正／寫稽核（`logs/broker_reconcile.jsonl`）
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

PERF_FILE = "logs/performance.csv"
HOLDINGS_FILE = "logs/holdings.json"
AUDIT_FILE = "logs/broker_reconcile.jsonl"

_SIDE_MAP = {"B": "BUY", "BUY": "BUY", "S": "SELL", "SELL": "SELL"}


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _side(raw) -> str:
    return _SIDE_MAP.get(str(raw or "").strip().upper(), "")


def matched_by_symbol(broker_transactions) -> dict:
    """券商成交回報 → `{(代號, 'BUY'/'SELL'): 已成交股數}`。

    `mat_dats` 明細優先（同一委託可能分多筆撮合）；沒有明細時退回外層 `qty`。
    """
    out: dict = {}
    for row in (broker_transactions or []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("stk_no") or "").strip()
        side = _side(row.get("buy_sell"))
        if not sid or not side:
            continue
        mats = row.get("mat_dats") or []
        qty = 0.0
        if isinstance(mats, list) and mats:
            for m in mats:
                if isinstance(m, dict):
                    qty += _num(m.get("qty"))
            if qty <= 0:
                qty = _num(row.get("qty"))
        else:
            qty = _num(row.get("qty"))
        if qty > 0:
            out[(sid, side)] = out.get((sid, side), 0.0) + qty
    return out


def matched_detail(broker_transactions) -> dict:
    """券商成交回報 → `{(代號, side): {"qty", "fee", "tax", "price"}}`（手續費／證交稅取 `mat_dats`）。

    用途（2026-11-05）：修帳時只知道「成交幾股」不夠——`performance.csv` 的 `cost` 欄是費用，
    要跟券商實際收的一致，算出來的已實現損益才對。
    """
    out: dict = {}
    for row in (broker_transactions or []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("stk_no") or "").strip()
        side = _side(row.get("buy_sell"))
        if not sid or not side:
            continue
        rec = out.setdefault((sid, side), {"qty": 0, "fee": 0.0, "tax": 0.0, "price": 0.0})
        mats = row.get("mat_dats") or []
        qty = sum(_num(d.get("qty")) for d in mats if isinstance(d, dict)) if mats else _num(row.get("qty"))
        rec["qty"] += int(qty)
        for d in mats:
            if isinstance(d, dict):
                rec["fee"] += abs(_num(d.get("fee")))
                rec["tax"] += abs(_num(d.get("tax")))
        px = _num(row.get("price_avg"))
        if px > 0:
            rec["price"] = px
    return out


def partial_fill_plan(trades, broker_transactions, date_str: str, allow_trim: bool = False) -> dict:
    """帳本 vs 券商成交 → 部分成交的修帳計畫（純函式；給歷史補帳用）。

    為什麼不能直接用 `run_daily()`：模擬環境查不到歷史成交，歷史只能靠**當天落地的快照**補。
    回傳 `{"plan": [...], "detail": {...}, "blocked": [...]}`：
    `plan` 每筆含 `sid`／`side`／`book`（帳本股數）／`broker`（券商成交股數）／
    `book_cost`／`broker_cost`（券商費用）／`action`／`apply`；
    `blocked` 是「買進少成交」這種需要人類決定的項目（`allow_trim=False` 時不自動減帳）。
    """
    book = book_trades_on(trades, date_str)
    detail = matched_detail(broker_transactions)
    matched = {k: v["qty"] for k, v in detail.items()}
    base = plan_adjustments(book, matched, apply_trim=allow_trim)
    plan, blocked = [], []
    for item in base:
        if item["action"] == "unknown":
            continue
        item = dict(item)
        d = detail.get((item["sid"], item["side"]), {})
        item["broker_cost"] = round(float(d.get("fee", 0.0)) + float(d.get("tax", 0.0)), 2)
        item["broker_price"] = d.get("price")
        if item["action"] == "trim_holding" and not allow_trim:
            item["apply"] = False
            blocked.append(item)
        plan.append(item)
    return {"plan": plan, "detail": detail, "blocked": blocked}


def rewrite_csv_text(text: str, date_str: str, sid: str, side: str, qty: int,
                     cost=None) -> tuple:
    """把 `performance.csv` 文字裡「某日某代號某方向」的**成交股數**改成券商實際成交股數。

    為什麼直接動 CSV 文字：`performance.csv` 是三本帳的成交權威（append-only），
    `DictReader` 寫回會把欄寬／多餘欄位洗掉（歷史上有 6 欄與 8 欄混用）。
    這裡只改 `quantity` 欄（單列時連 `cost` 一起校正成券商實收費用），其餘原樣保留。

    回傳 `(新文字, 被改動的資料列索引[0-based，不含表頭], 說明字串)`。
    """
    import csv as _csv
    import io as _io

    lines = [ln for ln in text.splitlines()]
    reader = list(_csv.reader(lines))
    if not reader:
        return text, [], "CSV 是空的"
    head = reader[0]
    idx = {}
    for name in ("timestamp", "symbol", "action", "quantity", "cost"):
        try:
            idx[name] = head.index(name)
        except ValueError:
            idx[name] = None
    if any(idx[k] is None for k in ("timestamp", "symbol", "action", "quantity")):
        # 舊格式（表頭缺欄）⇒ 用專案文件化的位置：timestamp,symbol,signal,price,quantity,action,…
        idx.setdefault("timestamp", 0)
        idx = {"timestamp": 0, "symbol": 1, "action": 5, "quantity": 4,
               "cost": 7 if len(head) > 7 else None}

    def _cell(row, key):
        i = idx.get(key)
        return row[i] if (i is not None and i < len(row)) else ""

    rows = reader[1:]
    hits = [i for i, r in enumerate(rows)
            if _cell(r, "timestamp").startswith(date_str)
            and _cell(r, "symbol").strip() == str(sid)
            and _side(_cell(r, "action")) == _side(side)]
    if not hits:
        return text, [], f"{sid} {side} 在 {date_str} 沒有帳本成交列"
    total = sum(int(_num(_cell(rows[i], "quantity"))) for i in hits)
    target, remaining, changed, drop = int(qty), int(qty), [], []
    # 依時間順序保留「最早成交」，多出來的部分從最後幾列砍掉（砍到 0 的整列刪除）——
    # 等同「券商先吃掉前面的單、後面的單被取消」，也避免留下 quantity=0 的假成交列。
    for i in hits:
        cur = int(_num(_cell(rows[i], "quantity")))
        keep = max(0, min(cur, remaining))
        remaining -= keep
        if keep != cur:
            if keep == 0:
                drop.append(i)
            else:
                rows[i][idx["quantity"]] = str(keep)
                changed.append(i)
    if cost is not None and len(hits) == 1 and idx.get("cost") is not None:
        i = hits[0]
        if idx["cost"] < len(rows[i]):
            rows[i][idx["cost"]] = str(round(float(cost), 2))
    out = _io.StringIO()
    w = _csv.writer(out, lineterminator="\n")
    w.writerow(head)
    for i, r in enumerate(rows):
        if i in drop:
            continue
        w.writerow(r)
    note = (f"{sid} {side}：帳本 {total} 股 → 券商 {target} 股"
            + ("" if total != target else "（無需調整）")
            + (f"（帳本少於券商 {target - total} 股，本工具只減不增，請人工確認）" if target > total else ""))
    return out.getvalue(), changed, note


def book_trades_on(trades, date_str: str) -> dict:
    """本機帳本的當日成交 → `{(代號, side): 股數}`（只收 `date_str` 那天）。"""
    out: dict = {}
    for r in (trades or []):
        if not isinstance(r, dict):
            continue
        ts = str(r.get("timestamp") or r.get("ts") or "")
        if not date_str or not ts.startswith(date_str):
            continue
        sid = str(r.get("symbol") or "").strip()
        side = _side(r.get("action"))
        qty = _num(r.get("quantity"))
        if sid and side and qty > 0:
            out[(sid, side)] = out.get((sid, side), 0.0) + qty
    return out


def plan_adjustments(book: dict, matched: dict, apply_trim=None) -> list:
    """比對帳本與券商成交，產出調整計畫（純函式）。

    `apply_trim`：買入方向（帳本高估持股）是否真的減帳；`None` ⇒ 讀
    `BROKER_SYNC_TRIM`（預設 0 ＝ 只告警）。
    """
    if apply_trim is None:
        apply_trim = os.getenv("BROKER_SYNC_TRIM", "0").strip().lower() in ("1", "true", "yes", "on")
    plan = []
    for (sid, side), q_book in sorted(book.items()):
        if (sid, side) not in matched:
            plan.append({"sid": sid, "side": side, "book": q_book, "broker": None,
                         "delta": 0.0, "action": "unknown", "apply": False,
                         "note": "券商成交回報沒有這筆（模擬環境只回當日／可能缺漏）"})
            continue
        q_broker = matched[(sid, side)]
        delta = q_broker - q_book          # <0 ＝ 少成交
        if abs(delta) < 1e-9:
            continue
        if side == "SELL":
            # 少賣 ⇒ 股票還在手上 ⇒ holdings 要補回
            plan.append({"sid": sid, "side": side, "book": q_book, "broker": q_broker,
                         "delta": delta, "action": "add_holding", "apply": True,
                         "note": f"賣出少成交 {-delta:.0f} 股 ⇒ 補回持股"})
        else:
            plan.append({"sid": sid, "side": side, "book": q_book, "broker": q_broker,
                         "delta": delta, "action": "trim_holding", "apply": bool(apply_trim),
                         "note": (f"買進少成交 {-delta:.0f} 股 ⇒ 帳本高估持股"
                                  + ("" if apply_trim else "（預設只告警，BROKER_SYNC_TRIM=1 才減）"))})
    return plan


def apply_adjustments(holdings: dict, plan: list) -> dict:
    """把 `apply=True` 的計畫套到 holdings（回傳新 dict，不改原物件）。"""
    out = {str(k): int(_num(v)) for k, v in (holdings or {}).items()}
    for p in (plan or []):
        if not p.get("apply"):
            continue
        sid = p["sid"]
        cur = out.get(sid, 0)
        if p["action"] == "add_holding":
            out[sid] = max(0, int(cur - p["delta"]))       # delta 為負 ⇒ 加回
        elif p["action"] == "trim_holding":
            out[sid] = max(0, int(cur + p["delta"]))       # delta 為負 ⇒ 減掉
    return out


def _audit(rec: dict, path: str | Path = AUDIT_FILE) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def run_daily(broker, date_str: str | None = None, perf_path: str | Path = PERF_FILE,
              holdings_path: str | Path = HOLDINGS_FILE, audit_path: str | Path = AUDIT_FILE,
              apply_trim=None) -> dict:
    """收盤後對帳：`performance.csv`（帳）× 券商當日成交回報（券商）→ 修正 holdings。

    **只修正帳本、不下單**。回傳報告 dict（`ok`／`plan`／`changed`／`errors`／`summary`）。
    """
    from core.books import read_trades

    day = date_str or datetime.now().strftime("%Y-%m-%d")
    report = {"date": day, "ok": False, "plan": [], "changed": {}, "errors": {}, "summary": ""}
    try:
        tx = None
        q = getattr(broker, "query_transactions", None)
        if q is not None:
            tx = q(day, day)
        else:
            sdk = getattr(broker, "_trade_sdk", None)
            if sdk is not None:
                tx = sdk.get_transactions_by_date(day, day)
    except Exception as e:
        report["errors"]["broker"] = f"{type(e).__name__}: {e}"
    if tx is None:
        report["errors"].setdefault("broker", "查不到成交回報")
        report["summary"] = "查不到券商成交回報 ⇒ 不改帳"
        _audit(report, audit_path)
        return report

    trades = read_trades(str(perf_path))
    book = book_trades_on(trades, day)
    matched = matched_by_symbol(tx)
    plan = plan_adjustments(book, matched, apply_trim=apply_trim)
    report["plan"] = plan
    if not book:
        report["ok"] = True
        report["summary"] = "今日帳本沒有成交紀錄 ⇒ 無需對帳"
        _audit(report, audit_path)
        return report

    holdings = {}
    try:
        hp = Path(holdings_path)
        if hp.exists():
            holdings = json.loads(hp.read_text(encoding="utf-8"))
    except Exception as e:
        report["errors"]["holdings"] = str(e)
    before = {str(k): int(_num(v)) for k, v in holdings.items()}
    after = apply_adjustments(before, plan)
    changed = {k: (before.get(k, 0), after.get(k, 0)) for k in set(before) | set(after)
               if before.get(k, 0) != after.get(k, 0)}
    report["changed"] = changed
    if changed:
        try:
            Path(holdings_path).write_text(
                json.dumps({k: v for k, v in after.items() if v > 0}, ensure_ascii=False, indent=4),
                encoding="utf-8")
            report["ok"] = True
        except Exception as e:
            report["errors"]["write"] = str(e)
    else:
        report["ok"] = not report["errors"]
    unknown = [p for p in plan if p["action"] == "unknown"]
    alerts = [p for p in plan if p["action"] != "unknown"]
    report["summary"] = (f"成交比對 {len(book)} 筆｜調整 {len(alerts)} 筆｜"
                         f"缺漏 {len(unknown)} 筆｜實際改帳 {len(changed)} 檔")
    _audit(report, audit_path)
    return report
