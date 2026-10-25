"""core/price_append.py — 把最近交易日**附加**到 `cache/selector_prices/`（共用實作）

供兩處共用（**唯一實作，禁止各寫一套**）：
1. CLI：`scripts/append_selector_prices.py`（人工／換股日前執行）
2. 實盤選股：`scripts/stock_selector_grid.py` 的 `--recommend` 路徑（選股前自動補到最近交易日）

## 為什麼需要

`stock_selector_grid.load_stock()` 若快取檔存在且 schema 正確就直接回傳
（`core.cache_io.load_cache` 只驗版本、**沒有新鮮度檢查**）⇒ **不會自動刷新**。
實測 2026-09-14：候選池 100 檔資料停在 2026-08-13（本機）／2026-08-05（VM），
而法人資料即時補抓到當天 ⇒ 選股變成「價格面用一個月前、法人面用當天」。
**同一組參數、只差資料新鮮度，選出的前三檔完全不同**（3017/3653/2059 → 2884/2883/2801）。
（法人面沒問題：selector 會 `fetch_twse_day` 即時補抓 ✓。）

## 為什麼是「附加」而不是「重抓」

同一份快取也供 selector 自己的 `--grid`／`--backtest` 用（涵蓋 2015 起）。
整檔換成「近 250 天」會**毀掉長歷史**；重抓整段歷史會讓**歷史數值變動**
（還原價係數因新除息回溯改變）⇒ 回測結果會靜默改變。
因此本模組**只追加 `last_date` 之後的新交易日**，`last_date`（含）以前一個位元都不動。

⚠️ **舊格式快取**：VM 上的 `selector_prices/*.pkl` 曾是**裸 DataFrame**（無 `schema_version`）。
嚴格 `load_cache()` 會回 `(None, None)` ⇒ 而 `load_stock()` 接著會「重新下載 250 天並覆蓋」
⇒ **長歷史被毀**。本模組用 `load_cache_or_raw`（遷移式）讀、`dump_cache` 寫（順便升級 v2）。

## 接縫縮放（splice）

還原價係數會因除息/減資**回溯改變** ⇒ 新抓的資料與舊快取不在同一基準，直接接起來會在
接縫日出現**假跳空**（實測 3706 於 2026-08-14 出現 −11.52%）。
做法：用**重疊日**（同一天、同一市場 ⇒ 差異純粹來自版本）算 `ratio = 舊收盤 / 新收盤`，
把**附加段**整體乘上 ratio。
- 舊歷史一個位元都不動（回測可重現性優先）。
- 附加段**自己的日報酬完全不變**（整段同乘常數）⇒ 動能計算正確。
- 代價：附加段的絕對價位是「舊基準」，不等於現行還原價（選股只用報酬/均線比例，不受影響）。
"""
import os
import pickle
import shutil
import sys
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

CACHE_DIR = os.path.join(_ROOT, "cache", "selector_prices")
CAP_RANKING = os.path.join(_ROOT, "cache", "inst_momentum", "mcap_ranking.pkl")


# ── 讀取／下載 ────────────────────────────────────────────────────
def load_cached(path):
    """讀快取 —— 用 `load_cache_or_raw`（遷移式，容忍舊格式），回傳 (df, meta)。"""
    from core.cache_io import load_cache_or_raw
    df, meta = load_cache_or_raw(path)
    return df, meta or {}


