"""
inst_data.py — 台股資料層（TWSE 法人／股價，回測與實盤唯一來源）

回測與實盤共用此模組，確保 TWSE T86 參數/欄位、FinMind 正規化、快取新鮮度、
選股池定義一致，避免兩套資料程式各自演進造成實盤靜默失效（2026-08 事件的教訓）。

提供：
  - fetch_twse_day / fetch_twse_inst_bulk   TWSE T86 三大法人（唯一實作）
  - get_price_data                          股價（finmind / twse / yfinance），含快取新鮮度
  - get_institutional_data                  法人買賣（finmind / twse），含快取新鮮度與 TWSE 逐日快取
  - TwseDayCache                            TWSE 逐日快取（實盤備援避免逐股逐日重複呼叫）
  - aggregate_institutional                 投信+外資每日加總（core 格式）
  - get_all_stock_ids                       市值前 N 選股池（與回測一致）

快取格式一律經 _dump_cache/_load_cache 版本化（CACHE_SCHEMA_VERSION）。
快取資料語義改變（欄位/價格調整/正規化方式）時必須遞增版本，否則舊快取會被靜默載入
——這是 2026-08 回測數字無法重現事件（價格快取混入 yfinance 還原價）的根因。
"""
import os
import pickle
import time
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from core.cache_io import CACHE_SCHEMA_VERSION, load_cache as _load_cache, dump_cache as _dump_cache

FINMIND_TOKEN_KEY = "FINMIND_API_TOKEN"

TWSE_T86_URL = "https://www.twse.com.tw/fund/T86"

# T86 欄位定義（唯一來源；回測與實盤共用）：
#   0 證券代號 | 1 證券名稱 | 2 外陸資買進 | 3 外陸資賣出 | 4 外陸資買賣超
#   5 外資自營商買進 | 6 外資自營商賣出 | 7 外資自營商買賣超
#   8 投信買進 | 9 投信賣出 | 10 投信買賣超
#   11 自營商買賣超 | 12 自營商(自行)買進 | 13 自營商(自行)賣出 | 14 自營商(自行)買賣超
#   15 自營商(避險)買進 | 16 自營商(避險)賣出 | 17 自營商(避險)買賣超 | 18 三大法人買賣超

FINMIND_INST_NAME_MAP = {
    "Foreign_Investor": "外資",
    "Investment_Trust": "投信",
    "Foreign_Dealer_Self": "自營商",
    "Dealer_self": "自營商",
    "Dealer_Hedging": "自營商",
}


def _safe_int(val) -> int:
    if isinstance(val, str):
        val = val.replace(",", "").strip()
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


# ─── TWSE T86 三大法人（唯一實作）────────────────────────

class TwseBlockedError(Exception):
    """TWSE T86 反爬封鎖（428 或 HTML 回應）— 呼叫方可改走 FinMind 補段"""


