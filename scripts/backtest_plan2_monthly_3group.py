"""方案二改「每月換股」+ 三組獨立選股策略回測（2022-2025, NT$500,000 單筆）— 訊號執行版

用法: python scripts/backtest_plan2_monthly_3group.py
環境覆寫: START END POOL_N TOP_N INITIAL MIN_PRICE MOM_DAYS

設計（誠實、無事後之明、依使用者修正）:
- 候選池 = 誠實池：每季以「當時市價 × 歷史股本」重建當時市值前 POOL_N 大（無倖存者偏差）。
- 每月換股：月初選股（僅用「上個月最後交易日」及以前資料），
  **選定即買入**（等權分配當下可用資金）；持股「依策略訊號進出」——
  賣出訊號(-1) 才會出場，**不做月底強制平倉**。
- 月內賣出空出的資金回到該股 bucket；當月被剔除（deselect）的股票的 bucket 併回現金池，
  於**下個月重新選股**時分配給新選標的。
- 三組 = 三套獨立選股規則（各有不同策略池），各跑一次完整回測。
- 計入交易成本：手續費 0.1425% + 證交稅 0.3%（ETF 0.1%）。
- 每月最多 TOP_N 檔（預設 5，≤10 限制內）。
"""
import os, sys, json as _json, math
# 專案根：**不要寫死作者的家目錄**（container 內是 /app，沒有 /home/frank/...）
# 2026-09-22 修：原本 `sys.path.insert(0, "/home/frank/tw-autotrader")` ＋ `os.chdir(...)`，
#   在本機能跑、在 container 內直接 ModuleNotFoundError／FileNotFoundError
#   （`docker exec tw_selfselect_bot python scripts/monthly_rebalance_picker.py` 必炸）。
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.isdir(_ROOT):
    os.chdir(_ROOT)
# ⚠️ 環境變數覆寫保護（2026-10-05 事故的同一類問題）：
#   `scripts/stock_selector_grid` 在 **import 時**執行 `load_dotenv(override=True)`
#   （為了讓 docker exec 的工具讀到現行 `.env`）⇒ 會**蓋掉呼叫端傳入的環境變數**。
#   症狀：`POOL_N=50 python scripts/backtest_plan2_monthly_3group.py` 卻仍用 `.env` 的值，
#   表面上完全看不出來（數字漂亮、無錯誤訊息）。⇒ 先快照、import 後再套回。
from core.backtest_rules import snapshot_env_overrides, apply_env_overrides, strategy_after_exit  # noqa: E402
_ENV_OVERRIDES = snapshot_env_overrides()

import pandas as pd, numpy as np
from core.cache_io import load_cache_or_raw
from core.candidate_pool import build_quarterly_pool
import scripts.stock_selector_grid as ssg   # noqa: E402  ← 這個 import 會載入 .env

apply_env_overrides(_ENV_OVERRIDES)          # 明確指定的 env > .env（.env 只當預設來源）
from strategies.bollinger import bollinger_reverse_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.breakout import breakout_strategy

START = os.getenv("START", "2022-01-01")
END = os.getenv("END", "2025-12-31")
POOL_N = int(os.getenv("POOL_N", "100"))
TOP_N = int(os.getenv("TOP_N", "5"))
INITIAL = float(os.getenv("INITIAL", "500000"))
DCA_MONTHLY = float(os.getenv("DCA_MONTHLY", "0"))  # >0 = 每月定額(方案一)；0 = 一筆資金(方案二/預設)
MIN_PRICE = float(os.getenv("MIN_PRICE", "5"))
MOM_DAYS = int(os.getenv("MOM_DAYS", "63"))
COMMISSION = ssg.COMMISSION_RATE
# ── 方案三濾網（可選）──────────────────────────────────
INST_CONFIRM = os.getenv("INST_CONFIRM", "1") == "1"   # 法人確認：近 N 日法人淨買超 > 0 才入選
INST_DAYS = int(os.getenv("INST_DAYS", "15"))
MIN_DRAW_BACK = float(os.getenv("MIN_DRAW_BACK", "30"))  # 股災防護：選股日總回撤 > N% 則該月不換股（續抱）
MDB_UNLIMITED = os.getenv("MDB_UNLIMITED", "0") == "1"   # 1=無限延長(>門檻就一直續抱)；0=最多延長一輪
STRAT_MODE = os.getenv("STRAT_MODE", "group")            # group=策略綁組別；form=依個股型態自適應(四種開放)
# LOCK_AT：auto 策略的「鎖定時點」（只作用 STRAT_MODE=form）
#   fill      = 進場成交當天鎖定（**預設，與實盤一致**：監控期每日重路由決定買訊、買入即鎖定）
#   selection = 選股日就鎖定（2026-09-18 前的舊口徑；實盤從未這樣做）
# ⚠️ 兩者不是「誰對誰錯」而是**規則不同**，勝負隨期間改變 ⇒ 要用它當生產規則前必須多期間驗證
#   （實測：2025-09~2026-09 正常組 selection +117.47% > fill +92.06%；但見下方 A/B 結論）
LOCK_AT = os.getenv("LOCK_AT", "fill")
SWAP_MODE = os.getenv("SWAP_MODE", "full")               # full=每月掉出前N就賣(現狀)；addonly=只依訊號出場、不強賣仍持的(C)
EXEC = os.getenv("EXEC", "immediate")                    # immediate=選股日立即買(A)；signal=等進場訊號才買(自選股/B, 等訊號)
# ── 人工降溫（過熱過濾，2026-09-06 新增）──────────────────
OVERHEAT = os.getenv("OVERHEAT", "1") == "1"             # 1=啟用過熱過濾(近52週高/YTD/高PE)；0=關(對照用)
OH_MAX_FROM_HIGH = float(os.getenv("MAX_PCT_FROM_HIGH", "7"))  # 距52週高點≤此%＝貼近52週高
OH_MAX_YTD = float(os.getenv("MAX_YTD_GAIN", "100"))          # YTD漲幅>此%＝過大
OH_MAX_PER = float(os.getenv("MAX_PER", "45"))                # 本益比>此值＝明顯偏高
OH_MIN_COUNT = max(1, min(3, int(os.getenv("MIN_OVERHEAT", "2"))))  # 1=任一 / 2=≥2(預設) / 3=三項全中『且』
OH_USE_PER = os.getenv("OVERHEAT_USE_PER", "1") == "1"    # 1=用FinMind P/E(慢/限流)；0=僅價量(近52週高+YTD)
MEGA_N = int(os.getenv("MEGA_N", "20"))                   # 權值股動能組：取當時市值前 N 大(權值股)範圍
# ── 過熱進場→自適應緊離場（2026-09-06 新增）─────────────────
HOT_EXIT = os.getenv("HOT_EXIT", "0") == "1"             # 1=過熱入場的持股用目標+移動停損提前落袋
HOT_TP_PCT = float(os.getenv("HOT_TP_PCT", "0"))          # 過熱入場：達 +此% 即(獲利目標)落袋；0=停用
HOT_TRAIL_PCT = float(os.getenv("HOT_TRAIL_PCT", "10"))   # 過熱入場：從峰值回撤 >此% 即(移動停損)出場；0=停用
HOT_THRESHOLD = max(1, min(3, int(os.getenv("HOT_THRESHOLD", "1"))))  # 過熱旗標命中≥此數視為「過熱入場」
# ── 買入當下的「過熱閘門」（策略訊號 sig==1 時拒買過熱；2026-09-08 新增，參數化）──
ENTRY_OVERHEAT = os.getenv("ENTRY_OVERHEAT", "0") == "1"   # 1=啟用(簽到買入當下拒買過熱) 0=關(對照)
OH_RSI_TH = float(os.getenv("OH_RSI_TH", "80"))            # RSI(14) >此值＝超買(拒買)
OH_DIST_WIN = int(os.getenv("OH_DIST_WIN", "63"))          # 距「N 日高」視窗
OH_DIST_TH = float(os.getenv("OH_DIST_TH", "8"))           # 距 N 日高 ≤此%＝貼近高點(拒買)
OH_ENTRY_MODE = os.getenv("OH_ENTRY_MODE", "both")         # any=任一命中拒買 / both=兩者都中才拒買(推薦, 較精準)
HOT_EXIT_GROUPS = set(x.strip() for x in os.getenv("HOT_EXIT_GROUPS", "normal,megacap,stable").split(",") if x.strip())  # 對哪些組套用緊離場(高獲利/追強除外)
# ── 硬停損（2026-09-16 新增，評估用；預設 0=關閉＝基準行為）──
# 為什麼：實盤沒有個股停損（出場只靠策略訊號），使用者問「怎麼沒有虧 10% 退場」。
# 這裡提供對照組：`STOP_LOSS_PCT=10` = 收盤價 ≤ 成本 ×(1−10%) 即全部出場（日頻收盤口徑，與本檔一致）。
# 規則本體在 core/backtest_rules.py（純函式、可獨立測試，不必匯入本檔的重型快取載入）。
from core.backtest_rules import signal_strategy, stop_hit, stop_loss_env  # noqa: E402

