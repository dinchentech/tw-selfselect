#!/usr/bin/env python3
"""scripts/broker_shortfall_repair.py — 用**當天落地的券商快照**補「部分成交」的帳（2026-11-05）

## 為什麼需要

2026-11-05：2615 送出 2,000 股賣單，券商最後**只成交 1,000 股**（`qty_s=2000`／`qty_sm=1000`），
但帳本記成「賣 2,000、2615 = 0 股」。`core/broker_sync.py` 是為「當天就能發現」設計的，
而模擬環境的查詢 API **不保留歷史**（`get_transactions_by_date` 對過去日期回空）⇒
隔天再跑 `broker_sync` 只會比對到「當天沒成交」，救不了這筆。

唯一還能用的證據是**當天落地的快照**（`scripts/snapshot_broker.py` → `logs/broker_snapshot_<日期>.json`）。
本工具就是拿那份快照，把帳本修成券商事實。

## 修什麼（三本帳）

| 帳 | 動作 |
|---|---|
| `logs/performance.csv` | 該日該代號該方向的 `quantity` 改成**券商實際成交股數**；單列時 `cost` 也校正成券商實收（fee+tax） |
| `logs/holdings.json` | 用修正後的 CSV 重算 FIFO 未平倉股數（只動「這次有落差」的代號） |
| `logs/stock_allocation.json` | 同上，`total_buy_shares`／`total_buy_cost` 對齊 FIFO 未平倉（權威口徑見 `core.books.fifo_open_positions`） |

## 安全設計

- **預設 dry-run**：只印「會怎麼改」，不寫任何檔。
- `--apply` 才寫，且**先備份**（`*.bak_shortfall_<時間戳>`）、用 `core.books.atomic_write_json` 原子寫入、
  並在 `logs/broker_shortfall_repair.jsonl` 留一筆稽核（含快照檔名）。
- **賣出少成交**（還有股票在手上）→ 預設就修（保守方向，避免明天重複建倉）。
- **買進少成交**（帳本高估持股）→ 預設**不修**（減錯會讓程式明天多買），要明示 `--allow-trim`。
- **券商回報裡沒有的代號** → 不動（「查不到 ≠ 沒發生」）。

## 用法

```bash
docker exec tw_selfselect_bot python scripts/broker_shortfall_repair.py \\
    --snapshot logs/broker_snapshot_2026-11-05.json          # 先看 dry-run
docker exec tw_selfselect_bot python scripts/broker_shortfall_repair.py \\
    --snapshot logs/broker_snapshot_2026-11-05.json --apply  # 確認後才寫
```

離開碼：`0` ＝ 不需修或已修；`1` ＝ 參數／檔案問題；`3` ＝ 有「買進少成交」待人工決定（未套用）。
"""
import argparse
import csv
import io
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

_f = globals().get("__file__", "")
_ROOT = (str(Path(_f).resolve().parent.parent) if _f and not str(_f).startswith("<")
         else str(Path.cwd()))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import books  # noqa: E402
from core.broker_sync import partial_fill_plan, rewrite_csv_text  # noqa: E402

PERF_FILE = "logs/performance.csv"
HOLDINGS_FILE = "logs/holdings.json"
ALLOC_FILE = "logs/stock_allocation.json"
AUDIT_FILE = "logs/broker_shortfall_repair.jsonl"


def _read(path):
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _trades_from_text(text):
    return [r for r in csv.DictReader(io.StringIO(text)) if r.get("symbol") and r.get("action")]


def _backup(path, tag):
    p = Path(path)
    if not p.exists():
        return None
    dst = p.with_name(p.name + f".bak_shortfall_{tag}")
    shutil.copy2(p, dst)
    return str(dst)


def _audit(rec, path=AUDIT_FILE):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def print_plan(plan, day):
    print("=" * 68)
    print(f"部分成交補帳（券商快照 @ {day}）")
    print("=" * 68)
    if not plan:
        print("✅ 帳本與券商成交一致 ⇒ 不需要修")
        return
    print(f"{'代號':<6}{'方向':<6}{'帳本':>8}{'券商':>8}{'差額':>8}{'券商費用':>10}  動作")
    for p in plan:
        print(f"{p['sid']:<6}{p['side']:<6}{p['book']:>8.0f}{p['broker']:>8.0f}"
              f"{p['broker'] - p['book']:>8.0f}{p.get('broker_cost', 0):>10.0f}  "
              f"{'會套用' if p.get('apply') else '不套用（需 --allow-trim）'}｜{p.get('note', '')}")


