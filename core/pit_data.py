"""core/pit_data.py — point-in-time 資料源（月營收＋新聞介面），供 AI 選股封包使用

## 為什麼需要「可用時間」而不只是「資料時間」

月營收的 `date` 是**營收所屬月份**（例 2022-01-01 代表 2022 年 1 月營收），但那一筆資料**不是**當天就公布，
台股法定公告期限是**次月 10 日前**。若直接用 `date` 當「當時看得到」，就會在 1 月中就知道 1 月整月營收
＝**偷看未來**。所以本模組統一用 `available_from`：

    available_from = create_time（若資料源有給）
                     否則 = 所屬月份的次月 10 日（法定公告期限，保守）

只有 `available_from <= as_of` 的營收才算「當時看得到」。

## 新聞

本專案**沒有**新聞來源。這裡只提供介面（`NewsProvider`）與「明確留空」的預設實作：
`UnavailableNews` 會回 `{"unavailable": True}`，**不得**用模型記憶補上。
要接來源時實作 `NewsProvider.fetch(sid, as_of)`（回傳 `[{ts, title, url}]`，且 `ts <= as_of`），
再註冊到 `NEWS_PROVIDERS`；`core.ai_pick` 與 `scripts/ai_pick_preview.py` 會自動使用。

## 月營收快取

`cache/stock_revenue/rev_<sid>.pkl`（`core.cache_io` 版本化）：`{date_str: {revenue, yoy_base_month}}`…
實際存的是原始列，計算在 `revenue_pack()` 內完成；**抓一次長期重用**（FinMind 有配額）。
"""
from __future__ import annotations

import os
from datetime import date, datetime

SCHEMA_VERSION = 1
REV_DIR = os.path.join("cache", "stock_revenue")
#: 台股月營收法定公告期限（次月 10 日）
ANNON_DEADLINE_DAY = 10


# ── 月營收 ───────────────────────────────────────────────────────
def revenue_available_from(revenue_year: int, revenue_month: int, create_time: str = "") -> str:
    """這筆月營收「當時看得到」的日期（YYYY-MM-DD）。

    有 `create_time`（資料源給的建立時間）就用它；否則用**次月 10 日**（法定公告期限，保守）。
    """
    if create_time and str(create_time).strip():
        return str(create_time)[:10]
    y, m = int(revenue_year), int(revenue_month) + 1
    if m > 12:
        y, m = y + 1, 1
    return f"{y}-{m:02d}-{ANNON_DEADLINE_DAY:02d}"


def revenue_pack(rows, as_of, months: int = 6) -> dict:
    """從 FinMind 月營收列（`[{date, revenue, revenue_year, revenue_month, create_time}]`）
    取出「`as_of` 當時看得到」的最近 `months` 個月，並算 MoM／YoY。

    回傳 `{"available": True, "items": [...], "provenance": "..."} `或
    `{"unavailable": True, "reason": "..."}`（資料不足時**不得**臆測）。
    """
    import pandas as pd

    limit = pd.Timestamp(as_of)
    seen = {}
    for r in rows or []:
        try:
            y, m = int(r.get("revenue_year")), int(r.get("revenue_month"))
            rev = float(r.get("revenue") or 0)
        except (TypeError, ValueError):
            continue
        if rev <= 0:
            continue
        avail = revenue_available_from(y, m, r.get("create_time", ""))
        if pd.Timestamp(avail) > limit:
            continue                      # 選股日當時還沒公布
        seen[(y, m)] = (rev, avail)
    if not seen:
        return {"unavailable": True, "reason": "as_of 當時沒有任何已公布的月營收（或快取為空）"}

    keys = sorted(seen)[-max(1, int(months)):]
    items = []
    for y, m in keys:
        rev, avail = seen[(y, m)]
        prev = seen.get((y - 1, m))       # 去年同月 → YoY
        prev_m = seen.get((y, m - 1) if m > 1 else (y - 1, 12))   # 上月 → MoM
        items.append({
            "year": y, "month": m, "revenue": rev,
            "yoy": round(rev / prev[0] - 1, 4) if prev and prev[0] > 0 else None,
            "mom": round(rev / prev_m[0] - 1, 4) if prev_m and prev_m[0] > 0 else None,
            "available_from": avail,
        })
    return {"available": True, "items": items,
            "provenance": max(v[1] for v in seen.values())}