# ⚠️ .env 一律以「檔案」為準（override=True）。原因（2026-10-01 實測）：
#   容器用 docker-compose `env_file` 在**建立容器時**把變數注入 process env，之後主機上改 `.env`
#   不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 不會覆蓋它們
#   ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。
#   主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`（V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)
STOP_LOSS_PCT = stop_loss_env("STOP_LOSS_PCT", 0.0)

GROUPS = {
    "high_profit": {"label": "高獲利(高風險)", "strats": ["ma_cross", "breakout"]},
    "normal":      {"label": "正常",          "strats": ["bollinger", "ma_cross", "vwap", "breakout"]},
    "stable":      {"label": "高穩定(低風險)", "strats": ["bollinger", "vwap"]},
    "megacap":     {"label": "權值股動能", "strats": ["ma_cross", "breakout"]},
}

STRAT_FUNCS = {
    "bollinger": bollinger_reverse_strategy,
    "ma_cross": ma_cross_strategy,
    "vwap": vwap_deviation_strategy,
    "breakout": breakout_strategy,
}


def load_data():
    """載入回測所需資料（**不再在 import 時執行** —— 否則光 import 就要載數百檔股票）。

    在 `main()` 一開始呼叫。回測函式仍透過模組全域取用（`data`／`pools`／`ALL_DATES`…）。
    """
    global hist
    global _
    global union
    global data
    global hist_for_pool
    global all_data_pool
    global pools
    global inst_conf
    global INST_CONFDATES
    global _mkt0full
    global FULLCAL
    global _mkt0
    global MASTER
    global ALL_DATES
    global MONTH_STARTS
    global MONTH_START_SET
    # ── 載入資料 ─────────────────────────────────────────────
    hist, _ = load_cache_or_raw("cache/inst_momentum/historical_shares.pkl")
    union = sorted({k[0] for k in hist})
    data = {}
    for sid in union:
        df = ssg.load_stock(sid)
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["close"])
        if len(df) > 60:
            data[sid] = df
    print(f"價格載入: {len(data)} 檔 (聯集池 {len(union)})")

    hist_for_pool = {(sid, q): v for (sid, q), v in hist.items()}
    all_data_pool = {}
    for sid, df in data.items():
        d2 = df.reset_index()
        d2 = d2.rename(columns={d2.columns[0]: "date"})
        all_data_pool[sid] = d2
    pools = build_quarterly_pool(hist_for_pool, all_data_pool, top_n=POOL_N)
    print(f"逐季池: {len(pools)} 季點, 空池 {sum(1 for p in pools.values() if not p)}")

    # 法人確認資料（可選）
    inst_conf = None
    INST_CONFDATES = []
    if INST_CONFIRM:
        inst_conf = ssg.load_twse_inst_merged()
        INST_CONFDATES = sorted(pd.Timestamp(d) for d in inst_conf)
        print(f"法人確認啟用: {len(INST_CONFDATES)} 交易日, DAYS={INST_DAYS}")

    # 全期交易日曆（取 0050 為基準，並涵蓋全部資料日）
    _mkt0full = ssg.load_stock("0050").dropna(subset=["close"])
    FULLCAL = sorted(set(_mkt0full.index))          # 完整日曆（含 2022 前，供選股日查詢）
    _mkt0 = _mkt0full[(_mkt0full.index >= pd.Timestamp(START)) & (_mkt0full.index <= pd.Timestamp(END))]
    MASTER = sorted(set(_mkt0.index))
    ALL_DATES = sorted(set(
        d for df in data.values() for d in df.index
        if pd.Timestamp(START) <= d <= pd.Timestamp(END)
    ))
    MONTH_STARTS = {}
    for d in ALL_DATES:
        ym = (d.year, d.month)
        if ym not in MONTH_STARTS:
            MONTH_STARTS[ym] = d
    MONTH_START_SET = set(MONTH_STARTS.values())