def fetch_prices(symbol, start, end):
    """抓還原價（`auto_adjust=True`，與快取語義一致）。回傳 DataFrame 或 None。"""
    import pandas as pd
    import yfinance as yf

    df = yf.download(f"{symbol}.TW", start=start, end=end,
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume"})
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def latest_trading_day_hint():
    """最近「可能的」交易日（只跳過週末；國定假日由資料本身決定）。"""
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ── 純函式：合併與完整性 ──────────────────────────────────────────
def drop_unusable_rows(df):
    """丟掉「沒有可用收盤價」的列（close 為 NaN 或 ≤ 0）。

    ⚠️ 為什麼必要（2026-09-18 實測事故）：yfinance 對**最新一個交易日**可能回傳
    「只有 volume、OHLC 全 NaN」的半成品 K 棒 —— 當天 500/500 檔的 2026-09-17 全是這種列
    （09-16 及以前 0 筆）。這種列一旦寫進快取，就成了選股的**基準日**：
    `score_stock()` 的 close／波動／均線全變 NaN ⇒ total 全 NaN ⇒ 排序失效 ⇒ 亂選
    （實測選出 2317/2881/2882，總分都是 NaN）。寧可那天不進快取（隔天補價會自然補上）。
    """
    if df is None or getattr(df, "empty", True):
        return df
    if "close" not in df.columns:
        return df
    return df[df["close"].notna() & (df["close"] > 0)]


def merge_append(old, fresh, splice=True):
    """附加式合併：`old.index[-1]`（含）以前完全不動，只接上更新的日期。

    回傳 (merged, stats)：rows_added / last_old / last_new / vintage_max_diff
    / vintage_date / splice_ratio / splice_date。
    """
    import pandas as pd

    last_old = old.index[-1]
    overlap = old.index.intersection(fresh.index)
    vmax, vdate, ratio, rdate = 0.0, None, 1.0, None
    for d in overlap:
        try:
            a, b = float(old.loc[d, "close"]), float(fresh.loc[d, "close"])
        except Exception:
            continue
        if a > 0:
            diff = abs(b / a - 1.0)
            if diff > vmax:
                vmax, vdate = diff, d
    if splice and len(overlap):
        d = overlap[-1]
        try:
            a, b = float(old.loc[d, "close"]), float(fresh.loc[d, "close"])
            if a > 0 and b > 0:
                ratio, rdate = a / b, d
        except Exception:
            ratio = 1.0

    newer = drop_unusable_rows(fresh[fresh.index > last_old])
    if len(newer) and abs(ratio - 1.0) > 1e-9:
        newer = newer.copy()
        for col in ("open", "high", "low", "close"):
            if col in newer.columns:
                newer[col] = newer[col] * ratio
    merged = pd.concat([old, newer]) if len(newer) else old.copy()
    merged = merged[~merged.index.duplicated(keep="first")].sort_index()
    return merged, {
        "rows_added": int(len(newer)),
        "last_old": str(last_old)[:10],
        "last_new": str(merged.index[-1])[:10],
        "vintage_max_diff": vmax,
        "vintage_date": str(vdate)[:10] if vdate is not None else None,
        "splice_ratio": ratio,
        "splice_date": str(rdate)[:10] if rdate is not None else None,
    }


def integrity_ok(old, merged):
    """硬性檢查：合併後**不可遺失或改動任何舊列**（否則視為資料毀損，必須中止）。"""
    if len(merged) < len(old):
        return False, f"列數變少（{len(old)} → {len(merged)}）"
    missing = old.index.difference(merged.index)
    if len(missing):
        return False, f"遺失 {len(missing)} 個舊日期（首個 {str(missing[0])[:10]}）"
    for d in old.index:
        try:
            if abs(float(old.loc[d, "close"]) - float(merged.loc[d, "close"])) > 1e-9:
                return False, f"舊日期 {str(d)[:10]} 的收盤價被改動"
        except Exception:
            pass
    return True, ""


# ── 單檔更新 ──────────────────────────────────────────────────────
def update_symbol(symbol, *, fetcher=None, apply=False, overlap_days=30, splice=True,
                  cache_dir=None, backup_dir=None, end_date=None):
    """把一檔標的補到最近交易日。

    回傳 `(status, payload)`：status ∈
      "updated"（已寫入）/ "would_update"（dry-run 可更新）/ "skipped" / "failed"
    payload 含 stats 或原因字串。
    """
    from core.cache_io import dump_cache

    cache_dir = cache_dir or CACHE_DIR
    fetcher = fetcher or fetch_prices
    path = os.path.join(cache_dir, f"{symbol}.pkl")
    if not os.path.exists(path):
        return "skipped", "無快取"
    old, meta = load_cached(path)
    if old is None or getattr(old, "empty", True):
        return "skipped", "快取無法讀取或為空（需重建）"
    last_old = old.index[-1]
    if str(last_old)[:10] >= latest_trading_day_hint().isoformat():
        return "skipped", f"已是最新（{str(last_old)[:10]}）"

    start = (last_old - timedelta(days=overlap_days)).date().isoformat()
    end = end_date or (date.today() + timedelta(days=1)).isoformat()
    try:
        fresh = fetcher(symbol, start, end)
    except Exception as e:
        return "failed", f"下載失敗 {type(e).__name__}: {e}"
    if fresh is None or fresh.empty:
        return "failed", "下載為空"

    merged, st = merge_append(old, fresh, splice=splice)
    ok, why = integrity_ok(old, merged)
    if not ok:
        return "failed", f"完整性檢查失敗：{why}"
    if st["rows_added"] == 0:
        return "skipped", f"無新交易日（下載末日 {st['last_new']}）"

    if apply:
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(path, os.path.join(backup_dir, f"{symbol}.pkl"))
        meta = dict(meta)
        meta.update({"appended_at": datetime.now().isoformat(timespec="seconds"),
                     "appended_rows": st["rows_added"], "last_date": st["last_new"]})
        dump_cache(path, merged, meta=meta)
        back, _ = load_cached(path)
        if back is None or str(back.index[-1])[:10] != st["last_new"]:
            return "failed", "寫後驗證失敗"
        return "updated", st
    return "would_update", st


def drop_nan_in_cache(symbol, *, apply=False, cache_dir=None, backup_dir=None):
    """把快取檔裡「沒有可用收盤價」的列就地移除（補救 2026-09-17 那批 NaN 列用）。

    為什麼需要獨立動作：`merge_append()` 的契約是「舊列一位元都不動」
    （回測可重現性），所以修好 source 端之後，**已經寫進去的 NaN 列不會自己消失** ——
    而它就卡在「最後一列＝選股基準日」這個最傷的位置上。

    回傳 `(status, payload)`：status ∈ "updated" / "would_update" / "skipped"。
    """
    cache_dir = cache_dir or CACHE_DIR
    path = os.path.join(cache_dir, f"{symbol}.pkl")
    if not os.path.exists(path):
        return "skipped", "無快取"
    df, meta = load_cached(path)
    if df is None or getattr(df, "empty", True):
        return "skipped", "快取無法讀取或為空"
    kept = drop_unusable_rows(df)
    dropped = int(len(df) - len(kept))
    if dropped == 0:
        return "skipped", "無 NaN 列"
    st = {"dropped": dropped, "last_old": str(df.index[-1])[:10],
          "last_new": str(kept.index[-1])[:10]}
    if not apply:
        return "would_update", st
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(backup_dir, f"{symbol}.pkl"))
    from core.cache_io import dump_cache
    meta = dict(meta)
    meta.update({"dropped_nan_at": datetime.now().isoformat(timespec="seconds"),
                 "dropped_nan_rows": dropped, "last_date": st["last_new"]})
    dump_cache(path, kept, meta=meta)
    back, _ = load_cached(path)
    if back is None or len(back) != len(kept):
        return "failed", "寫後驗證失敗"
    return "updated", st


