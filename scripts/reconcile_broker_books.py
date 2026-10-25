#!/usr/bin/env python3
"""scripts/reconcile_broker_books.py — **券商庫存 vs 本機帳本** 對帳（唯讀，2026-09-23）

## 為什麼需要

`cairn/environment-scope.md` 早就寫明「真錢上線前必須用券商庫存對帳」，但 repo 內一直沒有工具
（`scripts/void_untracked_buys.py` 的註解也提到這件事）。2026-09-23 的實盤事故就是缺這個：

```
↻ 2884 2000 股餘數 ≥500，進位至 2 張   ✅ 下單成功: 整股 buy 2884 2000 股   📝 記錄: BUY 2884 (1584 股)
↻ 5876 1461 股餘數 <500，捨去為 1 張   ✅ 下單成功: 整股 buy 5876 1000 股   📝 記錄: BUY 5876 (1461 股)
```

券商實際庫存（實測）：

| 股票 | 券商 `qty_b` | 成交價 | 本機 holdings.json | 本機 CSV |
|---|---|---|---|---|
| 2884 玉山金 | **2000** | 45.45 | 1584 ❌ | 1584 ❌ |
| 5876 上海商銀 | **1000** | **49.90** | 1461 ❌ | 1461 @49.25 ❌ |
| 2881 富邦金 | 470 | 153.00 | 470 ✅ | 470 ✅ |

（根因見 `data/esun_provider.py` 的整股進位／`core/live_utils.reconcile_order_qty`，程式面已修）

## 用法（**必須在實盤機的 container 內跑**：需要玉山 SDK 與憑證）

```bash
docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py            # 對帳（唯讀）
docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py --date 2026-09-23
docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py --json
```

離開碼：`0` ＝ 三本帳與券商一致；`1` ＝ 有差異（列出逐檔差異與建議動作）；`2` ＝ 查不到券商資料。

⚠️ **本工具只讀不改**：修帳請用 `--print-fix` 產出的明確指令，人工確認後再執行
（修帳會動到實盤持股，刻意保留人為關卡）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 專案根：動態推導（container 內是 /app；支援 `docker exec -i … python - < 本檔`）
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.isdir(_ROOT):
    os.chdir(_ROOT)

from core.live_state import held_quantities, load_json   # noqa: E402

# ⚠️ .env 一律以「檔案」為準（override=True）。原因（2026-10-01 實測）：
#   容器用 docker-compose `env_file` 在**建立容器時**把變數注入 process env，之後主機上改 `.env`
#   不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 不會覆蓋它們
#   ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。
#   主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`（V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)


def read_holdings_file(path):
    """讀持股檔 → `{代號: 股數}`（`>0` 才算；沿用全專案唯一的 `held_quantities`）。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return held_quantities(load_json(str(p), {}))
    except Exception:
        return {}


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def parse_inventories(raw):
    """券商庫存 → `{代號: {"qty": int, "price": float, "cost": float, "name": str}}`。

    ⚠️ 股數一律取 `qty_b`（見 `EsunProvider.query_inventories` 的單位陷阱說明）；
    零股列的 `stk_dats[].qty` 是「以 1 股為單位」的表示，不可當總數。
    """
    out = {}
    for row in (raw or []):
        if not isinstance(row, dict):
            continue
        sym = str(row.get("stk_no") or "").strip()
        if not sym:
            continue
        qty = int(_num(row.get("qty_b")))
        if qty <= 0:
            # 沒有 qty_b 就退回 cost_qty（整股列兩者相同；零股列 qty_b 才是總數）
            qty = int(_num(row.get("cost_qty")))
        out[sym] = {"qty": qty, "price": _num(row.get("price_avg")),
                    "cost": abs(_num(row.get("cost_sum"))),
                    "name": str(row.get("stk_na") or "")}
    return out


def parse_transactions(raw):
    """成交回報 → `{代號: {"qty": int, "price": float, "fee": float}}`（同日可能多筆，取總和）。"""
    out = {}
    for row in (raw or []):
        if not isinstance(row, dict):
            continue
        sym = str(row.get("stk_no") or "").strip()
        if not sym:
            continue
        qty = int(_num(row.get("qty")))
        price = _num(row.get("price_avg"))
        fee = 0.0
        for d in (row.get("mat_dats") or []):
            if isinstance(d, dict):
                fee += abs(_num(d.get("fee")))
        cur = out.setdefault(sym, {"qty": 0, "price": price, "fee": 0.0})
        cur["qty"] += qty
        cur["fee"] += fee
        if price > 0:
            cur["price"] = price
    return out


