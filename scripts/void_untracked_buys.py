#!/usr/bin/env python3
"""作廢「未入帳買進」列 —— 一次性對齊 `performance.csv` 與 `holdings.json`（A 案）。

## 背景（2026-09-17）

`performance.csv` 裡有 6 筆買進**只寫進了 CSV**，沒進 `holdings.json`／分帳本／月預算：
- 2395：2026-07-29 12 股 @551、07-30 12 股 @541、07-30 12 股 @542（合計 36 股、19,608 元）
- 3665：2026-07-29 12 股 @2215、07-30 12 股 @1955、07-30 12 股 @1950（合計 36 股、73,440 元）

後果（兩個症狀）：
1. CSV 的 FIFO 未平倉比 holdings 多 36+36 股 ⇒ 儀表板「未平倉部位」看不到它們、
   且這種部位**永遠不會被自動賣出**（賣出與孤兒清倉只認 `holdings.json`）；
2. 總資產三個口徑對不上（`B − A ≡ Σ未平倉成本基礎(CSV) − Σ分帳本成本基礎`）。

## 演算法

對每個「CSV 未平倉股數 > holdings 股數」的標的：
`excess = csv_open − holdings`，由**最舊的買進列**開始作廢，直到累計股數 ≥ `excess`。
（最舊者優先 → 本案例正好選中那 6 筆 12 股列；dry-run 會逐列印出讓人工覆核。）

## 安全設計

- **預設 dry-run**，只報告不寫檔。
- `--apply`：先備份 `<檔>.bak_void_<時間戳>`，作廢列另存 `logs/voided_trades.jsonl`（保留稽核軌跡），
  再原子替換；替換前 **CAS** 確認檔案未被 append（否則中止）。
- 套用後**自我驗證**：重跑 `core.books.audit_books()`，幽靈部位必須歸零，否則回報失敗。
- ⚠️ 只用標準庫（可離線在 VM 上用系統 python3 執行）；驗證用的 `books` 為選用 import。

⚠️ **只改帳、不改變事實**：若券商端其實真的持有這些股（模擬環境查不到），
   本工具不會讓它們消失 —— 真錢上線前仍必須用券商庫存對帳（見 `cairn/environment-scope.md`）。

用法：
    python3 scripts/void_untracked_buys.py                    # dry-run
    python3 scripts/void_untracked_buys.py --apply            # 實際作廢（先備份）
離開碼：0 = 成功或無事可做；1 = 失敗／需要人工處理。
"""
import argparse
import csv
import io
import json
import os
import sys
import tempfile
from datetime import datetime

DEFAULT_PERF = "logs/performance.csv"
DEFAULT_HOLDINGS = "logs/holdings.json"
DEFAULT_VOID_LOG = "logs/voided_trades.jsonl"


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f)]
    return [r for r in rows if r and any(c.strip() for c in r)]