def fetch_revenue(sid: str, start: str = "2015-01-01", end: str | None = None):
    """FinMind `TaiwanStockMonthRevenue` → 原始列 list（需要 `FINMIND_API_TOKEN`）。"""
    import requests

    tok = os.getenv("FINMIND_API_TOKEN")
    if not tok:
        return None
    end = end or date.today().isoformat()
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanStockMonthRevenue", "data_id": str(sid),
                                 "start_date": start, "end_date": end},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        d = r.json()
        if d.get("status") != 200:
            return None
        return d.get("data") or []
    except Exception:
        return None


def load_revenue_rows(sid: str, fetch: bool = True):
    """讀月營收快取；沒有就抓一次並落地（之後離線可用）。"""
    import os as _os
    from core.cache_io import dump_cache, load_cache_or_raw

    path = _os.path.join(REV_DIR, f"rev_{sid}.pkl")
    rows, _meta = load_cache_or_raw(path)
    if isinstance(rows, list) and rows:
        return rows
    if not fetch:
        return None
    fresh = fetch_revenue(sid)
    if not fresh:
        return None
    try:
        _os.makedirs(REV_DIR, exist_ok=True)
        dump_cache(path, fresh, meta={"dataset": "TaiwanStockMonthRevenue", "symbol": str(sid)})
    except Exception:
        pass
    return fresh


# ── 本益比（PER）：磁碟快取優先，必要時才抓 ─────────────────────────────
# 為什麼要有這一段：`SCORING_MODEL=zscore` 的資格是「0 < PER <= 40」，沒有 PER 的股票**根本不會被選到**
# ⇒ PER 的取得方式會直接決定選股結果。舊版實盤只在「價量過熱命中」時才抓 PER（省限流），
# 結果大多數候選股的 `per=None` 被資格門檻默默剔除；而 `cache/stock_per/per_<sid>.pkl`
# 現在已涵蓋 672 檔（2026-10-29 補齊）。所以改成「先讀磁碟快取、缺檔才打 FinMind」，
# 與回測共用同一份序列（回測的 `_oh_get_per()` 也只讀這份快取）。
PER_DIR = os.path.join("cache", "stock_per")


def load_per_series(sid: str):
    """讀 `cache/stock_per/per_<sid>.pkl`（`{date: PER}`）；沒有 → None。"""
    from core.cache_io import load_cache

    try:
        d, _meta = load_cache(os.path.join(PER_DIR, f"per_{sid}.pkl"))
    except Exception:
        return None
    return d if isinstance(d, dict) and d else None


def per_at(series, sel_date):
    """{date_str: PER} → 最近一筆 ≤ sel_date 的 PER（無 → None）。純函式，可單獨測試。"""
    import pandas as pd

    if not series:
        return None
    cut = pd.Timestamp(sel_date).normalize()
    best_d, best_v = None, None
    for d, v in series.items():
        try:                                   # 容忍 ISO / 'YYYY/MM/DD' / Timestamp 三種鍵
            ds = pd.Timestamp(d)
            if ds.tz is not None:
                ds = ds.tz_localize(None)
        except Exception:
            continue
        if ds <= cut and (best_d is None or ds > best_d):
            try:
                best_v = float(v)
            except (TypeError, ValueError):
                continue
            best_d = ds
    return best_v