def read_csv_rows(path, date_str):
    """讀 performance.csv 當日列 → `[(行號, 欄位 list)]`（保留行號以便人工核對）。"""
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        if line.startswith(date_str):
            rows.append((i + 1, line.split(",")))
    return rows


def build_report(broker_inv, holdings, csv_rows, date_str):
    """組出對帳結果（純函式）→ `{"ok":bool,"rows":[...],"only_local":[...],"notes":[...]}`。"""
    csv_by_sym = {}
    for _ln, cols in csv_rows:
        if len(cols) < 5:
            continue
        sym = cols[1].strip()
        side = cols[5].strip().upper() if len(cols) > 5 else ""
        if side not in ("BUY", "SELL"):
            continue
        qty = int(_num(cols[4]))
        rec = csv_by_sym.setdefault(sym, {"buy": 0, "sell": 0, "price": _num(cols[3])})
        rec["buy" if side == "BUY" else "sell"] += qty
    rows, only_local, notes = [], [], []
    for sym in sorted(set(broker_inv) | set(csv_by_sym)):
        b = broker_inv.get(sym, {})
        h = holdings.get(sym)
        c = csv_by_sym.get(sym)
        row = {"sym": sym, "name": b.get("name", ""), "broker_qty": b.get("qty"),
               "holdings_qty": h, "csv_buy": (c or {}).get("buy"),
               "broker_price": b.get("price"), "csv_price": (c or {}).get("price")}
        diffs = []
        if b.get("qty") is not None and h is not None and int(h) != int(b["qty"]):
            diffs.append(f"holdings {h} ≠ 券商 {b['qty']}")
        if c and b.get("qty") is not None and int(c["buy"]) != int(b["qty"]):
            diffs.append(f"CSV 買進 {c['buy']} ≠ 券商 {b['qty']}")
        if c and b.get("price") and abs(float(c["price"]) - float(b["price"])) > 0.005:
            diffs.append(f"CSV 價 {c['price']} ≠ 券商 {b['price']}")
        row["diffs"] = diffs
        if diffs:
            rows.append(row)
        elif b.get("qty"):
            only_local.append(row)      # 一致（列出供人工目視）
    if not broker_inv:
        notes.append("查不到券商庫存（SDK 未登入／非交易時段／回應格式改變）⇒ 無法對帳")
    else:
        # 實測 2026-09-23：玉山 get_inventories() 只回「當日有成交」的標的（每檔 stk_dats 全是當天），
        # 所以它比較像「今日成交／未交割庫存」而非完整集保庫存 ⇒ 未涵蓋的持股無法比對，必須講明。
        uncovered = sorted(s for s, q in (holdings or {}).items() if q > 0 and s not in broker_inv)
        if uncovered:
            notes.append(f"券商回傳只有 {len(broker_inv)} 檔（疑似僅涵蓋當日成交／未交割）；"
                         f"本機另有 {len(uncovered)} 檔未涵蓋、無法比對：{', '.join(uncovered)}"
                         f"（完整庫存請以券商對帳單為準）")
    return {"ok": bool(broker_inv) and not rows, "date": date_str,
            "rows": rows, "consistent": only_local, "notes": notes}


def print_report(rep, as_json=False):
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    print("=" * 68)
    print(f"券商庫存 vs 本機帳本 對帳（{rep['date']}）")
    print("=" * 68)
    for n in rep["notes"]:
        print(f"⚠️  {n}")
    if rep["rows"]:
        print("\n❌ 有差異（券商才是事實；本機帳本要照它校正）：")
        print(f"{'代號':<6}{'名稱':<8}{'券商庫存':>10}{'holdings':>10}{'CSV買進':>10}{'券商價':>9}{'CSV價':>9}  差異")
        for r in rep["rows"]:
            print(f"{r['sym']:<6}{r['name']:<8}{str(r['broker_qty']):>10}{str(r['holdings_qty']):>10}"
                  f"{str(r['csv_buy']):>10}{str(r['broker_price']):>9}{str(r['csv_price']):>9}  "
                  + "；".join(r["diffs"]))
    if rep["consistent"]:
        print("\n✅ 一致：")
        for r in rep["consistent"]:
            print(f"   {r['sym']} {r['name']:<8} 券商 {r['broker_qty']} 股 @ {r['broker_price']}")
    print("\n" + ("✅ 三本帳與券商一致" if rep["ok"] else "❌ 需要人工校正（本工具只讀不改）"))