def pool_for_date(d):
    cand = [q for q in sorted(pools) if pd.Timestamp(q + "-01").to_period("M").end_time <= d]
    return pools[cand[-1]] if cand else []


# ── 技術工具（只用 ≤ 指定日期的資料）────────────────────────
def snap(df, d):
    return ssg._snap_date(df, d)


def trailing_ret(df, d, days):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    sp = float(df.iloc[s]["close"]); ep = float(df.iloc[idx]["close"])
    return (ep - sp) / sp if sp > 0 else None


def vol(df, d, days=63):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    px = df.iloc[s:idx + 1]["close"].values
    return float(np.std(px / np.mean(px))) if len(px) >= 5 else None


def ma_pos(df, d, days=20):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    ma = float(df.iloc[s:idx + 1]["close"].mean()); cp = float(df.iloc[idx]["close"])
    return (cp - ma) / ma if ma > 0 else None


def inst_ok(sid, sel_date):
    """法人確認濾網：近 INST_DAYS 法人累計淨買超 > 0。None（未知）→ pass-through。
    每個選股日只算一次全市場向量並快取；各股查表。"""
    if not INST_CONFIRM:
        return True
    import bisect
    key = pd.Timestamp(sel_date)
    if key not in _INST_NET_CACHE:
        idx = bisect.bisect_right(INST_CONFDATES, key)
        recent = INST_CONFDATES[max(0, idx - INST_DAYS):idx]
        acc = {}
        for ts in recent:
            row = inst_conf[ts.strftime("%Y-%m-%d")]
            for sid2, (b, s) in row.items():
                acc[sid2] = acc.get(sid2, 0) + (b - s)
        _INST_NET_CACHE[key] = pd.Series(acc) if acc else pd.Series(dtype=float)
    ser = _INST_NET_CACHE[key]
    net = ser.get(sid)
    return net is None or net > 0


_INST_NET_CACHE = {}


# ── 人工降溫（過熱過濾）helper ────────────────────────────
_OH_PER_CACHE = {}
_OH_DL = None


def _oh_dl():
    global _OH_DL
    if _OH_DL is None:
        from FinMind.data import DataLoader
        _OH_DL = DataLoader()
    return _OH_DL


# PER 磁碟快取（FinMind 有配額，重跑不要重抓）：
# `cache/stock_per/per_{代號}.pkl`（`{date_str: PER}`，經 core.cache_io 版本化）。
#
# ⚠️ 為何一定要有磁碟快取（2026-09-18 查獲）：原本只有**記憶體**快取、每次執行都重打 FinMind
#    ⇒ 抓到／抓不到 PER 會讓「過熱閘門」行為不同，**同一組參數兩次跑出 +79.2% 與 +109.6%**
#    （重跑不可重現 = 回測結論不可信）。改為磁碟快取後：第一次跑會抓並落地，之後完全可重現。
_PER_DIR = "cache/stock_per"
_OH_PER_MISS = {"n": 0}          # 抓不到 PER 的查詢次數（跑完印出來，供判讀可信度）


def per_at(series, sel_date):
    """{date_str: PER} → 最近一筆 ≤ sel_date 的 PER（無 → None）。純函式，可單獨測試。"""
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


_PER_STALE_DAYS = 10          # 快取最後一筆 PER 距選股日超過此天數 → 視為過期、重抓
_OH_PER_STALE = {"n": 0}      # 用到「過期 PER」的查詢次數（跑完印出）


def _oh_per_disk(sid):
    from core.cache_io import load_cache
    d, _ = load_cache(os.path.join(_PER_DIR, f"per_{sid}.pkl"))
    return d if isinstance(d, dict) and d else None


def series_max_date(series):
    """{date: PER} → 最大日期（Timestamp）；無 → None。"""
    best = None
    for d in (series or {}):
        try:
            ds = pd.Timestamp(d)
            if ds.tz is not None:
                ds = ds.tz_localize(None)
        except Exception:
            continue
        if best is None or ds > best:
            best = ds
    return best


def _oh_per_fetch(sid):
    """FinMind TaiwanStockPER（2015 起全段，抓一次即可長期重用）→ {date_str: PER}。"""
    try:
        dl = _oh_dl()
        d = dl.taiwan_stock_per_pbr(stock_id=sid, start_date="2015-01-01",
                                    end_date=pd.Timestamp.today().strftime("%Y-%m-%d"))
        if d is None or not len(d):
            return None
        d = d.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        return dict(zip(d["date"], d["PER"]))
    except Exception:
        return None


def _oh_get_per(sid, sel_date):
    """PER（≤ sel_date）→ 先讀磁碟快取，缺才打 FinMind 並落地（之後可重現）。"""
    key = (sid, sel_date.strftime("%Y-%m"))
    if key in _OH_PER_CACHE:
        return _OH_PER_CACHE[key]
    per = None
    if OH_USE_PER:
        series = _oh_per_disk(sid)
        # ⚠️ 快取可能「太舊」：實測既有 259 檔全部只到 2025-12-31 ⇒ 拿它過濾 2026 年的選股
        #    等於閘門失效（用 9 個月前的 PER 判斷今天貴不貴）。過期就重抓並更新快取。
        fresh_enough = (series is not None
                        and (series_max_date(series) or pd.Timestamp("1970-01-01"))
                        >= pd.Timestamp(sel_date) - pd.Timedelta(days=_PER_STALE_DAYS))
        if not fresh_enough:
            fetched = _oh_per_fetch(sid)
            if fetched:
                merged = {**(series or {}), **fetched}
                from core.cache_io import dump_cache
                try:
                    os.makedirs(_PER_DIR, exist_ok=True)
                    dump_cache(os.path.join(_PER_DIR, f"per_{sid}.pkl"), merged,
                               meta={"dataset": "TaiwanStockPER", "symbol": sid})
                except Exception:
                    pass
                series = merged
            elif series is None:
                _OH_PER_MISS["n"] += 1
            else:
                _OH_PER_STALE["n"] += 1        # 抓不到新資料 → 退回舊值（可重現但已過期）
        per = per_at(series, sel_date)
        if per is None and series is not None:
            _OH_PER_MISS["n"] += 1
    _OH_PER_CACHE[key] = per
    return per