def load_holdings(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in (data or {}).items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[str(k)] = n
    return out


def fifo_open_shares(rows):
    """由 CSV 列推算各標的未平倉股數（FIFO）。rows 不含表頭。"""
    lots, out = {}, {}
    for r in rows:
        if len(r) < 6:
            continue
        sym, act = str(r[1]), str(r[5]).strip().upper()
        try:
            qty = int(r[4])
        except (TypeError, ValueError):
            continue
        if act == "BUY":
            lots.setdefault(sym, []).append(qty)
        elif act == "SELL":
            left = qty
            while left > 0 and lots.get(sym):
                take = min(lots[sym][0], left)
                lots[sym][0] -= take
                left -= take
                if lots[sym][0] == 0:
                    lots[sym].pop(0)
    for sym, ls in lots.items():
        tot = sum(ls)
        if tot > 0:
            out[sym] = tot
    return out


def select_voids(rows, holdings):
    """挑出要作廢的列（index 相對於 rows，0-based，不含表頭）。

    回傳 ([(idx, row)], {sym: excess}, {sym: 預計作廢股數})。
    """
    open_shares = fifo_open_shares(rows)
    excess = {s: n - holdings.get(s, 0) for s, n in open_shares.items()
              if n > holdings.get(s, 0)}
    picks, picked_shares = [], {}
    for sym, need in sorted(excess.items()):
        got = 0
        for i, r in enumerate(rows):
            if got >= need:
                break
            if len(r) < 6 or str(r[1]) != sym or str(r[5]).strip().upper() != "BUY":
                continue
            try:
                qty = int(r[4])
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            picks.append((i, r))
            got += qty
        picked_shares[sym] = got
    picks.sort(key=lambda t: t[0])
    return picks, excess, picked_shares


def money(row):
    try:
        return float(row[3]) * int(row[4])
    except (TypeError, ValueError, IndexError):
        return 0.0


def render(rows):
    out = []
    for r in rows:
        cells = []
        for c in r:
            c = "" if c is None else str(c)
            if any(ch in c for ch in ',"\n\r'):
                c = '"' + c.replace('"', '""') + '"'
            cells.append(c)
        out.append(",".join(cells))
    return "\n".join(out) + "\n"


def atomic_replace(path, text):
    d = os.path.dirname(os.path.abspath(path))
    try:
        mode = os.stat(path).st_mode & 0o777      # mkstemp 是 0600 → 必須保留原權限
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_void_", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser(description="作廢「只寫進 CSV、沒進 holdings」的買進列")
    ap.add_argument("--perf", default=DEFAULT_PERF)
    ap.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    ap.add_argument("--void-log", default=DEFAULT_VOID_LOG)
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設只 dry-run）")
    args = ap.parse_args()

    if not os.path.exists(args.perf):
        print(f"❌ 找不到 {args.perf}")
        return 1
    if not os.path.exists(args.holdings):
        print(f"❌ 找不到 {args.holdings}（沒有持股基準無法判斷哪些是幽靈部位）")
        return 1

    size_before = os.path.getsize(args.perf)
    rows = read_rows(args.perf)
    if not rows:
        print("❌ performance.csv 是空的")
        return 1
    header, body = rows[0], rows[1:]
    holdings = load_holdings(args.holdings)
    picks, excess, picked = select_voids(body, holdings)

    if not picks:
        print("✅ 沒有「CSV 有、holdings 沒有」的買進列，無事可做")
        return 0

    print(f"檔案：{args.perf}（{size_before:,} bytes，{len(body)} 筆交易）")
    print(f"holdings.json：{ {k: v for k, v in sorted(holdings.items())} }")
    print()
    print("將作廢以下買進列（**最舊優先**，逐列請人工覆核）：")
    total = 0.0
    for i, r in picks:
        amt = money(r)
        total += amt
        print(f"  第 {i + 2} 列  {r[0][:19]}  {r[1]:6} 買 {r[4]:>5} 股 @ {r[3]:>9}  = NT${amt:>10,.0f}")
    print(f"  合計 {sum(int(r[4]) for _, r in picks):,} 股 / NT${total:,.0f}")
    print()
    print("各標的：CSV 未平倉多於 holdings 的股數 → 預計作廢")
    for sym, need in sorted(excess.items()):
        print(f"  {sym}: 多 {need:,} 股 → 作廢 {picked.get(sym, 0):,} 股")
    over = {s: picked[s] - excess[s] for s in excess if picked.get(s, 0) > excess[s]}
    if over:
        print(f"  ⚠️ 作廢股數超過多出的股數（列不可分割）：{over} → 請人工確認")

    kept = [r for i, r in enumerate(body) if i not in {i2 for i2, _ in picks}]
    open_after = fifo_open_shares(kept)
    remaining = {s: n - holdings.get(s, 0) for s, n in open_after.items() if n > holdings.get(s, 0)}
    print()
    print(f"作廢後 CSV 未平倉 vs holdings 的殘餘差異：{remaining or '無 ✅'}")

    if not args.apply:
        print("\n🔎 dry-run：未寫入。確認無誤後加 `--apply`（會先備份並寫 logs/voided_trades.jsonl）。")
        return 0 if not remaining else 1

    if os.path.getsize(args.perf) != size_before:
        print("\n❌ 中止：檔案在讀取後被修改（可能有新成交寫入）→ 請重跑一次")
        return 1

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{args.perf}.bak_void_{ts}"
    with open(args.perf, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())

    d = os.path.dirname(args.void_log)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.void_log, "a", encoding="utf-8") as f:
        for i, r in picks:
            f.write(json.dumps({
                "voided_at": datetime.now().isoformat(timespec="seconds"),
                "reason": "只寫進 performance.csv、未進 holdings.json/分帳本（幽靈部位）",
                "source_file": os.path.basename(args.perf),
                "original_row": i + 2,
                "symbol": r[1], "action": r[5], "price": r[3], "quantity": r[4],
                "amount": money(r), "raw": r,
            }, ensure_ascii=False) + "\n")

    atomic_replace(args.perf, render([header] + kept))
    print(f"\n✅ 已作廢 {len(picks)} 列；備份：{backup}")
    print(f"   稽核軌跡：{args.void_log}")

    # 自我驗證：重跑三本帳稽核，幽靈部位必須歸零
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core import books
        r = books.audit_books(args.perf, holdings_path=args.holdings,
                              alloc=books.load_ledger())
        if r["phantom"]:
            print(f"❌ 驗證失敗：仍有幽靈部位 {r['phantom']}")
            return 1
        print(f"✅ 驗證通過：幽靈部位已歸零（holdings 與 CSV 一致）")
        print(f"   （作廢金額 NT${total:,.0f} 回到現金；`B − A` 缺口應同步消失）")
    except Exception as e:
        print(f"⚠️ 無法自動驗證（{e}）—— 請手動跑 scripts/reconcile_total_assets.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
