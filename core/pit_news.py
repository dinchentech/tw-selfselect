"""core/pit_news.py — 新聞的 point-in-time 來源（FinMind `TaiwanStockNews`）

## 為什麼挑這個來源

新聞要有**時間戳**才能證明「當時看得到」。FinMind `TaiwanStockNews` 每筆都有 `date`（到秒）、
`title`、`source`、`link`，而且本專案既有 token 可用（免費層）。

⚠️ 限制（實測 2026-10-28）：
- **必須帶 `data_id`**（不帶的全市場查詢要更高等級）⇒ **一檔一天一次呼叫**，
  成本＝N 檔 × D 天。所以：①預設 lookback 14 天、②每次抓到的結果落地成
  `cache/news/news_<sid>_<day>.pkl`（重跑免費）、③抓不到就**留空**（不得臆測）、④AI 選股預設**不啟用**（要 `--news`）。

## 口徑（保守）

選股決策發生在**收盤後**（D1 13:36 起），所以「當天 13:30 之後才發布的新聞」對這次決策是未來資訊。
本模組一律用 `cutoff="13:30"` 過濾：只採用 `ts <= 選股日 13:30` 的新聞。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from core.pit_data import NewsProvider, register_news_provider

NEWS_DIR = os.path.join("cache", "news")
CUTOFF = "13:30"


def _ts_ok(ts: str, as_of, cutoff: str = CUTOFF) -> bool:
    """`ts` 是否 <= as_of 當天的 cutoff（預設 13:30）。"""
    import pandas as pd

    limit = pd.Timestamp(str(as_of)[:10] + " " + cutoff)
    try:
        return pd.Timestamp(str(ts)) <= limit
    except Exception:
        return False


class FinmindNewsProvider(NewsProvider):
    """FinMind `TaiwanStockNews`（一檔一天一次；結果落地快取）。"""

    name = "finmind"

    def __init__(self, lookback_days: int = 14, cutoff: str = CUTOFF,
                 cache_dir: str = NEWS_DIR, limit: int = 20, fetch: bool = True):
        self.lookback_days = int(lookback_days)
        self.cutoff = cutoff
        self.cache_dir = cache_dir
        self.limit = int(limit)
        self.fetch_enabled = bool(fetch)
        self.misses = 0          # 抓不到的天數（供報告「資料可信度」）

    # ── 單日快取 ─────────────────────────────────────────
    def _cache_path(self, sid: str, day: str) -> str:
        return os.path.join(self.cache_dir, f"news_{sid}_{day}.pkl")

    def _day_rows(self, sid: str, day: str):
        from core.cache_io import dump_cache, load_cache_or_raw

        path = self._cache_path(sid, day)
        rows, _ = load_cache_or_raw(path)
        if isinstance(rows, list):
            return rows                      # 空 list 也代表「抓過了、那天沒有」
        if not self.fetch_enabled:
            return None
        rows = self._fetch_day(sid, day)
        if rows is None:
            self.misses += 1
            return None
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            dump_cache(path, rows, meta={"dataset": "TaiwanStockNews", "symbol": sid, "day": day})
        except Exception:
            pass
        return rows

    def _fetch_day(self, sid: str, day: str):
        import requests

        tok = os.getenv("FINMIND_API_TOKEN")
        if not tok:
            return None
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": "TaiwanStockNews", "data_id": str(sid),
                                     "start_date": day, "end_date": day},
                             headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            d = r.json()
            if d.get("status") != 200:
                return None                  # 402 配額／等級不足 → 當作抓不到（留空）
            out = []
            for row in d.get("data") or []:
                if str(row.get("stock_id")) != str(sid):
                    continue
                out.append({"ts": str(row.get("date")), "title": row.get("title") or "",
                            "url": row.get("link") or "", "source": row.get("source") or ""})
            return out
        except Exception:
            return None

    # ── 介面 ─────────────────────────────────────────────
    def fetch(self, sid: str, as_of) -> list[dict]:
        import pandas as pd

        as_of_ts = pd.Timestamp(as_of)
        start = (as_of_ts - timedelta(days=self.lookback_days)).date()
        out = []
        d = start
        while d <= as_of_ts.date():
            if d.weekday() < 5:              # 週末不查（台股不開盤，新聞對選股無意義）
                rows = self._day_rows(sid, d.isoformat())
                for x in rows or []:
                    if _ts_ok(x.get("ts"), as_of, self.cutoff):
                        out.append(x)
            d += timedelta(days=1)
        out.sort(key=lambda x: x["ts"])
        return out[-self.limit:]


def register(provider: NewsProvider | None = None) -> NewsProvider:
    """把 FinMind 新聞註冊成 `NEWS_PROVIDER=finmind`（回傳實例，方便測試／報告 miss 數）。"""
    p = provider or FinmindNewsProvider()
    register_news_provider("finmind", p)
    return p
