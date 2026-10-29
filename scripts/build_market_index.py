#!/usr/bin/env python3
"""scripts/build_market_index.py — 建立「加權指數（TAIEX）日線」快取，供回測的大盤年線濾網使用

## 為什麼需要

實盤在買進前會看**加權指數是否在年線（MA200）之上**（`selfselect_trader.py:819` +
`core/market_filter.py`，`MARKET_TREND_FILTER`）。但**回測腳本沒有這條規則**，所以 2018／2022
這種空頭年的回測結果比實盤更差（實盤那段時間根本不會買）。
要在回測裡重現它，就需要 2016 起、可重複取得的加權指數日線（`core/market_filter.py` 只抓近 15 個月、
存在記憶體，不能當回測資料源）。

## 資料源

TWSE 公開 API `FMTQIK`（免 token）：**一次回傳一個月**的「市場成交統計」，欄位含加權指數（TAIEX）。
本檔逐月抓、落地成 `cache/market_index/taiex.pkl`（`core.cache_io` 版本化格式，index=date、欄位 close）。

## 用法

    .venv/bin/python scripts/build_market_index.py                     # 2016-01 ~ 今天，補缺月
    .venv/bin/python scripts/build_market_index.py --start 2015-01-01
    .venv/bin/python scripts/build_market_index.py --dry-run           # 只報告缺哪幾個月

特性：**只補缺的月份**（已有快取不動），可重複執行；單月失敗會重試，最後印出覆蓋率與缺口。
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime

_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

OUT_DIR = os.path.join(_ROOT, "cache", "market_index")
OUT_PKL = os.path.join(OUT_DIR, "taiex.pkl")
URL = "https://www.twse.com.tw/en/exchangeReport/FMTQIK"


def months_between(start, end):
    y, m = start.year, start.month
    out = []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}{m:02d}01")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def fetch_month(ym, retries=3, sleep=0.8):
    """抓一個月 → DataFrame(index=date, close) 或 None。"""
    import pandas as pd
    import requests

    last = None
    for i in range(retries):
        try:
            r = requests.get(URL, params={"response": "json", "date": ym},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            rows = r.json().get("data") or []
            if not rows:
                return None            # 該月無資料（未來月份／休市）
            df = pd.DataFrame(rows, columns=["date", "volume", "value", "trades", "TAIEX", "change"])
            df["date"] = pd.to_datetime(df["date"], format="%Y/%m/%d", errors="coerce")
            for c in ("TAIEX", "change", "volume", "value", "trades"):
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
            df = df.dropna(subset=["date", "TAIEX"]).rename(columns={"TAIEX": "close"})
            df = df.set_index("date")[["close"]].sort_index()
            df.index.name = "Date"
            return df if len(df) else None
        except Exception as e:      # 網路/格式都重試
            last = e
            time.sleep(sleep * (i + 2))
    print(f"  ⚠️ {ym} 失敗：{last}")
    return None


def scan(close, window=200, days=0):
    """診斷用：回傳 (最後日期, 筆數, MA200 是否可用)。"""
    if close is None or len(close) < window:
        return (None, 0 if close is None else len(close), False)
    return (close.index[-1].date() if days == 0 else None, len(close), True)


def main():
    ap = argparse.ArgumentParser(description="建立加權指數日線快取（TWSE FMTQIK）")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.8)
    args = ap.parse_args()

    import pandas as pd
    from core.cache_io import dump_cache, load_cache_or_raw

    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()
    old = None
    if os.path.exists(OUT_PKL):
        old, meta = load_cache_or_raw(OUT_PKL)
        if old is not None and "close" in old.columns:
            print(f"既有快取：{len(old)} 筆（{old.index.min().date()} ~ {old.index.max().date()}）")
        else:
            old = None

    have = set(old.index.strftime("%Y%m") if old is not None else [])
    todo = [ym for ym in months_between(start, end) if ym[:6] not in have]
    print(f"需要補 {len(todo)} 個月（{args.start} ~ {end}）")
    if args.dry_run or not todo:
        if args.dry_run and todo:
            print("缺月：", ",".join(todo[:24]), "…" if len(todo) > 24 else "")
        return 0

    got = []
    for i, ym in enumerate(todo, 1):
        df = fetch_month(ym, sleep=args.sleep)
        if df is None:
            print(f"  ⏭ {ym}: 無資料")
        else:
            got.append(df)
            print(f"  ✅ {ym}: {len(df)} 筆（到 {df.index.max().date()}）")
        time.sleep(args.sleep)

    if not got:
        print("沒有任何新資料，未寫入")
        return 0
    merged = pd.concat([old] + got) if old is not None else pd.concat(got)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged.index.name = "Date"
    os.makedirs(OUT_DIR, exist_ok=True)
    dump_cache(OUT_PKL, merged, meta={"dataset": "FMTQIK", "source": "TWSE",
                                     "built_at": datetime.now().isoformat(timespec="seconds")})
    last, n, ok = scan(merged["close"])
    print(f"\n✅ 已寫入 {os.path.relpath(OUT_PKL, _ROOT)}：{n} 筆（{merged.index.min().date()} ~ {last}）"
          f"｜MA200 可用：{'是' if ok else '否（資料不足 200 筆）'}")
    # 缺口檢查（交易日對不上是正常的，只看「整個月缺」）
    miss = [ym for ym in months_between(start, end)
            if ym[:6] not in set(merged.index.strftime("%Y%m"))]
    if miss:
        print(f"⚠️ 仍缺 {len(miss)} 個月：{','.join(miss[:12])}{'…' if len(miss) > 12 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