def overheat_flags(sid, sel_date):
    """過熱旗標（永遠算，供 HOT_EXIT 與排除用；只算 ≤ sel_date，無前瞻）。"""
    df = data.get(sid)
    if df is None:
        return None
    sd = snap(df, sel_date)
    if sd is None or sd not in df.index:
        return None
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    if cp <= 0:
        return None
    win = df.iloc[max(0, idx - 251):idx + 1]
    hi = float(win["high"].max())
    pct_from_high = (hi - cp) / hi * 100 if hi > 0 else 0.0
    near_high = (hi > 0 and cp >= hi * (1 - OH_MAX_FROM_HIGH / 100.0))
    ys = df[df.index <= pd.Timestamp(str(sd.year) + "-01-01")]
    ytd = (cp / float(ys.iloc[-1]["close"]) - 1) if len(ys) and float(ys.iloc[-1]["close"]) > 0 else 0.0
    huge_ytd = ytd > OH_MAX_YTD / 100.0
    per = _oh_get_per(sid, sd) if (near_high or huge_ytd) else None
    high_pe = per is not None and per > OH_MAX_PER
    count = int(near_high) + int(huge_ytd) + int(high_pe)
    return {"sid": sid, "near_high": near_high, "huge_ytd": huge_ytd, "high_pe": high_pe,
            "count": count, "overheated": count >= OH_MIN_COUNT}


def overheated(sid, sel_date):
    if not OVERHEAT:
        return False
    f = overheat_flags(sid, sel_date)
    return bool(f and f["overheated"])


def _rsi14(df, idx):
    """簡單 RSI(14)。回傳 0-100 或 None（資料不足）。"""
    if idx < 15:
        return None
    seg = df.iloc[idx - 14:idx + 1]
    delta = seg["close"].diff()
    up = float(delta[delta > 0].sum())
    dn = float(-delta[delta < 0].sum())
    if up + dn <= 0:
        return 50.0
    rs = up / dn if dn > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def entry_overheat(sid, d):
    """買入當下是否過熱（只算 ≤ d，無前瞻）。供 sig==1 時拒買用。
    參數化：RSI 超買（OH_RSI_TH）與/或 距 N 日高太近（OH_DIST_WIN/OH_DIST_TH）。
    """
    if not ENTRY_OVERHEAT:
        return False
    df = data.get(sid)
    if df is None:
        return False
    sd = snap(df, d)
    if sd is None or sd not in df.index:
        return False
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    if cp <= 0:
        return False
    rsi = _rsi14(df, idx)
    rsi_over = rsi is not None and rsi > OH_RSI_TH
    win = df.iloc[max(0, idx - OH_DIST_WIN):idx + 1]
    hi = float(win["high"].max())
    near_high = hi > 0 and ((hi - cp) / hi * 100.0) <= OH_DIST_TH
    if OH_ENTRY_MODE == "both":
        return rsi_over and near_high
    return rsi_over or near_high


# ── 三組選股規則 ─────────────────────────────────────────
def pick_high_profit(pool, sel_date):
    cands = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        r = trailing_ret(df, sd, MOM_DAYS)
        mp = ma_pos(df, sd, 20)
        if r is None or mp is None or mp < 0:
            continue
        if not inst_ok(sid, sel_date):
            continue
        if overheated(sid, sel_date):   # 人工降溫：過熱 → 剔除
            continue
        cands.append((sid, r))
    cands.sort(key=lambda x: -x[1])
    return [s for s, _ in cands[:TOP_N]]


def pick_normal(pool, sel_date):
    scored = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        if not inst_ok(sid, sel_date):
            continue
        s = ssg.score_stock(sid, df, sd, dict(ssg.DEFAULT_PARAMS))
        if s is None:
            continue
        if overheated(sid, sel_date):   # 人工降溫：過熱 → 剔除
            continue
        scored.append(s)
    scored.sort(key=lambda x: -x["total"])
    return [s["symbol"] for s in scored[:TOP_N]]


def pick_stable(pool, sel_date):
    cands = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        v = vol(df, sd, 63)
        mp200 = ma_pos(df, sd, 200)
        if v is None or mp200 is None or mp200 < 0:
            continue
        if not inst_ok(sid, sel_date):
            continue
        cands.append((sid, v))
    cands.sort(key=lambda x: x[1])
    return [s for s, _ in cands[:TOP_N]]


def pick_megacap_momentum(pool, sel_date):
    """權值股動能：從「當時市值前 MEGA_N 大」(權值股)挑動能最強者。"""
    sub = pool[:MEGA_N]
    cands = []
    for sid in sub:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        r = trailing_ret(df, sd, MOM_DAYS)
        mp = ma_pos(df, sd, 20)
        if r is None or mp is None or mp < 0:
            continue
        if not inst_ok(sid, sel_date):
            continue
        if overheated(sid, sel_date):
            continue
        cands.append((sid, r))
    cands.sort(key=lambda x: -x[1])
    return [s for s, _ in cands[:TOP_N]]


PICKERS = {"high_profit": pick_high_profit, "normal": pick_normal, "stable": pick_stable,
           "megacap": pick_megacap_momentum}


# ── 訊號快取（全期一次算，rolling 皆回看歷史 → 無未來函數）──
_SIG = {}
_ROLL = {}
_STRATS = set(s for s in STRAT_FUNCS)


def _roll(sid):
    if sid not in _ROLL:
        df = data[sid]
        r = df.reindex(ALL_DATES)
        r["close"] = r["close"].ffill()
        _ROLL[sid] = r
    return _ROLL[sid]