def repair(text, plan, day):
    """把 plan（apply=True）套到 performance.csv 文字；回傳 `(新文字, [(sid, side, 說明)])`。"""
    notes = []
    for p in plan:
        if not p.get("apply"):
            continue
        side = "SELL" if p["side"] == "SELL" else "BUY"
        text, changed, note = rewrite_csv_text(text, day, p["sid"], side,
                                              int(p["broker"]), cost=p.get("broker_cost"))
        notes.append((p["sid"], side, note, len(changed)))
    return text, notes


def books_after(text, holdings, alloc, touched):
    """用修正後的 CSV 重算 FIFO 未平倉，更新「這次有落差」的代號 → `(holdings, alloc)`。"""
    trades = _trades_from_text(text)
    open_pos, _realized, _unmatched = books.fifo_open_positions(trades)
    new_h = {str(k): int(v) for k, v in (holdings or {}).items()}
    new_a = {str(k): dict(v) for k, v in (alloc or {}).items() if isinstance(v, dict)}
    for sid in touched:
        sh, cost = open_pos.get(sid, (0, 0.0))
        new_h[sid] = int(sh)
        cur = new_a.setdefault(sid, {"total_buy_cost": 0, "total_buy_shares": 0})
        cur["total_buy_shares"] = int(sh)
        cur["total_buy_cost"] = float(round(cost, 2))
    return {k: v for k, v in new_h.items() if v > 0}, new_a


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用當天落地的券商快照補「部分成交」的帳（預設 dry-run）")
    ap.add_argument("--snapshot", required=True, help="logs/broker_snapshot_<日期>.json")
    ap.add_argument("--date", default=None, help="交易日（預設取快照裡的 date）")
    ap.add_argument("--apply", action="store_true", help="真的寫檔（先備份；預設只印）")
    ap.add_argument("--allow-trim", action="store_true",
                    help="連「買進少成交」也減帳（預設不減：減錯會讓程式明天多買）")
    ap.add_argument("--perf", default=PERF_FILE)
    ap.add_argument("--holdings", default=HOLDINGS_FILE)
    ap.add_argument("--alloc", default=ALLOC_FILE)
    args = ap.parse_args(argv)

    try:
        snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 讀不到快照 {args.snapshot}：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    day = args.date or snap.get("date")
    tx = snap.get("transactions") or []
    if not day or not tx:
        print(f"❌ 快照沒有 date 或 transactions（date={day}、{len(tx)} 筆）", file=sys.stderr)
        return 1

    text = _read(args.perf)
    if not text.strip():
        print(f"❌ 讀不到 {args.perf}", file=sys.stderr)
        return 1
    trades = _trades_from_text(text)
    res = partial_fill_plan(trades, tx, day, allow_trim=args.allow_trim)
    plan = res["plan"]
    print_plan(plan, day)
    todo = [p for p in plan if p.get("apply")]
    if not todo:
        blocked = res["blocked"]
        return 3 if blocked else 0

    new_text, notes = repair(text, plan, day)
    touched = sorted({n[0] for n in notes})
    holdings = json.loads(_read(args.holdings) or "{}") or {}
    alloc = json.loads(_read(args.alloc) or "{}") or {}
    new_h, new_a = books_after(new_text, holdings, alloc, touched)

    print("\n── 將修改（三本帳）──")
    for sid, side, note, _n in notes:
        print(f"   performance.csv：{note}")
    for sid in touched:
        print(f"   holdings.json：{sid} {holdings.get(sid, 0)} → {new_h.get(sid, 0)} 股")
        print(f"   stock_allocation.json：{sid} "
              f"{alloc.get(sid, {}).get('total_buy_shares', 0)} → {new_a.get(sid, {}).get('total_buy_shares', 0)} 股")

    if not args.apply:
        print("\n（dry-run：沒有寫任何檔。確認無誤後加 --apply）")
        _audit({"ts": datetime.now().isoformat(timespec="seconds"), "date": day,
                "snapshot": args.snapshot, "applied": False,
                "plan": plan, "touched": touched})
        return 0

    tag = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = {name: _backup(path, tag) for name, path in
               (("perf", args.perf), ("holdings", args.holdings), ("alloc", args.alloc))}
    Path(args.perf).write_text(new_text, encoding="utf-8")
    books.atomic_write_json(args.holdings, new_h)
    books.atomic_write_json(args.alloc, new_a)

    # 自我驗證：用修正後的檔案重算，必須沒有可套用的落差
    verify = partial_fill_plan(_trades_from_text(_read(args.perf)), tx, day)
    leftover = [p for p in verify["plan"] if p.get("apply")]
    ok = not leftover
    print("\n" + ("✅ 已修帳並驗證（重算後無落差）" if ok else f"⚠️ 仍有落差：{leftover}"))
    _audit({"ts": datetime.now().isoformat(timespec="seconds"), "date": day,
            "snapshot": args.snapshot, "applied": True, "ok": ok,
            "plan": plan, "touched": touched, "backups": backups})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
