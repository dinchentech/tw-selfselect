#!/usr/bin/env python3
"""把最近的交易日**附加**到 `cache/selector_prices/` —— CLI 薄殼。

核心實作在 `core/price_append.py`（與實盤選股的自動補價**共用同一份**，
2026-09-14 起 `stock_selector_grid.py --recommend` 會自己先補）。
本檔只負責：解析參數、組報告、備份與 dry-run 開關。

用法：
    python3 scripts/append_selector_prices.py                 # dry-run（預設）
    python3 scripts/append_selector_prices.py --apply         # 實際附加（先備份）
    python3 scripts/append_selector_prices.py --symbols 2330,2317 --apply
    python3 scripts/append_selector_prices.py --all           # 目錄內全部標的
    python3 scripts/append_selector_prices.py --truncate-after 2026-08-13 --apply  # 補救

詳見 `core/price_append.py` 的模組說明（為何只附加、接縫縮放、舊格式快取陷阱）。
離開碼：0 = 成功或無事可做；1 = 有標的失敗。
"""
import argparse
import os
import shutil
import sys
from datetime import date, datetime

# ⚠️ 支援「用 stdin 執行」（`docker exec -i ... python - < 本檔`）：
#    那時 __file__ 是 '<stdin>'（**不是未定義**），abspath 會推出 '/' ⇒ 一律用 CWD。
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

from core.price_append import (CACHE_DIR, load_cached, update_symbol,  # noqa: E402
                              latest_trading_day_hint, resolve_pool_symbols)
from core.cache_io import dump_cache  # noqa: E402