def sig_at(sid, strat, d):
    if (sid, strat) not in _SIG:
        df = data[sid]
        _SIG[(sid, strat)] = STRAT_FUNCS[strat](df)["signal"].reindex(ALL_DATES).ffill().fillna(0)
    return int(_SIG[(sid, strat)].get(d, 0))


def close_at(sid, d):
    r = _roll(sid)
    return float(r.loc[d, "close"]) if d in r.index else 0.0


def strat_for(group, idx):
    return GROUPS[group]["strats"][idx % len(GROUPS[group]["strats"])]


def pick_strategy_by_form(sid, sel_date):
    """依個股當下型態自適應選策略（四種全開放，只用 ≤ 選股日資料）。
    型態=趨勢/盤整，選順勢(ma_cross/breakout)或回歸(bollinger/vwap)。
    """
    df = data.get(sid)
    if df is None:
        return "ma_cross"
    sd = snap(df, sel_date)
    if sd is None or sd not in df.index:
        return "ma_cross"
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    ma20 = float(df.iloc[max(0, idx - 19):idx + 1]["close"].mean())
    ma60 = float(df.iloc[max(0, idx - 59):idx + 1]["close"].mean())
    mom20 = trailing_ret(df, sd, 20) or 0.0
    trend_up = (cp > ma20) and (ma20 > ma60) and (mom20 > 0)
    if trend_up:
        # 順勢：強勢(20d>5%)用突破，否則均線交叉
        return "breakout" if mom20 > 0.05 else "ma_cross"
    # 盤整/下跌 → 回歸：回檔超跌用布林(買低)，否則 VWAP
    return "bollinger" if cp < ma20 else "vwap"


def buy_cost(cash, px):
    return cash - cash * COMMISSION  # 實際可用於買股（預留手續費）


def sell_net(proceeds, sid):
    return proceeds * (1 - COMMISSION - ssg.tax_rate(sid))