def print_fix_hint(rep):
    """產生「明確的修帳指令」給人工確認後執行（不代跑）。"""
    if not rep["rows"]:
        return
    print("\n── 建議的修帳資料（人工確認後才寫入；本工具不代改）──")
    for r in rep["rows"]:
        print(f"   {r['sym']}: holdings.json → {r['broker_qty']} 股；"
              f"performance.csv {rep['date']} 的 BUY 列 → quantity={r['broker_qty']}, "
              f"price={r['broker_price']}")
    print("   ⚠️ 修帳前先備份（backups/），並在 cairn/LOG.md 記一筆。")


def fetch_from_broker(prov, date_str):
    """取得 `(庫存, 成交)`。優先走 provider 的唯讀方法；舊映像沒有這兩個方法時直接呼叫 SDK。

    為什麼要 fallback：本工具常被 `docker exec -i … python - < 本檔` 直接餵進**已在跑的映像**
    （映像內的 provider 可能是加方法之前的版本），fallback 讓它照樣能對帳。
    """
    if hasattr(prov, "query_inventories") and hasattr(prov, "query_transactions"):
        return prov.query_inventories(), prov.query_transactions(date_str, date_str)
    try:
        prov.login()
    except Exception as e:
        print(f"⚠️ 登入失敗（{e}）")
    sdk = getattr(prov, "_trade_sdk", None)
    if sdk is None:
        return None, None
    inv = tx = None
    try:
        inv = sdk.get_inventories()
    except Exception as e:
        print(f"⚠️ 取庫存失敗: {type(e).__name__}: {e}")
    try:
        tx = sdk.get_transactions_by_date(date_str, date_str)
    except Exception as e:
        print(f"⚠️ 取成交回報失敗: {type(e).__name__}: {e}")
    return inv, tx


def main():
    p = argparse.ArgumentParser(description="券商庫存 vs 本機帳本 對帳（唯讀）")
    p.add_argument("--date", default=None, help="對帳日期 YYYY-MM-DD（預設今天）")
    p.add_argument("--json", action="store_true", help="以 JSON 輸出")
    p.add_argument("--print-fix", action="store_true", help="額外印出建議的修帳資料")
    p.add_argument("--holdings", default=os.path.join("logs", "holdings.json"))
    p.add_argument("--perf", default=os.path.join("logs", "performance.csv"))
    p.add_argument("--from-json", default=None,
                   help="改讀已捕捉的券商回傳 JSON（{\"inventories\":[...],\"transactions\":[...]}）"
                        "，用於沒有 SDK 的環境重跑對帳")
    args = p.parse_args()

    from datetime import datetime
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.from_json:
        blob = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        raw_inv, raw_tx = blob.get("inventories"), blob.get("transactions")
    else:
        try:
            from data.esun_provider import EsunProvider
        except Exception as e:
            sys.exit(f"❌ 載入玉山 provider 失敗（本工具必須在實盤機的 container 內跑）：{e}")
        if os.getenv("BROKER", "esun").lower() != "esun":
            print(f"⚠️ BROKER={os.getenv('BROKER')}（本工具為玉山專用）")
        raw_inv, raw_tx = fetch_from_broker(EsunProvider(), date_str)

    inv = parse_inventories(raw_inv)
    tx = parse_transactions(raw_tx)
    holdings = read_holdings_file(args.holdings)
    rep = build_report(inv, holdings, read_csv_rows(args.perf, date_str), date_str)
    if tx:
        for r in rep["rows"] + rep["consistent"]:
            if r["sym"] in tx:
                r["broker_fee"] = tx[r["sym"]].get("fee")
    print_report(rep, as_json=args.json)
    if args.print_fix:
        print_fix_hint(rep)
    if not inv:
        sys.exit(2)
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
