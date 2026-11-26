"""core/stock_pending.py — 自選股「成交未確認」的賣出待對帳（2026-11-25，v1.1.53）

## 為什麼

停泊那條線（`park_asset.pending_verifies`）在 11/25 已經證明有用：13:25 送出的賣單
`resolve_fill()` 查不到成交 ⇒ 帳本照送單股數記「全額賣出」，但券商實際只成一部分
⇒ **可用現金被高估**（真錢上就是交割款不足）。

自選股的策略賣出／硬停損走的是同一條 `resolve_fill()`，同樣會遇到「查不到成交」；
只是它的受害面是 `holdings.json`＋分帳本＋`fit_cash()` 的現金估算。

## 做法（與停泊同一套語意）

1. 賣單送出去、`resolve_fill()` 回 `None` ⇒ 照原樣記帳（否則下一圈會重複下單），
   但把這筆寫進 `logs/stock_pending.json`（佇列）。
2. 之後每個下單窗口先對帳：**當天**用券商即時庫存 `qty_sm`、**隔天**用當日快照的
   `transactions`（`buy_sell=='S'`）⇒ 實際成交小於送單量時，把沒賣掉的股數與成本
   **加回** `holdings` 與分帳本（＝撤回多記的賣出）。
3. 未確認的賣出金額同時從 `fit_cash()` 的可用現金扣掉（保守）。

⚠️ 已知限制：`performance.csv` 的那列仍是送單股數（P&L 會暫時偏高），
隔天的 `core.broker_sync`／`scripts.broker_shortfall_repair` 才是修 CSV 的正式路徑。
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = "logs/stock_pending.json"


def load(path: str | Path = PATH) -> list[dict]:
    try:
        p = Path(path)
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def save(entries, path: str | Path = PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(list(entries or []), ensure_ascii=False, indent=1), encoding="utf-8")


def record(entry: dict, path: str | Path = PATH) -> list[dict]:
    """把一筆待對帳加進佇列並落地；回傳新的佇列。"""
    entries = load(path)
    if isinstance(entry, dict) and entry:
        entries.append(entry)
    save(entries, path)
    return entries


def unverified_sell_value(entries) -> float:
    """未確認的**賣出**金額合計（`shares × price`）——要從可用現金扣掉。"""
    total = 0.0
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        if str(e.get("act") or "").upper() != "SELL":
            continue
        try:
            total += float(e.get("shares") or 0) * float(e.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def apply_deltas(entry: dict, delta_shares: int, delta_cost: float,
                 holdings: dict, alloc: dict) -> None:
    """把對帳修正套回持股與分帳本（就地修改；呼叫端負責存檔）。

    賣出少成交 ⇒ `delta_shares > 0`（把沒賣掉的加回）、`delta_cost > 0`（成本加回）。
    """
    sym = str((entry or {}).get("symbol") or "")
    if not sym:
        return
    try:
        holdings[sym] = max(0, int(holdings.get(sym, 0) or 0) + int(delta_shares))
    except (TypeError, ValueError):
        pass
    led = alloc.get(sym)
    if isinstance(led, dict):
        try:
            led["total_buy_cost"] = max(0.0, float(led.get("total_buy_cost") or 0.0) + float(delta_cost))
            led["total_buy_shares"] = max(0, int(led.get("total_buy_shares") or 0) + int(delta_shares))
        except (TypeError, ValueError):
            pass
