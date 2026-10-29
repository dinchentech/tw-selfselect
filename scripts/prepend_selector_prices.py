#!/usr/bin/env python3
"""scripts/prepend_selector_prices.py — 把「快取第一個交易日之前」的歷史補進 `cache/selector_prices/`

## 為什麼需要

`cache/selector_prices/*.pkl` 幾乎全部從 **2022-01-03** 才開始（當初是「新標的進池 ⇒ 抓近 250 天」），
所以任何 2016-2021 的回測（2018 空頭、2020 COVID）都跑不了：`load_data()` 只會在 2022 之後才有 K 棒。

本檔是 `core/price_append.py`（往後**附加**）的鏡像：只補 `old.index[0]`（不含）**以前**的日子，
**既有列一個位元都不動**（回測可重現性優先）。

## 為什麼要「接縫縮放」

yfinance `auto_adjust=True` 的還原價會因之後的除息/減資**回溯改變** ⇒ 今天抓的 2016 年價格與
快取裡（某個較早版本抓的）2022 年價格不在同一基準。做法與 `price_append` 相同：
用**重疊日**算 `ratio = 舊收盤 ÷ 新收盤`，把**新增（較舊）那段**整體乘上 ratio。
- 新增段自己的日報酬完全不變（整段同乘常數）⇒ 動能/波動計算正確。
- 接縫日不會出現假跳空（實測 2330 的 ratio = 1.002944，逐日變異 ~1e-7 ⇒ 純版本差異）。

## 用法

    .venv/bin/python scripts/prepend_selector_prices.py                    # dry-run（預設）
    .venv/bin/python scripts/prepend_selector_prices.py --apply            # 實際寫入（先整目錄備份）
    .venv/bin/python scripts/prepend_selector_prices.py --start 2016-01-01 --apply
    .venv/bin/python scripts/prepend_selector_prices.py --symbols 2330,2317 --apply
    .venv/bin/python scripts/prepend_selector_prices.py --all --apply      # 目錄內全部標的

離開碼：0 = 全部成功或無事可做；1 = 有標的失敗。
"""
import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta

_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

CACHE_DIR = os.path.join(_ROOT, "cache", "selector_prices")
OVERLAP_PAD_DAYS = 45          # 抓資料時多抓「快取第一天之後」的天數，用來算 ratio
MIN_OVERLAP = 3                # 少於這個重疊天數 ⇒ 無法校正，跳過
MAX_RATIO_STD = 5e-3           # ratio 相對變異超過此值 ⇒ 視為異常（非單純版本差異）
MAX_SEAM_JUMP = 0.35           # 接縫日報酬超過此值 ⇒ 警告（多半是資料錯，不是真行情）


def load_symbol(path):
    from core.cache_io import load_cache_or_raw
    df, meta = load_cache_or_raw(path)
    return df, (meta or {})


def fetch_batch(symbols, start, end):
    """一次抓多檔（yfinance）。回傳 {symbol: DataFrame(open/high/low/close/volume)}。"""
    import pandas as pd
    import yfinance as yf

    tick = [f"{s}.TW" for s in symbols]
    raw = yf.download(tick, start=start, end=end, auto_adjust=True,
                      progress=False, threads=True, group_by="column")
    out = {}
    if raw is None or len(raw) == 0:
        return out
    if not isinstance(raw.columns, pd.MultiIndex):
        # 單檔時 yfinance 回單層欄位
        if len(symbols) == 1:
            df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                     "Close": "close", "Volume": "volume"})
            out[symbols[0]] = _clean(df)
        return out
    for s in symbols:
        col = f"{s}.TW"
        if ("Close", col) not in raw.columns:
            continue
        sub = raw.loc[:, (slice(None), col)].copy()
        sub.columns = [c[0] for c in sub.columns]
        sub = sub.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                  "Close": "close", "Volume": "volume"})
        out[s] = _clean(sub)
    return out


def _clean(df):
    import pandas as pd
    if df is None or len(df) == 0:
        return None
    df = df[[c for c in ("open", "high", "low", "close", "volume") if c in df.columns]]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"
    df = df[~df.index.duplicated(keep="first")].sort_index()
    from core.price_append import drop_unusable_rows
    df = drop_unusable_rows(df)
    return df if df is not None and len(df) else None


def plan_symbol(old, fresh, min_overlap=MIN_OVERLAP):
    """算「要補哪些列」與接縫縮放比。純函式（可單獨測試）。

    回傳 dict：ok / reason / rows(new rows to prepend, already scaled) / ratio / ratio_std
    / overlap / seam_jump / first_old / first_new
    """
    import pandas as pd

    if fresh is None or len(fresh) == 0:
        return {"ok": False, "reason": "yfinance 無資料"}
    first_old = old.index[0]
    older = fresh[fresh.index < first_old]
    if len(older) == 0:
        return {"ok": False, "reason": "沒有更早的資料（IPO 較晚或已是最早）"}
    overlap = old.index.intersection(fresh.index)
    if len(overlap) < min_overlap:
        return {"ok": False, "reason": f"重疊 {len(overlap)} 天 < {min_overlap}，無法校正版本差異"}
    a = old.loc[overlap, "close"].astype(float)
    b = fresh.loc[overlap, "close"].astype(float)
    valid = (a > 0) & (b > 0)
    if valid.sum() < min_overlap:
        return {"ok": False, "reason": "重疊日收盤價不可用"}
    ratio_s = a[valid] / b[valid]
    ratio = float(ratio_s.median())
    ratio_std = float(ratio_s.std() / ratio) if ratio else 0.0
    if ratio_std > MAX_RATIO_STD:
        return {"ok": False, "reason": f"ratio 不穩定（std/mean={ratio_std:.2e}）⇒ 疑似資料錯誤"}
    add = older.copy()
    for c in ("open", "high", "low", "close"):
        if c in add.columns:
            add[c] = add[c] * ratio
    seam_jump = float(add["close"].iloc[-1] / float(old.loc[first_old, "close"]) - 1.0)
    return {"ok": True, "rows": add, "ratio": ratio, "ratio_std": ratio_std,
            "overlap": int(len(overlap)), "seam_jump": seam_jump,
            "first_old": str(first_old)[:10], "first_new": str(add.index[0])[:10]}