def run_group(gkey):
    cash = 0.0 if DCA_MONTHLY > 0 else INITIAL   # DCA：空手起、每月投入；一筆：INITIAL
    deposited = 0.0                               # 已投入總額（DCA 用）
    positions = {}   # sid -> {'strat': s, 'shares': float}
    bucket = {}      # sid -> 未投資的該股資金（可再進場）
    _hot_exit = HOT_EXIT and gkey in HOT_EXIT_GROUPS   # 僅對指定組(正常/權值股動能/高穩定)套用緊離場
    curve = {}
    selection_log = []
    peak = 0.0
    extended_once = False
    deployed_hist = {}   # dts -> 實際投入在「持股」的資金（shares × 價）
    alloc_hist = {}      # dts -> 分配到「股票桶」的資金（bucket + 持股）＝已承諾但尚未全買
    stop_count = [0]     # 硬停損觸發次數（STOP_LOSS_PCT>0 時才有意義）

    def equity(dts):
        e = cash + sum(bucket.values())
        for sid, p in positions.items():
            if p["shares"] > 0:
                e += p["shares"] * close_at(sid, dts)
        return e

    for d in ALL_DATES:
        dts = pd.Timestamp(d)

        # 日初權益（供股災防護回撤評估）
        eq0 = equity(dts)
        peak = max(peak, eq0)

        # ── 每月選股事件（月初第一個交易日）──
        if dts in MONTH_START_SET:
            # DCA：每月定額投入現金池（在選股分配前）
            if DCA_MONTHLY > 0:
                cash += DCA_MONTHLY
                deposited += DCA_MONTHLY
            # 股災防護：選股日總回撤 > MIN_DRAW_BACK% 時「最多延長一輪」續抱未換。
            # 邏輯同原版 backtest_selector：首次觸發才延長(extended_once)，下輪恢復正常換倉。
            skip = False
            if MIN_DRAW_BACK > 0 and peak > 0:
                dd = eq0 / peak - 1.0
                if dd < -MIN_DRAW_BACK / 100.0:
                    if MDB_UNLIMITED:
                        skip = True
                    elif not extended_once:
                        skip = True
                        extended_once = True
                    else:
                        extended_once = False
                else:
                    extended_once = False
            if skip:
                selection_log.append({"date": dts.strftime("%Y-%m-%d"), "S": None, "skipped": True})
            else:
                prior = [x for x in FULLCAL if x < dts]
                sel_date = prior[-1] if prior else None
                S = PICKERS[gkey](pool_for_date(sel_date), sel_date) if sel_date is not None else []
                selection_log.append({"date": dts.strftime("%Y-%m-%d"), "S": list(S), "skipped": False})

                # Drop（A=full）：剔除未再選入的持股 → 賣出並把 bucket 併回現金池。
                # C=addonly：不強制賣出「仍在持(shares>0)」的股票；只清理「已出場(flat)且不在新選股」的。
                if SWAP_MODE == "full":
                    for sid in list(positions.keys()):
                        if sid not in S:
                            sh = positions[sid]["shares"]
                            px = close_at(sid, dts)
                            if sh > 0 and px > 0:
                                bucket[sid] = bucket.get(sid, 0) + sell_net(sh * px, sid)
                            cash += bucket.pop(sid, 0.0)
                            del positions[sid]
                else:  # addonly (C)
                    for sid in list(positions.keys()):
                        if positions[sid]["shares"] == 0 and sid not in S:
                            cash += bucket.pop(sid, 0.0)
                            del positions[sid]

                # Add：新選入且未持有 → 用現金池等權分配本金。
                # C 只補到 TOP_N（active 未滿才加），不強制賣出/換出。
                new = [sid for sid in S if sid not in positions]
                if SWAP_MODE == "addonly":
                    active = sum(1 for s in positions if positions[s]["shares"] > 0)
                    new = new[:max(0, TOP_N - active)]
                if new and cash > 0:
                    alloc = cash / len(new)
                    for i, sid in enumerate(new):
                        px = close_at(sid, dts)
                        # STRAT_MODE=form（＝實盤 strategy=auto）：
                        #   EXEC=immediate(A) → 選股日就買，當場鎖定；EXEC=signal(B) → **進場當天才鎖**
                        #   （與實盤「買入那一刻 route_strategy()」一致；見 signal_strategy_for）。
                        if STRAT_MODE == "form":
                            # EXEC=immediate(A) 或 LOCK_AT=selection ⇒ 選股日就選定策略；
                            # 否則（B 等訊號＋與實盤一致）先不鎖，等進場成交當天鎖定。
                            _lock_now = (EXEC != "signal") or (LOCK_AT == "selection")
                            _st = pick_strategy_by_form(sid, sel_date) if _lock_now else None
                        else:
                            _st = strat_for(gkey, i)
                        _oh = overheat_flags(sid, sel_date)
                        _hot = _hot_exit and bool(_oh and _oh["count"] >= HOT_THRESHOLD)
                        positions[sid] = {"strat": _st, "shares": 0.0, "hot": _hot,
                                          "entry": 0.0, "peak": 0.0}
                        bucket[sid] = alloc
                        cash -= alloc
                        # EXEC=immediate(A)：選股日立即買滿；EXEC=signal(B, 自選股=等訊號)：留空倉等進場訊號(由下方逐日訊號買進)
                        if (EXEC != "signal") and (px > 0) and (bucket[sid] > 5):
                            budget = bucket[sid]
                            bought = buy_cost(budget, px)
                            positions[sid]["shares"] = bought / px
                            positions[sid]["entry"] = px
                            positions[sid]["peak"] = px
                            bucket[sid] = 0.0

            # 記錄實際持有（代號＋策略）
            selection_log[-1]["holdings"] = [
                {"sid": s, "strat": positions[s]["strat"] or "pending"} for s in positions
            ]

        # ── 逐日訊號進出 ──
        for sid in list(positions.keys()):
            px = close_at(sid, dts)
            if px <= 0:
                continue
            # 未鎖定（等訊號尚未進場）→ 每日重路由；已鎖定 → 固定策略（與實盤一致）
            _st_today = signal_strategy(positions[sid]["strat"], pick_strategy_by_form, sid, dts)
            sig = sig_at(sid, _st_today, dts)
            sh = positions[sid]["shares"]
            hot = positions[sid].get("hot", False)
            do_sell = (sh > 0 and sig == -1)
            # 硬停損（2026-09-16 評估；STOP_LOSS_PCT=0 → 完全不影響基準）
            if sh > 0 and stop_hit(px, positions[sid].get("entry", 0.0), STOP_LOSS_PCT):
                do_sell = True
                stop_count[0] += 1
            # 過熱入場的自適應離場：獲利目標 + 移動停損（避免卡高點；僅對啟用組）
            if _hot_exit and hot and sh > 0:
                positions[sid]["peak"] = max(positions[sid].get("peak", 0.0), px)
                if HOT_TP_PCT > 0 and px >= positions[sid]["entry"] * (1 + HOT_TP_PCT / 100.0):
                    do_sell = True
                if HOT_TRAIL_PCT > 0 and px <= positions[sid]["peak"] * (1 - HOT_TRAIL_PCT / 100.0):
                    do_sell = True
            if do_sell and sh > 0:
                proceeds = sell_net(sh * px, sid)
                bucket[sid] = bucket.get(sid, 0.0) + proceeds
                positions[sid]["shares"] = 0.0
                # 2026-09-22 對齊實盤：賣出（部位歸零）要**釋放 auto 鎖定**，
                #   下次進場重新路由（實盤 AUTO_FIXED_CACHE.pop；2006 實例：ma_cross 賣 → breakout 買回）。
                #   舊版留著舊 strat ⇒ 回測低估「出場後換策略重進」的效果。
                positions[sid]["strat"] = strategy_after_exit(positions[sid]["strat"], positions[sid]["shares"])
            elif sh == 0 and sig == 1 and bucket.get(sid, 0.0) > 5:
                if entry_overheat(sid, dts):
                    continue   # 過熱拒買（策略訊號在、但買入當下過熱(RSI超買/距高點近)）
                budget = bucket[sid]
                bought = buy_cost(budget, px)
                positions[sid]["shares"] = bought / px
                positions[sid]["entry"] = px
                positions[sid]["peak"] = px
                bucket[sid] = 0.0
                if positions[sid]["strat"] is None:
                    # **進場當下鎖定**（這一輪用來產生買訊的策略）——與實盤買入即鎖定一致
                    positions[sid]["strat"] = _st_today

        # ── 權益紀錄 ──
        curve[dts] = equity(dts)
        _inv = sum(p["shares"] * close_at(sid, dts) for sid, p in positions.items() if p["shares"] > 0)
        deployed_hist[dts] = _inv
        alloc_hist[dts] = _inv + sum(bucket.values())

    curve = pd.Series(curve).sort_index()
    _avg_inv = (pd.Series(deployed_hist).mean() if deployed_hist else 0.0)
    _avg_alloc = (pd.Series(alloc_hist).mean() if alloc_hist else 0.0)
    # 尖峰動用（2026-09-18 新增，使用者指正）：**實際需要準備多少資金**看的是最高峰、不是平均。
    # 「平均 58%」只說明平均；要回答「50 萬是不是真的需要」得看 peak_deployed。
    _peak_inv = max(deployed_hist.values()) if deployed_hist else 0.0
    _peak_d = max(deployed_hist, key=deployed_hist.get) if deployed_hist else None
    # ⚠️ 「相對初始本金」的動用金額會隨複利超過 100%（帳戶長大後本來就會），**不能**用來回答
    #    「需要準備多少資金」。正確指標是 **deployed ÷ 當下權益**（曝險比例），取其平均與尖峰。
    _ratios = [deployed_hist[d] / curve[d] for d in deployed_hist
               if d in curve.index and curve[d] > 0]
    _rs = sorted(_ratios)
    _util_avg = (sum(_ratios) / len(_ratios)) if _ratios else 0.0
    _util_peak = max(_ratios) if _ratios else 0.0
    # 中位數/p90：平均會被「剛換股後大量空倉」拉低，中位數與 p90 才看得出「平常要準備多少」
    def _pct(q):
        if not _rs:
            return 0.0
        i = min(len(_rs) - 1, max(0, int(round(q * (len(_rs) - 1)))))
        return _rs[i]
    _util_p50, _util_p90 = _pct(0.5), _pct(0.9)
    _util_peak_d = (max(deployed_hist, key=lambda d: deployed_hist[d] / curve[d])
                    if _ratios else None)
    return {"curve": curve, "final": curve.iloc[-1] if len(curve) else cash,
            "deposited": deposited, "selection_log": selection_log,
            "avg_deployed": round(float(_avg_inv)),
            "avg_allocated": round(float(_avg_alloc)),
            "peak_deployed": round(float(_peak_inv)),
            "peak_deployed_date": (str(_peak_d)[:10] if _peak_d is not None else None),
            "util_avg": round(float(_util_avg), 4),        # 平均曝險比例（÷當下權益）
            "util_p50": round(float(_util_p50), 4),        # 中位數曝險比例
            "util_p90": round(float(_util_p90), 4),        # p90 曝險比例
            "util_peak": round(float(_util_peak), 4),      # 尖峰曝險比例（÷當下權益）
            "util_peak_date": (str(_util_peak_d)[:10] if _util_peak_d is not None else None),
            "stop_count": stop_count[0]}


