#!/usr/bin/env python3
"""
stock_selector_grid.py — 選股共用函式庫（資料載入／特徵／評分）

⚠️ 本專案（自選股）已移除母專案的季度換股回測與 Grid Search 引擎，只保留被
   `monthly_rebalance_picker.py` 與 `backtest_plan2_monthly_3group.py` 共用的部分：
     · load_stock() / load_twse_inst_merged() — 日線與法人資料（含快取）
     · score_stock() — 綜合評分（動能／技術面／穩定度／催化）
     · DEFAULT_PARAMS、COMMISSION_RATE、ETF_TAX、tax_rate()、_snap_date()
   選股入口：python scripts/monthly_rebalance_picker.py --risk normal
"""
import os
import sys

# ⚠️ sys.path 必須在 `from core...` **之前**：以 `python 工具腳本` 執行時
# sys.path[0] 是 scripts/（不是 CWD）⇒ 下面那行 import 會 ModuleNotFoundError。
# 容器內因為 image 設了 PYTHONPATH=/app 才沒事（2026-09-14 修）。
# ⚠️ 專案根：`python -`（stdin）時 __file__ 是 '<stdin>'（**不是未定義**），
#    abspath 會推成 '<CWD>/<stdin>' ⇒ dirname 再多退一層 → 路徑全錯
#    （實測 2026-09-14：stdin 執行時 CAP_RANKING 變成 '/cache/...' 不存在 ⇒ 候選池為空
#     ⇒ 舊碼掉進 range(1101,9999) 假池 ⇒ 狂抓 ~8900 檔把 VM 打掛）。一律用 CWD。
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

# ⚠️ `.env` 必須在**任何模組層 `os.getenv` 之前**載入，且一律以「檔案」為準（override=True）。
#   2026-10-23 修：`STOCK_NO`／`MIN_DAILY_AMOUNT`／`LOOKBACK_DAYS` 原本在
#   L49–L120 就讀 env，而本段卻寫在 L142 ⇒ **在本機直接跑 selector** 時候選池退回預設
#   「市值前 50」（不是 `.env` 的 `STOCK_NO=100`）⇒ 選出的檔數與 VM 可能不同
#   （重現 2026-10-17 B 腿選股時實測：50 檔池看不到當天第 1/4/5 名的 6213／1303／2492）。
#   容器內看不出來：docker-compose `env_file` 建容器時就注入 process env；而
#   先 `load_dotenv()` 才叫子程序時不受影響 ⇒ 只有「本機直接跑」會踩。
#   測試：`test/test_selector_env_order.py`。
#   為何 override=True（2026-10-01 實測）：容器用 `env_file` 在**建立容器時**把變數注入
#   process env，之後主機上改 `.env` 不會更新既有的 process env；而 python-dotenv 預設
#   `override=False` ⇒ `docker exec` 跑的工具（picker／selector／報表…）會讀到
#   **容器啟動當時**的舊值。主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`
#   （V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)

import numpy as np
import pandas as pd

import yfinance as yf

from core.cache_io import load_cache, dump_cache, load_cache_or_raw

# ── 候選股票池（市值前 N 大） ─────────────────────────
STOCK_NO = int(os.getenv("STOCK_NO", "50"))  # 候選池：市值前 N 大
MIN_DAILY_AMOUNT = float(os.getenv("MIN_DAILY_AMOUNT", "0"))  # 日均成交額門檻（萬元，0=不啟用）
CAP_RANKING = os.path.join(_ROOT, "cache", "inst_momentum", "mcap_ranking.pkl")


def build_candidate_pool(ranked, stock_no):
    """由市值排名挑出候選池（4 位數代號、前 stock_no 檔）。

    容忍兩種歷史格式：**list**（新）與 **dict 包裝**（舊 payload，取 `data`）。
    取不到就回空 list —— 由呼叫端**明確中止**，不要亂猜。
    """
    if isinstance(ranked, dict):
        for key in ("data", "ranking", "symbols"):
            if isinstance(ranked.get(key), (list, tuple)):
                ranked = ranked[key]
                break
        else:
            return []
    if not isinstance(ranked, (list, tuple)):
        return []
    return [str(s) for s in ranked if str(s).isdigit() and len(str(s)) == 4][:int(stock_no)]