def merge_prepend(old, add):
    import pandas as pd
    merged = pd.concat([add, old])
    merged = merged[~merged.index.duplicated(keep="first")].sort_index()
    merged.index.name = "Date"
    return merged


def resolve_symbols(args):
    if args.symbols:
        return [s.strip() for s in args.symbols.split(",") if s.strip()]
    if os.path.isdir(CACHE_DIR):
        return sorted(f[:-4] for f in os.listdir(CACHE_DIR) if f.endswith(".pkl"))
    return []


def main():
    ap = argparse.ArgumentParser(description="把快取第一天之前的歷史補進 selector_prices（預設 dry-run）")
    ap.add_argument("--apply", action="store_true", help="實際寫入（會先整目錄備份）")
    ap.add_argument("--start", default="2016-01-01", help="要補到多早（預設 2016-01-01）")
    ap.add_argument("--symbols", default="", help="只處理這些代號（逗號分隔）")
    ap.add_argument("--batch", type=int, default=60, help="yfinance 每批檔數（預設 60）")
    ap.add_argument("--min-overlap", type=int, default=MIN_OVERLAP)
    ap.add_argument("--no-backup", dest="backup", action="store_false", default=True)
    args = ap.parse_args()

    syms = resolve_symbols(args)
    if not syms:
        print("❌ 找不到任何標的")
        return 1

    print(f"標的 {len(syms)} 檔｜補到 {args.start}｜{'APPLY' if args.apply else 'DRY-RUN'}")
    todo, plan_cache = [], {}
    for s in syms:
        p = os.path.join(CACHE_DIR, f"{s}.pkl")
        if not os.path.exists(p):
            continue
        old, _ = load_symbol(p)
        if old is None or len(old) == 0:
            continue
        first = old.index[0]
        if first <= datetime.fromisoformat(args.start) + timedelta(days=10):
            continue                       # 已涵蓋
        todo.append((s, p, old, first))
    print(f"需要補歷史: {len(todo)} 檔（其餘已涵蓋 {args.start}）")
    if not todo:
        return 0

    if args.apply and args.backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = f"{CACHE_DIR}_bak_prepend_{stamp}"
        shutil.copytree(CACHE_DIR, bak)
        print(f"📦 已備份快取目錄 → {os.path.basename(bak)}")

    ok = fail = 0
    failures = []
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        # ⚠️ end 要用「這批裡**最晚**的快取起始日」+ pad（2026-10-28 修）：
        #    原本用 min(...) ⇒ 同批若有「2026 才進池、快取只有近 250 天」的標的，
        #    抓取視窗會早早結束在 2022，於是那些標的被誤判成「重疊 0 天／yfinance 無資料」。
        end = (max(c[3] for c in chunk) + timedelta(days=OVERLAP_PAD_DAYS + 10)).strftime("%Y-%m-%d")
        fresh_map = fetch_batch([c[0] for c in chunk], args.start, end)
        for s, p, old, first in chunk:
            pl = plan_symbol(old, fresh_map.get(s), args.min_overlap)
            plan_cache[s] = pl
            if not pl["ok"]:
                fail += 1
                failures.append((s, pl["reason"]))
                print(f"  ⏭ {s}: {pl['reason']}")
                continue
            warn = " ⚠️接縫跳空" if abs(pl["seam_jump"]) > MAX_SEAM_JUMP else ""
            print(f"  ✅ {s}: +{len(pl['rows'])} 列 {pl['first_new']}→{pl['first_old']} "
                  f"ratio {pl['ratio']:.6f}(std {pl['ratio_std']:.1e}) 接縫 {pl['seam_jump']:+.2%}{warn}")
            if args.apply:
                from core.cache_io import dump_cache
                merged = merge_prepend(old, pl["rows"])
                meta = {"prepend_from": pl["first_new"], "prepend_rows": int(len(pl["rows"])),
                        "prepend_ratio": round(pl["ratio"], 8),
                        "prepended_at": datetime.now().isoformat(timespec="seconds"),
                        "source": "yfinance(auto_adjust)"}
                dump_cache(p, merged, meta=meta)
            ok += 1

    print(f"\n完成：成功 {ok}、略過/失敗 {fail}｜{'已寫入' if args.apply else '未寫入（dry-run）'}")
    if failures:
        kinds = {}
        for _s, why in failures:
            kinds[why] = kinds.get(why, 0) + 1
        for why, n in sorted(kinds.items(), key=lambda x: -x[1]):
            print(f"  - {why}: {n} 檔")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