# ── 選股前的自動補價（實盤用）─────────────────────────────────────
def ensure_fresh(symbols, *, enabled=True, apply=True, deadline_s=600, splice=True,
                 fetcher=None, cache_dir=None, verbose=True, backup=False):
    """選股前把候選池報價補到最近交易日。**任何失敗都不阻斷選股**（回報後照常選）。

    回傳 dict：checked / updated / skipped / failed / elapsed_s / stopped_early
    """
    report = {"checked": 0, "updated": 0, "skipped": 0, "failed": 0,
              "elapsed_s": 0.0, "stopped_early": False, "notes": []}
    if not enabled or not symbols:
        return report
    import time
    t0 = time.time()
    for sym in symbols:
        if time.time() - t0 > deadline_s:
            report["stopped_early"] = True
            report["notes"].append(f"超過時限 {deadline_s}s，剩餘標的未處理（本次改用現有快取）")
            break
        report["checked"] += 1
        try:
            status, payload = update_symbol(
                sym, fetcher=fetcher, apply=apply, splice=splice, cache_dir=cache_dir,
                backup_dir=None, end_date=None)
        except Exception as e:                       # 絕不讓補價中斷選股
            status, payload = "failed", f"{type(e).__name__}: {e}"
        if status in ("updated", "would_update"):
            report["updated"] += 1
            if verbose and isinstance(payload, dict):
                print(f"   📈 {sym}: {payload['last_old']} → {payload['last_new']}"
                      f"（+{payload['rows_added']} 列）")
        elif status == "skipped":
            report["skipped"] += 1
        else:
            report["failed"] += 1
            report["notes"].append(f"{sym}: {payload}")
    report["elapsed_s"] = round(time.time() - t0, 1)
    return report


def resolve_pool_symbols(pool_size=None, cache_dir=None):
    """由市值排名取候選池代號（list 或 dict 舊 payload 都吃）。"""
    cache_dir = cache_dir or CACHE_DIR
    if not os.path.exists(CAP_RANKING):
        return []
    try:
        with open(CAP_RANKING, "rb") as f:
            ranked = pickle.load(f)
    except Exception:
        return []
    if isinstance(ranked, dict):
        for key in ("data", "ranking", "symbols"):
            if isinstance(ranked.get(key), (list, tuple)):
                ranked = ranked[key]
                break
        else:
            return []
    if not isinstance(ranked, (list, tuple)):
        return []
    syms = [str(s) for s in ranked if str(s).isdigit() and len(str(s)) == 4]
    return syms[:int(pool_size)] if pool_size else syms