CANDIDATE_POOL = []
if os.path.exists(CAP_RANKING):
    _ranked, _ = load_cache_or_raw(CAP_RANKING)
    CANDIDATE_POOL = build_candidate_pool(_ranked, STOCK_NO)
if not CANDIDATE_POOL:
    # ⚠️ 2026-09-14 修：原本這裡退回 `range(1101, 9999)`（~8,900 個不存在或極冷門的代號）
    # ⇒ 會**狂抓 yfinance**（實測把 VM 打到 SSH 都連不上）而且**選出垃圾**。
    # 讀不到市值排名是「環境/資料問題」，必須**大聲失敗**，不可以靜默用假池。
    # 2026-10 拆專案時再修：硬失敗移到 `require_candidate_pool()`，**import 時只警告**
    #   —— 否則連「只是想 import 來跑單元測試」都會 SystemExit（且 monthly_rebalance_picker
    #   走的是歷史股本池，根本不需要這份排名）。
    print(f"⚠️ 尚未建立市值排名快取：{CAP_RANKING}")
    print(f"   需要『當期市值前 N 大候選池』的工具請先跑："
          f"python scripts/rebuild_mcap_ranking.py （或 scripts/verify_cache.py 檢查快取）")


def require_candidate_pool():
    """需要候選池的入口請先呼叫這支：沒有排名就**大聲中止**（不可靜默用假池）。"""
    if not CANDIDATE_POOL:
        print(f"❌ 無法取得候選池（市值排名讀不到或格式不符）：{CAP_RANKING}")
        print(f"   請先跑 python scripts/rebuild_mcap_ranking.py，或用 scripts/verify_cache.py 檢查快取")
        raise SystemExit(3)
    return CANDIDATE_POOL

POOL_LABELS = {}
# 股票名稱：**先讀本地快取、再打 FinMind**。
# 為何要本地快取（2026-09-18）：FinMind 免費層 600 req/hr，跑連續回測／報表會被限流
# ⇒ `taiwan_stock_info()` 失敗 ⇒ 報表上的股票名稱整排空白（代號還在，但可讀性差）。
# 快取檔：cache/stock_names.pkl（{代號: 名稱}，經 core.cache_io）。
_NAME_CACHE = os.path.join(_ROOT, "cache", "stock_names.pkl")
try:
    _cached_names, _ = load_cache_or_raw(_NAME_CACHE)
    if isinstance(_cached_names, dict):
        POOL_LABELS.update({str(k): str(v) for k, v in _cached_names.items()})
except Exception:
    pass
try:
    from FinMind.data import DataLoader as _DL
    _dl = _DL()
    _info = _dl.taiwan_stock_info()
    _fresh = {}
    for _, _r in _info.iterrows():
        _sid = str(_r["stock_id"]).strip()
        if _sid.isdigit() and len(_sid) == 4:
            _fresh[_sid] = _r["stock_name"]
    if _fresh:
        POOL_LABELS.update(_fresh)
        try:
            dump_cache(_NAME_CACHE, dict(POOL_LABELS),
                       meta={"source": "FinMind_TaiwanStockInfo", "count": len(POOL_LABELS)})
        except Exception:
            pass
except Exception:
    pass

START_DATE = "2022-01-01"
END_DATE = "2025-12-31"
# 實盤選股只需近期資料（動能 63 日 + MA60 足夠）。VM 實盤可設 SELECTOR_LOOKBACK_DAYS=250 減少下載量。
LOOKBACK_DAYS = int(os.getenv("SELECTOR_LOOKBACK_DAYS", "0"))  # 0=用 START_DATE 完整期間（回測用）

# ══════════════════════════════════════════════════════════════
# 資料載入
# ══════════════════════════════════════════════════════════════

_cache = {}
_PRICE_CACHE_DIR = os.path.join(_ROOT, "cache", "selector_prices")

