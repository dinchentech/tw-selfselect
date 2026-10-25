#!/usr/bin/env python
"""總資產三口徑對帳 + 三本帳一致性檢查。

背景：2026-09-13 查出 VM 上三個總資產口徑長期不一致，差額 92,484 元
（2395/3665 各 36 股只寫進 performance.csv、沒進 holdings/分帳本）。
詳見 `cairn/total-assets-reconciliation.md`。

    A 現金流（`core.drawdown_guard.compute_equity`，**MDB 股災防護用**）
        = TOTAL_CAPITAL + (ΣSELL − ΣBUY) + Σ(holdings.json 股數 × 現價)
    B 儀表板（`scripts/generate_dashboard.py`）
        = TOTAL_CAPITAL + FIFO已實現 + (持股市值 − 分帳本成本)
    C CSV 自洽（假設所有登錄成交皆為真）
        = 現金 + Σ(CSV FIFO 未平倉股數 × 現價)

⚠️ **A 與 B 代數恆等**：`B − A ≡ Σ未平倉成本基礎(CSV) − Σ分帳本成本基礎`
   （因為 `FIFO已實現 = 淨現金流 + Σ未平倉成本基礎`）。
   ⇒ 帳務一致時 A ≡ B；兩者不同**只代表三本帳不同步**，不是公式錯。
   本腳本真正的用處是抓出「不同步」—— 部位比對由 `core/books.py` 提供（單一實作）。

用法：
    .venv/bin/python scripts/reconcile_total_assets.py
    .venv/bin/python scripts/reconcile_total_assets.py --prices 2395=674 --json
    .venv/bin/python scripts/reconcile_total_assets.py --perf /tmp/performance.csv

離開碼：0 = 三本帳一致；1 = 不一致或缺檔（含無現價，刻意 fail-loud）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import books  # noqa: E402
from core.drawdown_guard import load_env_value  # noqa: E402

DEFAULT_TC = 1_200_000.0
# 容許誤差：手續費/稅金不在 CSV 內，實務上會有百元級落差
TOLERANCE_ABS = 1_000.0
TOLERANCE_PCT = 0.002


def money_flow(trades):
    """回傳 (ΣBUY, ΣSELL, 淨現金流, 費用合計)。

    淨現金流 = Σ賣 − Σ買 − Σ費用（手續費＋賣出證交稅，2026-09-17 起計入；
    舊列沒有 `cost` 欄者以現行費率推定）。不扣費用會讓總資產虛高。
    """
    from core import fees
    buy = sum(float(r["price"]) * int(r["quantity"])
              for r in trades if str(r["action"]).upper() == "BUY")
    sell = sum(float(r["price"]) * int(r["quantity"])
               for r in trades if str(r["action"]).upper() == "SELL")
    cost = fees.total_for_rows(trades)
    return buy, sell, sell - buy - cost, cost


def main():
    ap = argparse.ArgumentParser(description="總資產對帳 + 三本帳一致性")
    ap.add_argument("--perf", default=books.PERF_FILE)
    ap.add_argument("--holdings", default=books.HOLDINGS_FILE)
    ap.add_argument("--alloc", default=books.ALLOC_FILE,
                    help=f"分帳本（實盤為 logs/stock_allocation.json，單數）")
    ap.add_argument("--total-capital", type=float, default=None)
    ap.add_argument("--prices", default="", help="覆寫現價，如 2395=674,3665=1875（離線可重跑）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tc = args.total_capital
    if tc is None:
        try:
            tc = float(load_env_value("TOTAL_CAPITAL", str(DEFAULT_TC)))
        except (TypeError, ValueError):
            tc = DEFAULT_TC

    trades = books.read_trades(args.perf)
    buy, sell, net_cash_flow, tx_costs = money_flow(trades)
    cash = tc + net_cash_flow

    holdings = books.load_holdings(args.holdings)
    alloc = books.load_ledger(args.alloc)
    open_lots, realized, _ = books.fifo_open_positions(trades)
    cost_ledger = books.ledger_cost(alloc)

    # 三本帳一致性（單一實作；缺檔也算不一致，不回退成 0）
    audit = books.audit_books(args.perf, holdings=holdings, alloc=alloc)
    if not os.path.exists(args.alloc):
        audit["missing"] = list(audit.get("missing", [])) + [args.alloc]
        audit["ok"] = False
        audit["summary"] = f"缺分帳本 {args.alloc}（不可靜默當 0）；" + audit["summary"]

    prices = {}
    for kv in filter(None, args.prices.split(",")):
        k, _, v = kv.partition("=")
        prices[k.strip()] = float(v)
    need = sorted(set(holdings) | set(open_lots))
    missing_px = [s for s in need if s not in prices]
    if missing_px:
        try:
            from core.inst_data import fetch_latest_closes
            prices.update(fetch_latest_closes(missing_px) or {})
        except Exception as e:  # 網路失敗時仍可比對股數（市值部分留空）
            print(f"!! 現價抓取失敗（{e}）→ 請用 --prices 指定", file=sys.stderr)
    unpriced = [s for s in need if s not in prices]

    def mv(shares_map):
        return sum(sh * prices[s] for s, sh in shares_map.items() if s in prices)

    m_hold = mv(holdings)
    m_csv = mv({s: v[0] for s, v in open_lots.items()})
    A = cash + m_hold
    B = tc + realized + (m_hold - cost_ledger)
    C = cash + m_csv

    tol = max(TOLERANCE_ABS, abs(B) * TOLERANCE_PCT)
    # 無現價 ⇒ 市值算不出來，對帳結果無意義 → 一律視為不一致（fail-loud）
    bad = (not audit["ok"] or abs(B - A) > tol or bool(unpriced))

    payload = {
        "total_capital": tc, "sum_buy": buy, "sum_sell": sell,
        "net_cash_flow": net_cash_flow, "cash": cash, "transaction_costs": tx_costs,
        "market_value_holdings": m_hold, "market_value_csv": m_csv,
        "fifo_realized": realized, "ledger_cost": cost_ledger,
        "A_cash_flow": A, "B_dashboard": B, "C_csv_consistent": C,
        "B_minus_A": B - A, "C_minus_B": C - B,
        "phantom_positions": {
            s: {"shares": n, "cost": open_lots[s][1],
                "price": prices.get(s), "market_value": n * prices.get(s, 0.0)}
            for s, n in audit["phantom"].items()},
        "holdings_not_in_csv": audit["ghost"],
        "unmatched_sells": audit["unmatched"], "memory_drift": audit["memory_drift"],
        "ledger_gap": audit["ledger_gap"], "missing_files": audit["missing"],
        "unpriced": unpriced, "summary": audit["summary"],
        "consistent": not bad, "tolerance": tol,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if bad else 0

    print("=" * 64)
    print(f"TOTAL_CAPITAL={tc:,.0f}  ΣBUY={buy:,.0f}  ΣSELL={sell:,.0f}  "
          f"net_cash_flow={net_cash_flow:,.0f}  cash={cash:,.0f}")
    print(f"交易成本（手續費＋證交稅，已由淨現金流扣除）={tx_costs:,.0f}")
    print(f"FIFO已實現={realized:,.0f}  分帳本成本={cost_ledger:,.0f}  "
          f"M(holdings)={m_hold:,.0f}  M(CSV)={m_csv:,.0f}")
    print("-" * 64)
    print(f"A 現金流口徑（MDB 用）  : {A:>14,.0f}")
    print(f"B 儀表板口徑            : {B:>14,.0f}")
    print(f"C CSV 自洽口徑          : {C:>14,.0f}")
    print(f"    B − A = {B - A:>+13,.0f}   （≡ 分帳本成本基礎缺口 {audit['ledger_gap']:+,.0f}；恆等式，非公式錯）")
    print(f"    C − B = {C - B:>+13,.0f}   （CSV 自洽 − 儀表板；無幽靈部位且帳務一致時應≈0）")
    if audit["phantom"]:
        print("\n🚨 幽靈部位（CSV 有、holdings.json 沒有）—— 這些部位永遠不會被賣出：")
        for s, n in audit["phantom"].items():
            print(f"   {s}: {n} 股" + (f"  市值 {n * prices[s]:,.0f}（@{prices[s]:,.1f}）" if s in prices else "  （無現價）"))
    if audit["ghost"]:
        print("\n🚨 holdings.json 有、CSV 找不到買進的部位：")
        for s, n in audit["ghost"].items():
            print(f"   {s}: {n} 股")
    if audit["unmatched"]:
        print(f"\n🚨 賣出找不到對應買進（CSV 缺口）：{audit['unmatched']}")
    if audit["memory_drift"]:
        print(f"\n🚨 記憶體/磁碟持股漂移（下一筆 save_holdings 會蓋掉對方）：{audit['memory_drift']}")
    if audit["missing"]:
        print(f"\n🚨 缺檔（不可靜默當 0）：{audit['missing']}")
    if unpriced:
        print(f"\n⚠️ 無現價、未計入市值（視為不一致）：{unpriced}")
    print("-" * 64)
    print("✅ 三本帳一致" if not bad else f"❌ 不一致（容許誤差 ±{tol:,.0f}）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