def fetch_per(sid: str, start: str = "2015-01-01", end: str | None = None):
    """FinMind `TaiwanStockPER` → `{date: PER}`（需要 `FINMIND_API_TOKEN`）。"""
    import requests

    tok = os.getenv("FINMIND_API_TOKEN")
    if not tok:
        return None
    end = end or date.today().isoformat()
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanStockPER", "data_id": str(sid),
                                 "start_date": start, "end_date": end},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        d = r.json()
        if d.get("status") != 200:
            return None
        out = {}
        for x in d.get("data") or []:
            per, day = x.get("PER"), str(x.get("date") or "")
            if not day or per in (None, ""):
                continue
            try:
                out[day] = float(per)
            except (TypeError, ValueError):
                continue
        return out or None
    except Exception:
        return None


def per_asof(sid: str, as_of, fetch: bool = False):
    """≤ as_of 的 PER：**先讀磁碟快取**，沒有（或查不到值）且 `fetch=True` 才打 FinMind 並落地。"""
    import os as _os

    from core.cache_io import dump_cache

    series = load_per_series(sid)
    per = per_at(series, as_of)
    if per is not None or not fetch:
        return per
    fresh = fetch_per(sid)
    if not fresh:
        return None
    merged = {**(series or {}), **fresh}
    try:
        _os.makedirs(PER_DIR, exist_ok=True)
        dump_cache(_os.path.join(PER_DIR, f"per_{sid}.pkl"), merged,
                   meta={"dataset": "TaiwanStockPER", "symbol": str(sid)})
    except Exception:
        pass
    return per_at(merged, as_of)


# ── 新聞（介面；預設無來源）────────────────────────────────────────
class NewsProvider:
    """新聞來源介面。實作 `fetch(sid, as_of)` → `[{ts, title, url}]`（`ts` 必須 ≤ as_of）。"""

    name = "base"

    def fetch(self, sid: str, as_of) -> list[dict]:  # pragma: no cover - 介面
        raise NotImplementedError


class UnavailableNews(NewsProvider):
    """沒有新聞來源時的唯一合法答案：明確留空。"""

    name = "unavailable"

    def fetch(self, sid: str, as_of) -> list[dict]:
        return []


NEWS_PROVIDERS: dict[str, NewsProvider] = {"unavailable": UnavailableNews()}


def register_news_provider(name: str, provider: NewsProvider) -> None:
    NEWS_PROVIDERS[name] = provider


def news_pack(sid: str, as_of, provider: str | None = None, cutoff: str = "13:30") -> dict:
    """取得 `as_of` 當時**已發布**的新聞標題（沒有來源就明確標 `unavailable`）。

    `cutoff`：選股決策時點（D1 收盤後 13:36 ⇒ 預設 13:30）。**當天 cutoff 之後發布的新聞
    對這次決策是未來資訊**，一律排除（實測 2022-01-03 20:00 的新聞不得進 1/3 的封包）。
    """
    import pandas as pd

    name = provider or os.getenv("NEWS_PROVIDER", "unavailable")
    p = NEWS_PROVIDERS.get(name)
    if p is None or isinstance(p, UnavailableNews):
        return {"unavailable": True,
                "reason": f"本專案沒有新聞來源（NEWS_PROVIDER={name}）；不得用模型記憶填補"}
    try:
        items = p.fetch(sid, as_of) or []
    except Exception as e:  # 來源壞掉 → 留空，不影響選股流程
        return {"unavailable": True, "reason": f"新聞來源錯誤：{e}"}
    limit = pd.Timestamp(str(as_of)[:10] + " " + cutoff)
    kept = [x for x in items if x.get("ts") and pd.Timestamp(x["ts"]) <= limit]
    if not kept:
        return {"unavailable": True, "reason": "as_of 當時沒有可用新聞"}
    kept.sort(key=lambda x: x["ts"])
    return {"available": True, "items": kept[-20:],
            "provenance": str(kept[-1]["ts"])[:10], "provider": p.name}