# ─── 法人籌碼資料（B 方案：法人確認濾網）────────────────────
# 全市場 TWSE 法人資料快取：cache/inst_momentum/{2015,2022}/twse_inst_*.pkl
# 2015 目錄: 2017-12-18~2021-12-30（908 檔/日）| 2022 目錄: 2022-01-03~2026-07-30（FULL）
# 合併後覆蓋 2017-12-18 ~ 2026-07-30；2015-2017 前段無法人資料 → 該期間確認濾網 pass-through
_INST_CACHE_GLOB = os.path.join(_ROOT,
                                "cache", "inst_momentum", "*", "twse_inst_*.pkl")

# `.env` 的載入已移到檔案最上方（必須早於所有模組層 `os.getenv`，2026-10-23）。
_inst_merged = None


def load_twse_inst_merged(refresh_live: bool = False, as_of=None) -> dict:
    """合併全部全市場法人快取 → {date_str: {sid: (inst_buy, inst_sell)}}（投信+外資）。

    只合併「全市場」快取（單日 > 300 檔）；150 檔池子版（法人動能回測用）不混入，
    避免候選池外的股票被誤判為「無法人資料」。回傳 dict 以 module 層快取。
    refresh_live=True 時（實盤選股）：快取落後 > 3 個交易日就補抓缺失交易日；
    **快取為空時會 bootstrap**（回補最近 `days` 個交易日）。補抓結果會寫回
    `cache/inst_momentum/live/twse_inst_*.pkl`，下次不必重抓。
    """
    global _inst_merged
    if _inst_merged is not None:
        return _inst_merged
    import glob as _glob
    from core.cache_io import load_cache_or_raw
    merged = {}
    files = sorted(_glob.glob(_INST_CACHE_GLOB))
    for f in files:
        try:
            data, _meta = load_cache_or_raw(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # 判斷是否全市場：取前 3 個交易日樣本，單日檔數 > 300 才算
        sample_days = [d for d in data if isinstance(d, str)][:3]
        if not sample_days:
            continue
        if max(len(data[d]) for d in sample_days if isinstance(data.get(d), dict)) <= 300:
            continue
        for d, stocks in data.items():
            if not isinstance(d, str) or not isinstance(stocks, dict):
                continue
            day = {}
            for sid, val in stocks.items():
                sid = str(sid).strip()
                if isinstance(val, (tuple, list)) and len(val) >= 2:
                    day[sid] = (int(val[0]), int(val[1]))
            if day:
                merged[d] = day
    print(f"📥 法人資料合併完成: {len(merged)} 交易日（全市場快取）")
    if refresh_live:
        merged = _refresh_inst_live(merged, as_of=as_of)
    _inst_merged = merged
    return merged


def _refresh_inst_live(merged: dict, as_of=None, days: int = 45) -> dict:
    """實盤用：以 TWSE T86 補抓缺失交易日；**快取為空時 bootstrap**，並寫回快取。

    2026-10-26 修正三個實務缺陷：
      ① 原本 `if not merged: return merged` ⇒ 新環境（沒有任何 twse_inst 檔）永遠回
         0 交易日，法人確認等於 pass-through。
      ② 補抓只存在記憶體（docstring 說「寫回快取」但沒實作）⇒ 每次執行都重抓。
      ③ 單日抓取無重試/退避 ⇒ 一遇 TWSE 反爬就整批失敗。
    """
    import time as _time
    from core.inst_data import TwseBlockedError, fetch_twse_day

    end = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now()
    end = end.normalize()
    if merged:
        latest = max(pd.Timestamp(d) for d in merged)
        if (end - latest).days <= 3:
            return merged
        start = latest + pd.Timedelta(days=1)
    else:
        start = end - pd.Timedelta(days=max(days * 2, 90))
    biz = [d for d in pd.bdate_range(start.normalize(), end) if d.weekday() < 5]
    todo = [d for d in biz if d.strftime("%Y-%m-%d") not in merged][-days:]

    added = {}
    for d in todo:
        day = None
        for attempt in range(3):
            try:
                day = fetch_twse_day(d.strftime("%Y%m%d"))
                break
            except TwseBlockedError:
                _time.sleep(1.5 * (attempt + 1))
            except Exception as _e:
                print(f"⚠️ 法人資料 {d:%Y-%m-%d} 抓取失敗：{_e}")
                break
        if not day:
            continue
        added[d.strftime("%Y-%m-%d")] = {
            sid: (v["外資"]["buy"] + v["投信"]["buy"], v["外資"]["sell"] + v["投信"]["sell"])
            for sid, v in day.items()
        }

    if added:
        merged.update(added)
        print(f"📥 TWSE 法人資料補抓: +{len(added)} 交易日（{min(added)} ~ {max(added)}）")
        _persist_inst_live(added)
    elif not merged:
        print("⚠️ 法人資料快取是空的且補抓失敗（TWSE 反爬／無交易日）⇒ 法人確認本次 pass-through")
    return merged


def _persist_inst_live(added: dict) -> None:
    """把補抓到的**全市場**法人資料寫回快取：`cache/inst_momentum/live/twse_inst_<起>_<迄>.pkl`。"""
    if not added:
        return
    days = sorted(added)
    if max(len(added[d]) for d in days) <= 300:
        print("⚠️ 法人資料筆數不足（非全市場）⇒ 不寫快取")
        return
    out_dir = os.path.join(_ROOT, "cache", "inst_momentum", "live")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"twse_inst_{days[0]}_{days[-1]}.pkl")
    dump_cache(path, added, meta={"source": "TWSE_T86", "dates": len(added)})
    print(f"💾 已寫入法人資料快取：{os.path.relpath(path, _ROOT)}")