def fetch_twse_day(dt_str: str) -> dict:
    """TWSE T86 單日全市場法人資料。

    回傳 { stock_id: {"外資": {buy, sell}, "投信": {buy, sell}, "自營商": {buy, sell}} }
    失敗或 stat != OK 回傳 {}；**TWSE 反爬封鎖（428/HTML）拋 TwseBlockedError**。

    欄位以 API 回傳的 fields 標題動態定位（2026-08-28 修正）：
    2015-2016 為 16 欄格式（投信 [5]/[6]），2017+ 為 19 欄（投信 [8]/[9]、
    外陸資不含外資自營商）— 舊版硬編碼 19 欄索引解析 2015 資料時
    row[16] IndexError → 誤判「TWSE 無 2015 資料」→ 改用 FinMind 補抓
    （撞配額 402）。實測 TWSE T86 完整涵蓋 2015-2025。
    """
    try:
        params = {"response": "json", "date": dt_str, "selectType": "ALLBUT0999"}
        resp = requests.get(TWSE_T86_URL, params=params,
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 428 or not resp.text.strip().startswith("{"):
            # 反爬封鎖（428 Precondition Required 或 HTML 驗證頁）—
            # 2026-08-28：大量連續請求觸發，靜默回 {} 會讓回測法人殘缺 → 假數字
            raise TwseBlockedError(f"TWSE 428/HTML blocked ({dt_str}, status={resp.status_code})")
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return {}

        fields = data.get("fields", [])
        def idx(*names):
            for n in names:
                if n in fields:
                    return fields.index(n)
            return None

        i_fb = idx("外資買進股數", "外陸資買進股數(不含外資自營商)")
        i_fs = idx("外資賣出股數", "外陸資賣出股數(不含外資自營商)")
        i_tb = idx("投信買進股數")
        i_ts = idx("投信賣出股數")
        i_sb = idx("自營商買進股數(自行買賣)")
        i_ss = idx("自營商賣出股數(自行買賣)")
        i_hb = idx("自營商買進股數(避險)")
        i_hs = idx("自營商賣出股數(避險)")
        if i_fb is None or i_fs is None or i_tb is None or i_ts is None:
            return {}

        day = {}
        for row in data["data"]:
            sid = row[0].strip()
            try:
                day[sid] = {
                    "外資": {"buy": _safe_int(row[i_fb]), "sell": _safe_int(row[i_fs])},
                    "投信": {"buy": _safe_int(row[i_tb]), "sell": _safe_int(row[i_ts])},
                    "自營商": {
                        "buy": (_safe_int(row[i_sb]) if i_sb is not None else 0)
                               + (_safe_int(row[i_hb]) if i_hb is not None else 0),
                        "sell": (_safe_int(row[i_ss]) if i_ss is not None else 0)
                                + (_safe_int(row[i_hs]) if i_hs is not None else 0),
                    },
                }
            except (ValueError, IndexError):
                continue
        return day
    except TwseBlockedError:
        raise  # 反爬封鎖往上拋（呼叫方改走 FinMind 補段）
    except Exception:
        return {}


def fetch_twse_inst_bulk(trading_dates, cache_path=None, progress_every=50) -> dict:
    """逐日抓 T86 並聚合為 { date_str: { stock_id: (inst_buy, inst_sell) } }（投信+外資）。

    回測使用；cache_path 存在時直接載入，否則下載後寫入快取。
    trading_dates: date/datetime 集合。
    """
    if cache_path is not None and cache_path.exists():
        data, _meta = _load_cache(cache_path)
        if data is not None:
            print(f"   載入 TWSE 法人資料快取（{Path(cache_path).name}）...")
            return data

    inst_data = {}
    dates = sorted(trading_dates)
    blocked = 0
    for i, d in enumerate(dates):
        if hasattr(d, "strftime"):
            dt_str = d.strftime("%Y%m%d")
            key = d.isoformat()
        else:
            dt_str = str(d).replace("-", "")
            key = str(d)[:10]
        # TWSE 大量連續請求會限流/超時（2026-08-28：7 年窗口 1712 天只
        # 成功 44 天 → 回測法人殘缺 → 勝率 100% 假象）→ 單日重試 3 次
        day = None
        for attempt in range(3):
            try:
                day = fetch_twse_day(dt_str)
                break
            except TwseBlockedError:
                blocked += 1
                time.sleep(1.5 * (attempt + 1))
        if day:
            inst_data[key] = {
                sid: (v["外資"]["buy"] + v["投信"]["buy"], v["外資"]["sell"] + v["投信"]["sell"])
                for sid, v in day.items()
            }
        if progress_every and (i + 1) % progress_every == 0:
            print(f"   TWSE 下載進度: {i+1}/{len(dates)}")

    if blocked > len(dates) * 0.3:
        # 大量封鎖（>30%）→ 資料殘缺，拋出讓回測層改用 FinMind 補段
        raise TwseBlockedError(
            f"TWSE 反爬封鎖 {blocked}/{len(dates)} 天（>30%）— 需 FinMind 補段")

    if cache_path is not None:
        _dump_cache(cache_path, inst_data, meta={"source": "TWSE_T86", "dates": len(inst_data)})
        print(f"✅ TWSE 法人資料下載完成: {len(inst_data)} 交易日")
    return inst_data


def fetch_price_history_bulk(dl, stock_ids, start, end, cache_dir=None,
                             retry_wait=3600, max_retries=2) -> dict:
    """逐股抓價格歷史（FinMind，與實盤同資料層），回傳 { sid: DataFrame }。

    回測專用（2026-08-25 事故：回測與實盤共用 cache/inst_momentum/price/，
    實盤短歷史覆寫回測長歷史 → 2015-2020 無價格 → 魚過濾全滅、README 數字無法重現）。
    獨立快取目錄（預設 cache/inst_momentum/bt_price/），meta 記錄 start/end。
    FinMind 免費配額 600/hr：遇 402 自動等待 retry_wait 秒後重試（最多 max_retries 次）。
    """
    import time
    start_s, end_s = str(start)[:10], str(end)[:10]
    if cache_dir is None:
        cache_dir = Path("cache/inst_momentum/bt_price")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    out = {}
    for sid in stock_ids:
        cache_path = cache_dir / f"{sid}.pkl"
        df = None
        if cache_path.exists():
            cached, meta = _load_cache(cache_path)
            if cached is not None and not cached.empty:
                m = meta or {}
                # 請求範圍 ⊆ 快取範圍 → 命中（2026-08-28：精確等於會讓不同
                # 窗口互相覆寫快取，且首次下載遇配額 402 殘缺 → 全窗口假數字）
                if (m.get("start", "") <= start_s and m.get("end", "") >= end_s):
                    df = cached
        if df is None:
            for attempt in range(max_retries + 1):
                try:
                    raw = dl.taiwan_stock_daily(
                        stock_id=sid, start_date=start_s, end_date=end_s)
                    if raw is not None and not raw.empty:
                        df = _norm_price(raw)
                    break
                except Exception as e:
                    if "upper limit" in str(e) and attempt < max_retries:
                        print(f"   ⏳ FinMind 配額用盡，等待 {retry_wait/60:.0f} 分鐘重試（{sid}）...")
                        time.sleep(retry_wait)
                        continue
                    break
            if df is not None and not df.empty:
                try:
                    _dump_cache(cache_path, df,
                                meta={"source": "bt_price",
                                      "start": start_s, "end": end_s})
                except Exception:
                    pass
        if df is not None and not df.empty:
            out[sid] = df
    return out


def fetch_inst_history_bulk(dl, stock_ids, start, end, cache_dir=None,
                            retry_wait=3600, max_retries=2) -> dict:
    """逐股抓法人歷史（FinMind，與實盤同資料層），
    聚合為 { date_str: { stock_id: (inst_buy, inst_sell) } }（投信+外資）。

    回測用：2015-2021 等長歷史窗口 TWSE T86 無資料（API 僅提供 2017-12-18 後），
    回測必須用 FinMind（2026-08-25 事故：README 2015-2021 +49.37% 無法重現）。
    快取：每檔獨立 pkl（cache_dir），meta 記錄 start/end — 涵蓋請求範圍才命中。
    FinMind 免費配額 600/hr：遇 402 自動等待 retry_wait 秒後重試（最多 max_retries 次）。
    """
    import time
    start_s, end_s = str(start)[:10], str(end)[:10]
    if cache_dir is None:
        cache_dir = Path("cache/inst_momentum/inst_history")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    out = {}
    for i, sid in enumerate(stock_ids):
        cache_path = cache_dir / f"{sid}.pkl"
        df = None
        if cache_path.exists():
            cached, meta = _load_cache(cache_path)
            if cached is not None and not cached.empty:
                m = meta or {}
                # 請求範圍 ⊆ 快取範圍 → 命中（同 fetch_price_history_bulk）
                if (m.get("start", "") <= start_s and m.get("end", "") >= end_s):
                    df = cached
        if df is None:
            for attempt in range(max_retries + 1):
                try:
                    raw = dl.taiwan_stock_institutional_investors(
                        stock_id=sid, start_date=start_s, end_date=end_s)
                    if raw is not None and not raw.empty:
                        df = _norm_inst(raw)
                    break
                except Exception as e:
                    if "upper limit" in str(e) and attempt < max_retries:
                        print(f"   ⏳ FinMind 配額用盡，等待 {retry_wait/60:.0f} 分鐘重試（{sid}）...")
                        time.sleep(retry_wait)
                        continue
                    break
            if df is not None and not df.empty:
                try:
                    _dump_cache(cache_path, df,
                                meta={"source": "inst_history",
                                      "start": start_s, "end": end_s})
                except Exception:
                    pass
        if df is None or df.empty:
            continue
        agg = aggregate_institutional(df)
        for _, row in agg.iterrows():
            d = row["date"]
            d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            out.setdefault(d_str, {})[sid] = (
                int(row["inst_buy"]), int(row["inst_sell"]))
    return out


class TwseDayCache:
    """TWSE 逐日快取（實盤備援用）：先建立近 N 天快取，之後只補最新一天、淘汰最舊一天。"""

    def __init__(self, max_days: int = 20):
        self._cache = {}
        self._max_days = max_days
        self._built = False

    def ensure_range(self, end_date, lookback_days: int = 15):
        for i in range(lookback_days):
            d = end_date - timedelta(days=i)
            dt_str = d.strftime("%Y%m%d")
            if dt_str not in self._cache:
                day = fetch_twse_day(dt_str)
                if day:
                    self._cache[dt_str] = day
        keys = sorted(self._cache.keys())
        while len(keys) > self._max_days:
            del self._cache[keys.pop(0)]
        if not self._built:
            self._built = True
            print(f"✅ [TWSE] 快取建立 ({len(self._cache)} 天, "
                  f"{sum(len(v) for v in self._cache.values())} 筆)")

    def stock_rows(self, stock_id: str) -> pd.DataFrame:
        """回傳個股在快取內的法人資料：date/stock_id/name/buy/sell（name 為中文）。"""
        rows = []
        for date_str, stocks in self._cache.items():
            if stock_id in stocks:
                d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                for name, data in stocks[stock_id].items():
                    rows.append({"date": d, "stock_id": stock_id, "name": name,
                                 "buy": data["buy"], "sell": data["sell"]})
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df


# ─── 股價 ─────────────────────────────────────────────

def clean_price_df(df: pd.DataFrame) -> pd.DataFrame:
    """剔除價格髒點（close<=0 或 OHLC 全零）。缺失日會使權益估值退回買入價，
    避免單筆零價資料造成回測假崩盤（2025-07-30 鴻海 2317 零價事件）。"""
    bad = (df["close"] <= 0) | ((df["open"] == 0) & (df["high"] == 0) & (df["low"] == 0))
    n = int(bad.sum())
    if n:
        print(f"⚠️  剔除 {n} 筆無效價格（close<=0 或 OHLC 全零）")
    return df[~bad].reset_index(drop=True)


def _norm_price(df: pd.DataFrame) -> pd.DataFrame:
    # 先 rename 再 clean：FinMind raw 欄位是 max/min（非 high/low），
    # clean_price_df 需要 high/low（2026-08-25：回測價格直呼時 KeyError）
    rename = {"Trading_Volume": "volume", "Trading_money": "amount",
              "Trading_turnover": "turnover", "max": "high", "min": "low"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df = clean_price_df(df)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _fetch_price_finmind(dl, stock_id: str, start: str, end: str) -> pd.DataFrame:
    try:
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return _norm_price(df)


def _fetch_price_twse(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """TWSE STOCK_DAY（民國年轉換）。

    STOCK_DAY API 一次只回傳「date 參數所在月份」的資料 → 跨月請求必須逐月迴圈，
    否則只拿到 start 月的最後幾個交易日（2026-08-25 實盤事故：
    120 天請求只回 4 筆 4/27-4/30 → 被當成功寫入快取 → 全池篩選 0/0）。
    """
    try:
        frames = []
        cur = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        while cur <= end_ts:
            dt_str = cur.strftime("%Y%m01")
            url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            params = {"response": "json", "date": dt_str, "stockNo": stock_id}
            resp = requests.get(url, params=params, headers={
                "User-Agent": "Mozilla/5.0",
            }, timeout=10)
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("data"):
                cur = (cur + pd.offsets.MonthBegin(1)).normalize()
                continue
            rows = []
            for row in data["data"]:
                try:
                    parts = row[0].split("/")
                    d = f"{int(parts[0]) + 1911}-{parts[1]}-{parts[2]}"
                    if d < start or d > end:
                        continue
                    rows.append({
                        "date": d, "stock_id": stock_id,
                        "open": float(row[3].replace(",", "")),
                        "high": float(row[4].replace(",", "")),
                        "low": float(row[5].replace(",", "")),
                        "close": float(row[6].replace(",", "")),
                        "volume": int(row[1].replace(",", "")),
                    })
                except (ValueError, IndexError):
                    continue
            if rows:
                frames.append(pd.DataFrame(rows))
            cur = (cur + pd.offsets.MonthBegin(1)).normalize()
        if not frames:
            return pd.DataFrame()
        merged = pd.concat(frames, ignore_index=True)
        if merged.empty:
            return pd.DataFrame()
        return _norm_price(merged)
    except Exception:
        return pd.DataFrame()


MIS_QUOTE_URL = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp'
MIS_INDEX_URL = 'https://mis.twse.com.tw/stock/index.jsp'


def _mis_date_str(raw) -> str:
    """MIS 的 `d` 欄位是 `YYYYMMDD` → `YYYY-MM-DD`（格式不符時回空字串）。"""
    s = str(raw or '')
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return ''


def fetch_intraday_quotes(symbols, timeout: int = 8) -> dict:
    """TWSE MIS 即時報價：`{sym: {'price','date','time'}}`（13:30 後 `price` 即**當日收盤**）。

    為什麼需要（2026-09-16）：`fetch_latest_closes` 走 TWSE STOCK_DAY，該端點**盤後才更新**
    ⇒ 13:45 產生的收盤報告拿到的是**前一個交易日**的收盤價（實測 09-16 報告顯示 09-15 價格）。
    MIS 的 `z`＝最後成交價、`d`＝資料日期，可取得當日收盤。

    - 上市/上櫃都查（`tse_<sym>.tw|otc_<sym>.tw`），取有資料的那筆。
    - `z` 無成交（`-`）時退回昨收 `y`（避免整檔沒有價格）。
    - **任何失敗一律回 `{}`**，由呼叫端退回日線來源，絕不拋例外（報告不能因報價來源掛掉而消失）。
    """
    out = {}
    syms = [str(s) for s in (symbols or [])]
    if not syms:
        return out
    try:
        import requests
        sess = requests.Session()
        sess.headers.update({'User-Agent': 'Mozilla/5.0'})
        try:
            sess.get(MIS_INDEX_URL, timeout=timeout)   # 取 cookie；拿不到通常仍可查
        except Exception:
            pass
        ex_ch = '|'.join(f'tse_{s}.tw|otc_{s}.tw' for s in syms)
        resp = sess.get(MIS_QUOTE_URL, params={'ex_ch': ex_ch, 'json': '1', 'delay': '0'},
                        timeout=timeout)
        payload = resp.json()
    except Exception:
        return out

    for item in (payload.get('msgArray') or []):
        try:
            sym = str(item.get('c') or '').strip()
            if sym not in syms:
                continue
            raw_price = item.get('z')
            if raw_price in (None, '', '-'):
                raw_price = item.get('y')          # 無成交 → 用昨收
            price = float(str(raw_price).replace(',', ''))
            if price <= 0:
                continue
            out[sym] = {'price': price, 'date': _mis_date_str(item.get('d')),
                        'time': str(item.get('t') or '')}
        except Exception:
            continue
    return out


def _fetch_daily_closes_dated(symbols) -> dict:
    """TWSE STOCK_DAY 日收盤：`{sym: {'price','date'}}`。

    抓「本月 + 上個月」兩個月資料取最後一個交易日的收盤價，
    避免月初邊界（當月尚無資料）導致抓不到價格。
    `date` 一律取自**資料本身**的最後一筆交易日（不可用今天代替 —— 端點盤後才更新）。
    個別標的失敗時略過；全部失敗回傳空 dict，由呼叫端自行回退。
    """
    prices = {}
    if not symbols:
        return prices
    today = pd.Timestamp(date.today())
    month_starts = [today.strftime("%Y-%m-01")]
    prev = (today.replace(day=1) - pd.Timedelta(days=1)).replace(day=1)
    month_starts.append(prev.strftime("%Y-%m-01"))
    end_s = today.strftime("%Y-%m-%d")
    for sym in symbols:
        frames = []
        for ms in month_starts:
            try:
                df = _fetch_price_twse(sym, ms, end_s)
            except Exception:
                continue
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            continue
        merged = pd.concat(frames).drop_duplicates("date").sort_values("date")
        merged = merged[merged["close"] > 0]
        if merged.empty:
            continue
        last = merged.iloc[-1]
        prices[sym] = {'price': float(last["close"]),
                       'date': pd.Timestamp(last["date"]).strftime('%Y-%m-%d')}
    return prices


def fetch_latest_closes_dated(symbols) -> dict:
    """最新價＋**價格日期**：`{sym: {'price','date','source'}}`（source＝`mis`／`daily`）。

    順序：**TWSE MIS 當日報價**（盤後＝當日收盤）→ TWSE STOCK_DAY 日線（可能是前一交易日）。
    呼叫端（持倉報告／儀表板）可據 `date` 標示資料日期，避免把前一交易日的價格當成今天的。
    """
    dated = {}
    for sym, q in fetch_intraday_quotes(symbols).items():
        dated[sym] = {'price': q['price'], 'date': q.get('date', ''), 'source': 'mis'}
    missing = [s for s in (symbols or []) if str(s) not in dated]
    if missing:
        for sym, v in _fetch_daily_closes_dated(missing).items():
            dated[str(sym)] = {'price': v['price'], 'date': v.get('date', ''), 'source': 'daily'}
    return dated


def fetch_latest_closes(symbols) -> dict:
    """最新收盤價 `{sym: close}`（既有介面，供儀表板/對帳使用）。

    內部走 `fetch_latest_closes_dated`（先 MIS 當日報價、再日線）。
    """
    return {sym: v['price'] for sym, v in fetch_latest_closes_dated(symbols).items()}



def _fetch_price_yfinance(stock_id: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        tk = yf.Ticker(f"{stock_id}.TW")
        # auto_adjust=False：與 FinMind 一致使用原始價（除權前後不調整）。
        # 舊版用預設(調整後)價會讓快取混入還原價，導致回測訊號/進場價失真
        df = tk.history(start=start, end=end, auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["Date"].dt.date)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                "Close": "close", "Volume": "volume"})
        df = df[["date", "open", "high", "low", "close", "volume"]]
        return _norm_price(df)
    except Exception:
        return pd.DataFrame()


def get_price_data(dl, stock_id: str, start, end, cache_path=None,
                   max_stale_days: int = 5, ref_date=None,
                   sources=("finmind", "twse"), min_start=None) -> tuple:
    """取得個股日 K（date/open/high/low/close/volume）。

    cache_path 提供時做新鮮度檢查（ref_date 與 max_stale_days 可設定）。
    min_start 提供時，快取命中還需覆蓋到該起始日（避免舊快取歷史深度不足，
    導致魚過濾 90 天回溯視窗不完整 — 2026-08 官方數字無法重現事件的根因）。
    回傳 (df, source)，source ∈ cache / finmind / twse / yfinance / none。
    """
    if ref_date is None:
        ref_date = date.today()
    ref_ts = pd.Timestamp(ref_date)

    if cache_path is not None and Path(cache_path).exists():
        df, _meta = _load_cache(cache_path)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            latest = pd.Timestamp(df["date"].max())
            if min_start is not None:
                # 歷史深度檢查：快取最早日期需 ≤ 要求起點。但「股票上市晚於起點」
                # 不算深度不足（2019 上市的股票 2014 本來就無資料）——只拒絕
                # 「快取被截斷」的情形（最早日期遠晚於該股真實上市日）。
                # 判別：快取覆蓋 ≥ 1 年即視為上市晚、允許命中；< 1 年（如 2026-08
                # 事件的 90 天截斷）判定深度不足、重新下載。
                depth_days = (latest - pd.Timestamp(df["date"].min())).days
                span_ok = depth_days >= 365
                start_ok = pd.Timestamp(df["date"].min()) <= pd.Timestamp(min_start)
                if not start_ok and not span_ok:
                    history_ok = False
                else:
                    history_ok = True
            else:
                history_ok = True
            if history_ok and (ref_ts - latest).days <= max_stale_days:
                return _norm_price(df), "cache"

    start_s, end_s = str(start)[:10], str(end)[:10]
    fetchers = {
        "finmind": lambda: _fetch_price_finmind(dl, stock_id, start_s, end_s),
        "twse": lambda: _fetch_price_twse(stock_id, start_s, end_s),
        "yfinance": lambda: _fetch_price_yfinance(stock_id, start_s, end_s),
    }
    for src in sources:
        try:
            df = fetchers[src]()
        except Exception:
            continue
        if df is not None and not df.empty:
            # 新鮮度防護：抓回來的資料若最新日期太舊（距 ref_date 超過
            # max_stale_days），視為殘缺/失敗 — 不採用、不寫入快取。
            # （2026-08-25 事故：TWSE 單月殘缺資料（4 筆）被當成功寫入
            #   快取，之後 5 天每次搜尋都命中殘缺快取 → 全池 0/0）
            latest = pd.Timestamp(df["date"].max())
            if (ref_ts - latest).days > max_stale_days:
                continue
            if cache_path is not None:
                try:
                    _dump_cache(cache_path, df,
                                meta={"stock_id": stock_id, "source": src,
                                      "start": start_s, "end": end_s})
                except Exception:
                    pass
            return df, src
    return pd.DataFrame(), "none"


# ─── 法人買賣 ─────────────────────────────────────────

def _norm_inst(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["name"] = df["name"].replace(FINMIND_INST_NAME_MAP)
    return df


def aggregate_institutional(df: pd.DataFrame) -> pd.DataFrame:
    """投信+外資每日加總 → { date, inst_buy, inst_sell }（core 格式）。"""
    mask = df["name"].isin(["投信", "外資"])
    agg = df[mask].groupby("date").agg(
        inst_buy=("buy", "sum"), inst_sell=("sell", "sum")).reset_index()
    agg["date"] = pd.to_datetime(agg["date"])
    return agg


def get_institutional_data(dl, stock_id: str, start, end, cache_path=None,
                           max_stale_days: int = 5, ref_date=None,
                           sources=("finmind", "twse"),
                           twse_day_cache: TwseDayCache = None) -> tuple:
    """取得個股法人買賣資料（date/stock_id/name/buy/sell，name 為中文）。

    cache_path 提供時做新鮮度檢查（同股價快取）。
    twse_day_cache 提供時，TWSE 備援會走逐日快取避免逐股重複呼叫。
    回傳 (df, source, latest_date)，source ∈ cache / finmind / twse / none。
    """
    if ref_date is None:
        ref_date = date.today()
    ref_ts = pd.Timestamp(ref_date)

    if cache_path is not None and Path(cache_path).exists():
        df, _meta = _load_cache(cache_path)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            latest = pd.Timestamp(df["date"].max())
            if (ref_ts - latest).days <= max_stale_days:
                return _norm_inst(df), "cache", latest.date()

    for src in sources:
        if src == "finmind":
            try:
                df = dl.taiwan_stock_institutional_investors(
                    stock_id=stock_id,
                    start_date=str(start)[:10],
                    end_date=str(end)[:10],
                )
                if df is not None and not df.empty:
                    df = _norm_inst(df)
                    if cache_path is not None:
                        try:
                            _dump_cache(cache_path, df,
                                        meta={"stock_id": stock_id, "source": "finmind",
                                              "start": str(start)[:10], "end": str(end)[:10]})
                        except Exception:
                            pass
                    return df, "finmind", pd.Timestamp(df["date"].max()).date()
            except Exception:
                pass
        elif src == "twse":
            if twse_day_cache is None:
                continue
            start_dt = pd.Timestamp(start).date()
            end_dt = pd.Timestamp(end).date()
            twse_day_cache.ensure_range(end_dt, lookback_days=(end_dt - start_dt).days + 5)
            df = twse_day_cache.stock_rows(stock_id)
            if not df.empty:
                # TWSE 備援結果也寫入個股快取，避免每天重試/降級警示每天重發
                # （2026-08-25：FinMind 配額用盡 → 15 檔走備援但不落盤）
                if cache_path is not None:
                    try:
                        _dump_cache(cache_path, df,
                                    meta={"stock_id": stock_id, "source": "twse",
                                          "start": str(start)[:10], "end": str(end)[:10]})
                    except Exception:
                        pass
                return df, "twse", pd.Timestamp(df["date"].max()).date()
    return pd.DataFrame(), "none", None


# ─── 選股池 ───────────────────────────────────────────

def get_all_stock_ids(dl, n: int, exclude_etf: bool = True, mcap_file=None) -> list:
    """市值前 N 選股池（與回測一致）。

    `mcap_file` 存在時優先使用市值排名；**讀不到就退回 stock_id 排序，但要留下警告**。
    ⚠️ 2026-09-18 修：原本用裸 `pickle.loads` 讀 → 遇到 v2 格式（`dump_cache` 寫的
    `{"schema_version":2,"data":[...]}`）會得到空池，然後**無聲退回 stock_id 排序**
    （≈ 按代號取前 N 檔＝一堆老牌冷門股），選股結果全錯卻沒有任何訊息。
    改用共用的 `read_ranking_codes()`（三種格式都吃），並在「檔案在、卻讀不出東西」時出聲。
    """
    if mcap_file is not None and Path(mcap_file).exists():
        from core.cache_io import read_ranking_codes
        ranked = read_ranking_codes(mcap_file)
        if exclude_etf:
            ranked = [s for s in ranked if not s.startswith("0")]
        if ranked:
            return ranked[:n]
        print(f"⚠️  市值排名讀不出任何代號（{mcap_file}）→ 退回 stock_id 排序的替代池，"
              f"結果不可信，請先重建 ranking（scripts/rebuild_mcap_ranking.py）")
    df = dl.taiwan_stock_info()
    df = df[df["type"] == "twse"]
    ids = [s.strip() for s in df["stock_id"]
           if s.strip().isdigit() and len(s.strip()) == 4]
    if exclude_etf:
        ids = [s for s in ids if not s.startswith("0")]
    return sorted(set(ids))[:n]