# ── 0050 基準 ───────────────────────────────────────────
def benchmark(initial=INITIAL):
    df = _mkt0
    idx = df.index[(df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(END))]
    if len(idx) == 0:
        return pd.Series(dtype=float)
    t0 = idx[0]; b0 = float(df.loc[t0, "close"])
    curve = df.loc[idx, "close"] * (initial / b0)
    curve = curve * (1 - ssg.COMMISSION_RATE)
    daily = 0.0032 / 252.0
    curve = curve * ((1 - daily) ** np.arange(len(curve)))
    curve = curve * (1 - ssg.COMMISSION_RATE - ssg.ETF_TAX)
    return curve


def benchmark_dca(monthly=DCA_MONTHLY):
    """每月定額折入 0050：每個月第一個交易日買入 monthly，持有到期末。回傳(終值, 已投入)。"""
    df = _mkt0
    idx = list(df.index[(df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(END))])
    if not idx:
        return 0.0, 0.0
    sep = {}
    for d in idx:
        ym = (d.year, d.month)
        if ym not in sep:
            sep[ym] = d
    last = float(df.loc[idx[-1], "close"])
    final = 0.0
    contrib = 0.0
    for d in sep.values():
        px = float(df.loc[d, "close"])
        if px <= 0:
            continue
        contrib += monthly
        final += monthly * (last / px)   # 當日買入的 0050 持股到期末價值（未計成本，近似）
    final = final * (1 - ssg.COMMISSION_RATE - ssg.ETF_TAX)   # 簡化單次成本
    return final, contrib


def perf(curve):
    curve = curve.dropna()
    if len(curve) < 3:
        return None
    rets = curve.pct_change().dropna()
    sd = rets.std(ddof=1)
    sharpe = float(rets.mean() / sd * math.sqrt(252)) if sd and sd > 0 else float("nan")
    run_max = curve.cummax()
    mdd = float(((curve - run_max) / run_max).min())
    return {"sharpe": sharpe, "mdd": mdd}


def yearly(curve):
    if curve is None or len(curve) == 0:
        return {}
    return {int(yr): float(grp.iloc[-1] / grp.iloc[0] - 1)
            for yr, grp in curve.groupby(curve.index.year)}