def inst_net_buy(inst_data: dict, sid: str, end_date, days: int = 21) -> float:
    """選股日前 N 個交易日的法人累計淨買超（投信+外資，張數）。

    只使用 ≤ end_date 的資料（無前瞻）。該股在期間無資料時回傳 None（表未知）。
    """
    sid = str(sid)
    end_ts = pd.Timestamp(end_date)
    dates = sorted(d for d in inst_data if pd.Timestamp(d) <= end_ts)
    if not dates:
        return None
    recent = dates[-days:]
    total = 0.0
    found = False
    for d in recent:
        row = inst_data[d].get(sid)
        if row is not None:
            total += row[0] - row[1]
            found = True
    return total if found else None

def _drop_nan_rows(df):
    """丟掉沒有可用收盤價的列（close 為 NaN 或 ≤ 0）。

    ⚠️ 2026-09-18 實測事故：yfinance 對**最新交易日**會回傳「只有 volume、OHLC 全 NaN」
    的半成品 K 棒（當天 500/500 檔的 2026-09-17 全是），而 `ensure_fresh()` 會把它附加進快取
    ⇒ 快取最後一列（＝選股基準日）是 NaN ⇒ `score_stock()` 全變 NaN ⇒ 排序失效 ⇒ 亂選
    （實測選出 2317/2881/2882，total 全是 NaN）。這裡是**消費者端**防護，
    連已經躺在快取裡的舊 NaN 列一併擋掉（source 端另有 `core.price_append.drop_unusable_rows`）。
    只影響含 NaN 的資料；歷史回測（無 NaN）結果不變。
    """
    if df is None or getattr(df, "empty", True) or "close" not in df.columns:
        return df
    return df[df["close"].notna() & (df["close"] > 0)]