def resolve_symbols(args):
    if args.symbols:
        return [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.all:
        return sorted(f[:-4] for f in os.listdir(CACHE_DIR) if f.endswith(".pkl"))
    pool = args.pool
    if not pool:
        try:
            from core.drawdown_guard import load_env_value
            pool = int(load_env_value("STOCK_NO", "100") or 100)
        except Exception:
            pool = 100
    syms = resolve_pool_symbols(pool)
    return syms or sorted(f[:-4] for f in os.listdir(CACHE_DIR) if f.endswith(".pkl"))[:pool]


def main():
    ap = argparse.ArgumentParser(description="把最近交易日附加到 selector_prices 快取")
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設 dry-run）")
    ap.add_argument("--symbols", default="", help="只處理這些代號（逗號分隔）")
    ap.add_argument("--pool", type=int, default=0, help="候選池大小（預設讀 .env 的 STOCK_NO）")
    ap.add_argument("--all", action="store_true", help="處理快取目錄內全部標的")
    ap.add_argument("--overlap-days", type=int, default=30, help="重疊檢查天數（預設 30）")
    ap.add_argument("--vintage-warn", type=float, default=0.01, help="重疊價差超過此比例就提醒")
    ap.add_argument("--no-splice", dest="splice", action="store_false", default=True,
                    help="不做接縫縮放（附加段保持現行還原價基準，接縫可能有假跳空）")
    ap.add_argument("--backup-dir", default="",
                    help="備份目錄（預設 cache/selector_prices_bak_<時間戳>；"
                         "**測試請務必指定 tmp**，否則會動到真實 cache 目錄）")
    ap.add_argument("--truncate-after", default="",
                    help="補救用：先丟掉此日期之後的列（例：2026-08-13）再重跑。舊列不受影響。")
    ap.add_argument("--drop-nan", action="store_true",
                    help="補救用（2026-09-18）：只丟掉快取內「close 為 NaN/≤0」的列"
                         "（yfinance 最新交易日常回傳「只有量、沒有價」的半成品 K 棒），"
                         "不補價。搭配 --apply 才寫入。")
    ap.add_argument("--limit", type=int, default=0, help="只處理前 N 檔（測試用）")
    args = ap.parse_args()

    symbols = resolve_symbols(args)
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"標的數：{len(symbols)}　模式：{'APPLY' if args.apply else 'dry-run'}"
          f"{'（只丟 NaN 列，不補價）' if args.drop_nan else ''}"
          f"　今天 {date.today()}（最近交易日提示 {latest_trading_day_hint()}）\n")

    trunc = None
    if args.truncate_after:
        import pandas as pd
        trunc = pd.Timestamp(args.truncate_after)
        print(f"⚠️ --truncate-after {args.truncate_after}：將丟棄該日之後的既有列（補救模式）\n")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = args.backup_dir or (os.path.join(os.path.dirname(CACHE_DIR),
                                                  f"selector_prices_bak_{ts}")
                                     if args.apply else None)

    if args.drop_nan:
        from core.price_append import drop_nan_in_cache
        ng, ok, bad = [], [], []
        for i, sym in enumerate(symbols, 1):
            status, payload = drop_nan_in_cache(sym, apply=args.apply, backup_dir=backup_dir)
            if status in ("updated", "would_update"):
                ng.append(sym)
                print(f"  [{i}/{len(symbols)}] {sym}: 丟 {payload['dropped']} 列"
                      f"（{payload['last_old']} → {payload['last_new']}）")
            elif status == "failed":
                bad.append((sym, payload))
                print(f"  [{i}/{len(symbols)}] ❌ {sym}: {payload}")
            else:
                ok.append((sym, payload))
        print(f"\n{'已清理' if args.apply else '可清理'} {len(ng)} 檔、無事 {len(ok)} 檔、失敗 {len(bad)} 檔")
        if ng and args.apply:
            print(f"✅ 備份：{backup_dir}")
        if not args.apply:
            print("\n🔎 dry-run：未寫入。確認無誤後加 `--apply`。")
        return 1 if bad else 0

    updated, skipped, failed, vintage = [], [], [], []
    for i, sym in enumerate(symbols, 1):
        path = os.path.join(CACHE_DIR, f"{sym}.pkl")
        if trunc is not None and os.path.exists(path):
            old, meta = load_cached(path)
            if old is not None and (old.index > trunc).any():
                dropped = int((old.index > trunc).sum())
                old = old[old.index <= trunc]
                meta = dict(meta)
                meta.update({"truncated_at": datetime.now().isoformat(timespec="seconds"),
                             "truncated_rows": dropped})
                if args.apply:
                    if backup_dir:
                        os.makedirs(backup_dir, exist_ok=True)
                        shutil.copy2(path, os.path.join(backup_dir, f"{sym}.pkl"))
                    dump_cache(path, old, meta=meta)
                print(f"  {sym}: 丟棄 {dropped} 列（>{args.truncate_after}）")
        status, payload = update_symbol(sym, apply=args.apply, overlap_days=args.overlap_days,
                                        splice=args.splice, backup_dir=backup_dir)
        if status in ("updated", "would_update"):
            st = payload
            if st["vintage_max_diff"] > args.vintage_warn:
                vintage.append((sym, st["vintage_max_diff"], st["vintage_date"]))
            updated.append(sym)
            note = ""
            if st["vintage_max_diff"] > args.vintage_warn:
                note = (f"  ⚠️ 還原價係數差 {st['vintage_max_diff']:.2%} → 已縮放附加段 "
                        f"×{st['splice_ratio']:.4f} 消除接縫" if args.splice
                        else f"  ⚠️ 還原價係數差 {st['vintage_max_diff']:.2%}（未縮放，接縫會有假跳空）")
            print(f"  [{i}/{len(symbols)}] {sym}: {st['last_old']} → {st['last_new']}"
                  f"（+{st['rows_added']} 列）{note}")
        elif status == "skipped":
            skipped.append((sym, payload))
        else:
            failed.append((sym, payload))
            print(f"  [{i}/{len(symbols)}] ❌ {sym}: {payload}")

    print(f"\n{'已更新' if args.apply else '可更新'} {len(updated)} 檔、"
          f"跳過 {len(skipped)} 檔、失敗 {len(failed)} 檔")
    if vintage:
        verb = "已縮放附加段消除接縫假跳空" if args.splice else "**未縮放**（接縫會有假跳空）"
        print(f"⚠️ 還原價係數已變（除息/減資回溯調整）{len(vintage)} 檔 —— {verb}：")
        for sym, d, dt in vintage[:10]:
            print(f"    {sym}: 重疊最大價差 {d:.2%}（{dt}）")

    if not args.apply:
        print("\n🔎 dry-run：未寫入。確認無誤後加 `--apply`。")
        return 1 if failed else 0
    if updated:
        print(f"\n✅ 已更新 {len(updated)} 檔；備份：{backup_dir}")
        print("✅ 寫後驗證通過（舊歷史保留、新日期已附加）")
    else:
        print("\n✅ 無事可做")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