def main():
    load_data()
    results = {}
    ONLY = [x.strip() for x in os.getenv("GROUPS_ONLY", "").split(",") if x.strip()]
    gkeys = ONLY if ONLY else list(GROUPS.keys())
    for gkey in gkeys:
        meta = GROUPS[gkey]
        res = run_group(gkey)
        curve = res["curve"]
        years = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
        base = res["deposited"] if DCA_MONTHLY > 0 else INITIAL   # DCA 用已投入總額；一筆用 INITIAL
        total = res["final"] / base - 1
        ann = (res["final"] / base) ** (1 / years) - 1 if total > -1 else -1
        p = perf(curve) or {}
        results[gkey] = {
            "label": meta["label"],
            "final_value": round(res["final"]),
            "contributed": round(base),
            "total_return": round(total, 4),
            "annualized": round(ann, 4),
            "sharpe": round(p.get("sharpe", float("nan")), 2),
            "max_drawdown": round(p.get("mdd", float("nan")), 4),
            "avg_deployed": res["avg_deployed"],      # 平均實際投入在持股的資金
            "peak_deployed": res.get("peak_deployed"),          # 尖峰實際投入金額
            "peak_deployed_date": res.get("peak_deployed_date"),
            "util_avg": res.get("util_avg"),                    # **平均曝險比例（÷當下權益）**
            "util_p50": res.get("util_p50"), "util_p90": res.get("util_p90"),
            "util_peak": res.get("util_peak"),                  # **尖峰曝險比例（÷當下權益）**
            "util_peak_date": res.get("util_peak_date"),
            "avg_allocated": res["avg_allocated"],    # 平均分配到股票桶的資金（含空等訊號）
            "stop_loss_pct": STOP_LOSS_PCT,           # 本次回測的硬停損設定（0=關）
            "stop_count": res.get("stop_count", 0),   # 硬停損觸發次數
            # DCA 模式下權益曲線含每月投入，年度報酬會失真 → 不輸出
            "yearly": ({} if DCA_MONTHLY > 0 else {k: round(v, 4) for k, v in yearly(curve).items()}),
            "selection_log": res["selection_log"],
        }
        _deploy_pct = res["avg_deployed"] / INITIAL * 100 if INITIAL > 0 else 0.0
        _alloc_pct = res["avg_allocated"] / INITIAL * 100 if INITIAL > 0 else 0.0
        _mode = "dca" if DCA_MONTHLY > 0 else "lump"
        # ⚠️ 2026-09-21 修：原本寫**固定檔名**（`results/daily_<group>_<mode>.csv`）⇒ 跑其他窗口會
        #   覆蓋 11 年那條曲線（實際發生過：分析腳本讀到的曲線
        #   其實是別的窗口的）。改為一律寫**窗口專屬檔名**，canonical(2015-01-01/2025-12-31)
        #   另外再寫一份舊檔名，讓既有工具與文件仍可讀
        #   （2026-09-18 修法）。
        # 檔名含口徑（EXEC／DCA／鎖定時點）——2026-09-22 補：只帶窗口的話，
        #   同窗口的 signal 與 immediate 會互相覆蓋（實際發生：混合分析差點混到 A 的曲線）。
        _suffix = f"{EXEC}" + (f"_dca{DCA_MONTHLY:g}" if DCA_MONTHLY > 0 else "") \
                  + ("" if LOCK_AT == "fill" else f"_{LOCK_AT}")
        curve.to_csv(f"results/daily_{gkey}_{START}_{END}_{_suffix}.csv")
        # 舊檔名（不含口徑）只為「已文件化的 canonical 基線」保留：2015-2025 + signal + fill + 單筆
        if (START, END) == ("2015-01-01", "2025-12-31") and _suffix == "signal":
            curve.to_csv(f"results/daily_{gkey}_{_mode}.csv")
        print(f"\n[{meta['label']}] 投入 NT${base:,.0f} → 終值 NT${res['final']:,.0f}  "
              f"總報酬 {total:+.2%} 年化 {ann:+.2%} MDD {p.get('mdd', float('nan')):.2%} "
              f"夏普 {p.get('sharpe', float('nan')):.2f}")
        _pk = res.get("peak_deployed") or 0
        print(f"  平均動用(持股中) NT${res['avg_deployed']:,.0f}（{_deploy_pct:.1f}% of {INITIAL:,.0f}）｜"
              f"平均分配到股票桶 NT${res['avg_allocated']:,.0f}（{_alloc_pct:.1f}%）")
        print(f"  尖峰動用 NT${_pk:,.0f}（{_pk / INITIAL * 100:.1f}% of 初始 {INITIAL:,.0f}"
              f"；{res.get('peak_deployed_date') or '?'}）")
        print(f"  🔑 曝險比例（÷當下權益）：平均 {res.get('util_avg', 0):.1%}"
              f"｜中位 {res.get('util_p50', 0):.1%}｜p90 {res.get('util_p90', 0):.1%}"
              f"｜尖峰 {res.get('util_peak', 0):.1%}（{res.get('util_peak_date') or '?'}）"
              f" ← 這才是回答「要準備多少資金」的數字（T+2 淨額交割下現金需求更低）")
        if STOP_LOSS_PCT > 0:
            print(f"  硬停損 −{STOP_LOSS_PCT:g}%：觸發 {res.get('stop_count', 0)} 次")
        if DCA_MONTHLY == 0:
            print("  年度:", {k: f"{v:+.2%}" for k, v in yearly(curve).items()})

    years = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
    if DCA_MONTHLY > 0:
        b_final, b_contrib = benchmark_dca(DCA_MONTHLY)
        b_total = b_final / b_contrib - 1
        b_ann = (b_final / b_contrib) ** (1 / years) - 1 if b_total > -1 else -1
        print(f"\n[0050 DCA 基準] 投入 NT${b_contrib:,.0f} → 終值 NT${b_final:,.0f}  "
              f"總報酬 {b_total:+.2%} 年化 {b_ann:+.2%}")
        bench_meta = {"final_value": round(b_final), "contributed": round(b_contrib),
                      "total_return": round(b_total, 4), "annualized": round(b_ann, 4)}
    else:
        bench = benchmark()
        b_total = bench.iloc[-1] / INITIAL - 1
        b_ann = (bench.iloc[-1] / INITIAL) ** (1 / years) - 1
        bp = perf(bench) or {}
        print(f"\n[0050 買進持有] NT${INITIAL:,.0f} → NT${bench.iloc[-1]:,.0f}  "
              f"總報酬 {b_total:+.2%} 年化 {b_ann:+.2%} MDD {bp.get('mdd', float('nan')):.2%} "
              f"夏普 {bp.get('sharpe', float('nan')):.2f}")
        bench_meta = {"final_value": round(bench.iloc[-1]), "total_return": round(b_total, 4),
                      "annualized": round(b_ann, 4), "sharpe": round(bp.get("sharpe", float("nan")), 2),
                      "max_drawdown": round(bp.get("mdd", float("nan")), 4)}

    if OH_USE_PER:
        print(f"\n[PER 快取] 完全查不到 PER {_OH_PER_MISS['n']} 次、"
              f"退回過期 PER {_OH_PER_STALE['n']} 次（兩者皆＝過熱閘門在該查詢上失效；0/0＝完全可信）")
    out = {"start": START, "end": END, "initial": INITIAL, "dca_monthly": DCA_MONTHLY,
           "exec": EXEC, "strat_mode": STRAT_MODE, "swap_mode": SWAP_MODE,
           "overheat_use_per": OH_USE_PER, "lock_at": LOCK_AT,
           "per_miss": _OH_PER_MISS["n"] if OH_USE_PER else 0,
           "per_stale": _OH_PER_STALE["n"] if OH_USE_PER else 0,
           "pool_n": POOL_N, "top_n": TOP_N,
           "momentum_days": MOM_DAYS, "inst_confirm": INST_CONFIRM, "inst_days": INST_DAYS,
           "min_draw_back": MIN_DRAW_BACK, "strat_mode": STRAT_MODE, "swap_mode": SWAP_MODE,
           "overheat": OVERHEAT, "oh_max_from_high": OH_MAX_FROM_HIGH, "oh_max_ytd": OH_MAX_YTD,
           "oh_max_per": OH_MAX_PER, "oh_min_count": OH_MIN_COUNT, "oh_use_per": OH_USE_PER,
           "groups": results,
           "benchmark_0050": bench_meta}
    os.makedirs("results", exist_ok=True)
    with open("results/plan2_monthly_3group.json", "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    # 2026-09-21：另存**窗口／口徑專屬**檔名，避免「同一個檔名被不同窗口覆蓋」導致事後無法覆核
    #   （`plan2_monthly_3group.json` 保留為最新一次執行的通用檔）。
    _tag = f"{START}_{END}_{EXEC}" + (f"_dca{DCA_MONTHLY:g}" if DCA_MONTHLY > 0 else "") \
           + ("" if LOCK_AT == "fill" else f"_{LOCK_AT}")
    _out_path = f"results/plan2_monthly_3group_{_tag}.json"
    with open(_out_path, "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n已存 results/plan2_monthly_3group.json 與 {_out_path}")


if __name__ == "__main__":
    main()