def load_stock(symbol: str) -> pd.DataFrame:
    if symbol in _cache:
        return _cache[symbol]
    # 磁碟快取：先讀 pkl，避免每次重新下載
    pkl_path = os.path.join(_PRICE_CACHE_DIR, f"{symbol}.pkl")
    if os.path.exists(pkl_path):
        df, _ = load_cache(pkl_path)
        df = _drop_nan_rows(df)
        if df is not None and not df.empty:
            _cache[symbol] = df
            return df
    yf_sym = f"{symbol}.TW" if symbol.isdigit() else f"{symbol}.TW"
    if LOOKBACK_DAYS > 0:
        from datetime import date as _date, timedelta as _td
        start = (_date.today() - _td(days=LOOKBACK_DAYS)).isoformat()
        df = yf.download(yf_sym, start=start, end="2026-12-31", auto_adjust=True, progress=False)
    else:
        df = yf.download(yf_sym, start=START_DATE, end="2026-12-31", auto_adjust=True, progress=False)
    if df.empty:
        _cache[symbol] = df
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    df = _drop_nan_rows(df)
    # 寫入磁碟快取
    try:
        os.makedirs(_PRICE_CACHE_DIR, exist_ok=True)
        dump_cache(pkl_path, df, meta={"symbol": symbol, "source": "yfinance"})
    except Exception:
        pass
    _cache[symbol] = df
    return df


def load_all_stocks(pool=None):
    if pool is None:
        pool = CANDIDATE_POOL
    data = {}
    for sym in pool:
        df = load_stock(sym)
        if not df.empty:
            data[sym] = df
    return data


# ── 交易成本 ──
ETF_STOCKS = {"0050","0056","006208","00878","00646","00632R"}
COMMISSION_RATE = 0.001425
STOCK_TAX = 0.003
ETF_TAX = 0.001
def tax_rate(sym): return ETF_TAX if sym in ETF_STOCKS else STOCK_TAX


# ══════════════════════════════════════════════════════════════
# 技術指標（僅用截至當前日期的資料）
# ══════════════════════════════════════════════════════════════

def trailing_ret(df, end_date, days):
    if end_date not in df.index:
        return None
    idx = df.index.get_loc(end_date)
    start_idx = max(0, idx - days)
    sp = float(df.iloc[start_idx]["close"])
    ep = float(df.iloc[idx]["close"])
    if sp <= 0:
        return None
    return (ep - sp) / sp


def ma_position(df, end_date, days=20):
    """股價在均線上方/下方，回傳偏離 %"""
    if end_date not in df.index:
        return None
    idx = df.index.get_loc(end_date)
    start = max(0, idx - days)
    ma = float(df.iloc[start:idx+1]["close"].mean())
    cp = float(df.iloc[idx]["close"])
    if ma <= 0:
        return None
    return (cp - ma) / ma


def volatility(df, end_date, days=63):
    if end_date not in df.index:
        return None
    idx = df.index.get_loc(end_date)
    start = max(0, idx - days)
    prices = df.iloc[start:idx+1]["close"].values
    if len(prices) < 5:
        return None
    return float(np.std(prices / np.mean(prices)))


# ══════════════════════════════════════════════════════════════
# 潛力股模式評分（從 find_catalyst_stocks.py 萃取）
# ══════════════════════════════════════════════════════════════

def catalyst_score(df, end_date):
    """
    模仿 find_catalyst_stocks.py 的「長期盤整→近期突破」評分。
    只使用截至 end_date 的價格與成交量資料，無外部 API。

    回傳 dict: { stable_score, breakout_score, volume_score, catalyst_total }
    或 None（資料不足時）。
    """
    n_required = 130  # 約半年交易日
    if end_date not in df.index:
        return None
    idx = df.index.get_loc(end_date)
    if idx < n_required:
        return None

    start_idx = idx - n_required
    mid = start_idx + n_required // 2

    prices = df.iloc[start_idx:idx+1]["close"].values
    volumes = df.iloc[start_idx:idx+1]["volume"].values

    # === 前半段（盤整偵測）===
    fh_p = prices[:n_required//2]
    fh_mean = np.mean(fh_p)
    fh_min = np.min(fh_p)
    fh_max = np.max(fh_p)
    fh_range_pct = (fh_max - fh_min) / fh_mean * 100 if fh_mean > 0 else 999

    # === 後半段（突破偵測）===
    sh_p = prices[n_required//2:]
    current_price = float(prices[-1])
    pct_above_fh_high = (current_price - fh_max) / fh_max * 100 if fh_max > 0 else 0
    pct_above_fh_mean = (current_price - fh_mean) / fh_mean * 100 if fh_mean > 0 else 0

    # 量能變化
    fh_vol = np.mean(volumes[:n_required//2]) if n_required//2 > 0 else 1
    sh_vol = np.mean(volumes[n_required//2:]) if len(volumes) > n_required//2 else fh_vol
    vol_ratio = sh_vol / fh_vol if fh_vol > 0 else 1.0

    # 近期動能
    recent_20d = prices[-20:] if len(prices) >= 20 else prices
    recent_60d = prices[-60:] if len(prices) >= 60 else prices
    chg_20d = (recent_20d[-1] - recent_20d[0]) / recent_20d[0] * 100 if recent_20d[0] > 0 else 0
    chg_60d = (recent_60d[-1] - recent_60d[0]) / recent_60d[0] * 100 if recent_60d[0] > 0 else 0

    # 評分（對應 find_catalyst_stocks.py calculate_score）
    # 1. 盤整品質 (0~1): 波動越小越高
    s_stable = max(0, 1 - fh_range_pct / 40)

    # 2. 突破力道 (0~1): 突破幅度越大越高
    if pct_above_fh_mean > 0:
        s_breakout = min(pct_above_fh_mean / 80, 1.0)
        if pct_above_fh_mean > 30:
            s_breakout *= 1.2
        s_breakout = min(s_breakout, 1.0)
    else:
        s_breakout = 0

    # 3. 量能確認 (0~1): 後半段量 / 前半段量
    s_volume = min(vol_ratio / 5, 1.0) if vol_ratio > 1.0 else vol_ratio * 0.2

    # 4. 動能延續性輔助（近60日上漲趨勢加分）
    s_momentum_aux = min(max(0, chg_60d) / 50, 1.0)

    # 綜合（權重對應原本 find_catalyst_stocks.py 的 0.2/0.3/0.15/0.25/0.1）
    cat_total = (s_stable * 0.20 + s_breakout * 0.35 + s_volume * 0.15 + s_momentum_aux * 0.30)

    return {
        "stable_score": float(s_stable),
        "breakout_score": float(min(s_breakout, 1.0)),
        "volume_score": float(min(s_volume, 1.0)),
        "mom_aux_score": float(s_momentum_aux),
        "cat_total": float(cat_total),
        "stable_range_pct": float(fh_range_pct),
        "pct_above_high": float(pct_above_fh_high),
        "pct_above_mean": float(pct_above_fh_mean),
        "vol_ratio": float(vol_ratio),
        "chg_20d": float(chg_20d),
        "chg_60d": float(chg_60d),
    }


# ══════════════════════════════════════════════════════════════
# 選股評分函數（參數可調）
# ══════════════════════════════════════════════════════════════

# 快取 catalyst 分數（stock, date_str → score dict）
_catalyst_cache = {}

def score_stock(sym, df, end_date, params):
    """
    給一檔股票打分（只用截至 end_date 的資訊）
    params 字典:
      - momentum_days: 動能回看天數 (21/63/125)
      - momentum_weight: 動能權重
      - technical_weight: 技術面權重（均線位置）
      - stability_weight: 穩定性權重（低波動加分）
      - catalyst_weight: 潛力股模式評分權重（盤整→突破）
      - use_ma_filter: 是否要求股價站上 MA20
      - min_price: 最低股價門檻
    """
    m_days = params.get("momentum_days", 63)
    m_w = params.get("momentum_weight", 1.0)
    t_w = params.get("technical_weight", 0.5)
    s_w = params.get("stability_weight", 0.3)
    c_w = params.get("catalyst_weight", 0.0)
    use_ma = params.get("use_ma_filter", False)
    min_px = params.get("min_price", 5)

    if end_date not in df.index:
        return None

    cp = float(df.loc[end_date, "close"])
    if cp < min_px:
        return None

    if MIN_DAILY_AMOUNT > 0:
        idx = df.index.get_loc(end_date)
        start_i = max(0, idx - 20)
        window = df.iloc[start_i:idx + 1]
        avg_vol = window["volume"].mean()
        avg_amount_wan = (avg_vol * 1000 * cp) / 10000.0
        if avg_amount_wan < MIN_DAILY_AMOUNT:
            return None

    # 動能分數（支援雙動能: momentum_days 為主, momentum2_days/weight 為輔）
    m_ret = trailing_ret(df, end_date, m_days)
    if m_ret is None:
        return None

    if use_ma:
        ma20_pos = ma_position(df, end_date, 20)
        if ma20_pos is None or ma20_pos < 0:
            return None

    # 技術面分數：離 MA20 越近越好（正偏離獎勵）
    ma20_pct = ma_position(df, end_date, 20) or 0
    ma60_pct = ma_position(df, end_date, 60) or 0
    tech_score = (max(0, ma20_pct) * 0.6 + max(0, ma60_pct) * 0.4)

    # 穩定度：波動越低分數越高
    vol = volatility(df, end_date)
    stability = 1.0 / (vol + 0.05) if vol else 0

    # 潛力股模式評分（快取）
    cache_key = (sym, end_date.strftime("%Y-%m-%d"))
    if cache_key not in _catalyst_cache:
        _catalyst_cache[cache_key] = catalyst_score(df, end_date)
    cat = _catalyst_cache[cache_key]
    cat_val = cat["cat_total"] if cat else 0

    # 綜合（雙動能: momentum2 加權獨立於 momentum_weight）
    m2_days = params.get("momentum2_days", None)
    m2_term = 0.0
    if m2_days:
        m2_ret = trailing_ret(df, end_date, m2_days)
        m2_term = max(0, m2_ret) * params.get("momentum2_weight", 1.0)
    total = (max(0, m_ret) * m_w + m2_term + tech_score * t_w + stability * s_w * 0.01 + cat_val * c_w)

    return {
        "symbol": sym,
        "close": cp,
        "momentum": m_ret,
        "tech_score": tech_score,
        "stability": stability,
        "catalyst": cat_val,
        "cat_stable": cat["stable_score"] if cat else 0,
        "cat_breakout": cat["breakout_score"] if cat else 0,
        "cat_volume": cat["volume_score"] if cat else 0,
        "total": total,
        "ma20_pct": ma20_pct,
        "ma60_pct": ma60_pct,
        "vol": vol,
    }


# ── 候選股剔除濾網（2026-09-12 新增；**預設空 = 生產行為完全不變**）──────────
# 每個元素是 callable(symbol, df, end_date) -> True 表示「剔除這檔候選」。
# 由回測／分析腳本注入（**同一份程式碼也供實盤 `--recommend` 使用**，故預設必須為空）。
# 語意：濾網在**排序前**剔除 → 由下一名遞補、維持滿倉 topN
#      （不是選完才丟掉留現金 —— 那改變的是曝險，不是選股）。
# 用法（分析腳本可注入）：
#     ssg.candidate_filters = [my_filter]      # 實驗中
#     ssg.candidate_filters = []               # 還原
candidate_filters = []


# ══════════════════════════════════════════════════════════════
# 季度回測
# ══════════════════════════════════════════════════════════════


def _snap_date(df, target):
    """將日期對齊到 df 中 <= target 的最後交易日"""
    if target in df.index:
        return target
    avail = df[df.index <= target].index
    if len(avail) > 0:
        return avail[-1]
    # 沒有更早的日期，用第一個交易日
    return df.index[0] if len(df.index) > 0 else None


# ══════════════════════════════════════════════════════════════
# TWO_BY_TWO 策略回測 — Group 1
# ══════════════════════════════════════════════════════════════


DEFAULT_PARAMS = {
    "momentum_days": 21,
    "momentum_weight": 2.0,
    "technical_weight": 0.3,
    "stability_weight": 0.5,
    "catalyst_weight": 0.0,
    "auto_momentum": 1,
    "use_ma_filter": True,
    "min_price": 5,
}


# ══════════════════════════════════════════════════════════════
# 推薦輸出
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# HTML 報告
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════
