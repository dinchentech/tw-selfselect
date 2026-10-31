#!/usr/bin/env python3
"""scripts/monthly_rebalance_picker.py — 每月換股選股工具（固定程式）

用法:
  python scripts/monthly_rebalance_picker.py --risk high_profit
  python scripts/monthly_rebalance_picker.py --risk normal
  python scripts/monthly_rebalance_picker.py --risk high_profit --strategy auto  # 每檔用自動感知
  python scripts/monthly_rebalance_picker.py --risk normal --no-inst  # 關閉法人確認

行為:
  - 只用「當時市值前 N」誠實池（歷史股本×當季股價重建，無倖存者偏差）。
  - 選股僅用「截至當下」資料（無事後之明）。
  - 使用者只選 高風險(high_profit) / 正常(normal) 兩種風險（名稱是策略池特性，不代表歷史報酬更高）。
  - 輸出: 目前持股 vs 新選股 → 建議賣出 / 維持 / 買入；每檔標的給「原固定策略」與「auto 自動感知」兩種建議，
    並輸出可直接貼進 .env 的 PC_<代號>=... 設定列。
"""
import os, sys, json, argparse
from datetime import datetime
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
import numpy as np, pandas as pd
from pathlib import Path
from core.cache_io import load_cache_or_raw
from core.candidate_pool import build_quarterly_pool, load_historical_shares
import scripts.stock_selector_grid as ssg
from strategies.auto_sensing import route_strategy, auto_sensing_strategy

# ⚠️ .env 一律以「檔案」為準（override=True）。原因（2026-10-01 實測）：
#   容器用 docker-compose `env_file` 在**建立容器時**把變數注入 process env，之後主機上改 `.env`
#   不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 不會覆蓋它們
#   ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。
#   主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`（V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)

GROUPS = {
    "high_profit": {"label": "高風險（高波動）", "strats": ["ma_cross", "breakout"]},
    "normal": {"label": "正常", "strats": ["bollinger", "ma_cross", "vwap", "breakout"]},
}

LAST_PICK_FILE = os.getenv("MONTHLY_PICK_FILE", os.path.join("logs", "monthly_pick.json"))


# ── 載入誠實池與價量 ─────────────────────────────────────
def load_data(pool_n):
    hist, _hs = load_historical_shares()
    if not hist:
        sys.exit("❌ 找不到 cache/inst_momentum/historical_shares.pkl ⇒ 沒有誠實候選池可用。\n"
                 "   · 本機流程：先把 VM 的 cache 同步回來（alias `VM_sync_cache`，或\n"
                 "     `gcloud compute ssh tw-autotrader --zone=asia-east1-b --command='cd ~/tw-selfselect && tar czf - cache' | tar xzf - -C .`）\n"
                 "   · 或在建立這份 cache：`python scripts/build_historical_shares.py`（需 FinMind 額度）\n"
                 "   · 詳見使用手冊 §3-0「第一次執行」。")
    union = sorted({k[0] for k in hist})
    data = {}
    for sid in union:
        df = ssg.load_stock(sid)
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["close"])
        if len(df) > 60:
            data[sid] = df
    hist_for_pool = {(sid, q): v for (sid, q), v in hist.items()}
    all_data_pool = {}
    for sid, df in data.items():
        d2 = df.reset_index()
        d2 = d2.rename(columns={d2.columns[0]: "date"})
        all_data_pool[sid] = d2
    pools = build_quarterly_pool(hist_for_pool, all_data_pool, top_n=pool_n)
    return data, pools


def ma_pos(df, d, days=20):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    ma = float(df.iloc[s:idx + 1]["close"].mean())
    cp = float(df.iloc[idx]["close"])
    return (cp - ma) / ma if ma > 0 else None


def vol(df, d, days=63):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    px = df.iloc[s:idx + 1]["close"].values
    return float(np.std(px / np.mean(px))) if len(px) >= 5 else None


def snap(df, d):
    return ssg._snap_date(df, d)


# ── 人工降溫（過熱過濾）─────────────────────────────
# 門檻(env，可調)：MAX_PCT_FROM_HIGH=離52週高點%上限、MAX_YTD_GAIN=YTD漲幅%上限、
#                  MAX_PER=本益比上限、MIN_OVERHEAT=命中幾項才算過熱(預設2)
OV_PARAMS = {
    "max_from_high": float(os.getenv("MAX_PCT_FROM_HIGH", "7")),
    "max_ytd": float(os.getenv("MAX_YTD_GAIN", "100")),
    "max_per": float(os.getenv("MAX_PER", "45")),
    "min_count": max(1, min(3, int(os.getenv("MIN_OVERHEAT", "2")))),   # 1=任一項 / 2=≥2項(預設) / 3=三項全中『且』
}
_PER_CACHE = {}
_DL = None


def _get_dl():
    global _DL
    if _DL is None:
        from FinMind.data import DataLoader
        _DL = DataLoader()
    return _DL


def _get_per(sid, sel_date):
    """≤ sel_date 的 PER：**先讀磁碟快取**（`cache/stock_per/per_<sid>.pkl`，與回測同一份），
    沒有才回頭查 FinMind（只在那檔快取缺檔時發生）。失敗回 None。

    ⚠️ 2026-10-29 改：舊版每次都打 FinMind 抓 45 天窗口，`_zscore_rows()` 又只在「價量過熱命中」時
    才取值 ⇒ 大多數候選股的 `per=None`，被 `0 < PER <= 40` 的資格門檻默默剔除（選股結果被吃掉一大半）。
    """
    if sid in _PER_CACHE:
        return _PER_CACHE[sid]
    per = None
    try:
        from core.pit_data import per_asof
        per = per_asof(sid, sel_date, fetch=False)
    except Exception:
        per = None
    if per is None:
        try:
            dl = _get_dl()
            end = pd.Timestamp(sel_date).strftime("%Y-%m-%d")
            start = (pd.Timestamp(sel_date) - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
            d = dl.taiwan_stock_per_pbr(stock_id=sid, start_date=start, end_date=end)
            if d is not None and len(d):
                d = d.copy()
                d["date"] = pd.to_datetime(d["date"])
                d = d[d["date"] <= pd.Timestamp(sel_date)].sort_values("date")
                per = float(d.iloc[-1]["PER"]) if len(d) else None
        except Exception:
            per = None
    _PER_CACHE[sid] = per
    return per


def overheat_flags(sid, sel_date):
    """回傳過熱旗標 dict(或 None)。過熱 = 近52週高點 + YTD 漲幅 + 高本益比。"""
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
    near_high = (hi > 0 and cp >= hi * (1 - OV_PARAMS["max_from_high"] / 100.0))
    ys = df[df.index <= pd.Timestamp(str(sd.year) + "-01-01")]
    ytd = (cp / float(ys.iloc[-1]["close"]) - 1) if len(ys) and float(ys.iloc[-1]["close"]) > 0 else 0.0
    huge_ytd = ytd > OV_PARAMS["max_ytd"] / 100.0
    per = _get_per(sid, sd) if (near_high or huge_ytd) else None  # 只在價量命中才抓PER(限流)
    high_pe = per is not None and per > OV_PARAMS["max_per"]
    cnt = int(near_high) + int(huge_ytd) + int(high_pe)
    return {"sid": sid, "near_high": near_high, "huge_ytd": huge_ytd, "high_pe": high_pe,
            "pct_from_high": round(pct_from_high, 1), "ytd": round(ytd * 100, 1),
            "per": per, "count": cnt, "overheated": cnt >= OV_PARAMS["min_count"]}


def is_overheated(sid, sel_date):
    f = overheat_flags(sid, sel_date)
    return bool(f and f["overheated"])


# ── 選股規則（與回測相同，無事後之明）────────────────────
# ── 評分模型（2026-10-29）：與回測 `SCORING_MODEL` 同義，預設 `zscore`（AI 代理那套公式）
#   zscore ＝ 先篩 0<PER<=40，再 0.40·z(63日)+0.25·z(20日)+0.20·z(距52週高)+0.15·z(-PER)（共用 core/scoring.py）
#   legacy ＝ 現行 ssg.score_stock 綜合分
SCORING_MODEL = os.getenv("SELFSELECT_SCORING_MODEL", os.getenv("SCORING_MODEL", "zscore")).strip().lower()
if SCORING_MODEL not in ("legacy", "zscore"):
    SCORING_MODEL = "zscore"


# ── zscore 的兩個因子開關（2026-10-29 補進實盤；與回測 `FACTOR_REVENUE`／`MAX_PER_SECTOR` 同義）
#   SELFSELECT_FACTOR_REVENUE=1（預設）：月營收 YoY 加進分數（權重見 core.scoring.WEIGHTS_REVENUE）
#   SELFSELECT_MAX_PER_SECTOR=2     ：每產業最多 2 檔（0＝不限，預設）
#   為什麼預設開營收因子：回測（2016-2025、zscore＋停泊0050）各池大小都是正貢獻
#   （池20 +395.1%→+407.1%、池50 +291.1%→+446.0%、池100 +411.1%→+709.6%、池150 +541.7%→+704.7%）。
# ── 選股口徑 preset（2026-10-29，`core/selection_presets.py`）：預設 `current`＝行為不變。
#   `SELFSELECT_PRESET=revenue|aggressive` 才會改池大小／營收因子／產業上限，
#   而且**只填使用者沒明示的鍵**（`SELFSELECT_FACTOR_REVENUE=0` 這類明示值一律優先）。
from core.selection_presets import (DEFAULT_PRESET, HIGH_RETURN_PRESETS, PRESETS as _PRESETS,
                                    active_name as _preset_name, expand as _preset_expand,
                                    warning_text as _preset_warning)

SELECTION_PRESET = _preset_name()
# 實盤的「明示」只認 **SELFSELECT_ 前綴**的變數：`POOL_N`／`FACTOR_REVENUE`／`MAX_PER_SECTOR`
# 是回測旋鈕，若它們躺在同一份 .env 裡就被拿來當實盤設定，會變成「改回測順便改實盤」的隱形耦合。
_LIVE_ENV_MAP = {"POOL_N": "SELFSELECT_POOL_N", "FACTOR_REVENUE": "SELFSELECT_FACTOR_REVENUE",
                 "MAX_PER_SECTOR": "SELFSELECT_MAX_PER_SECTOR"}
_explicit_knobs = {k: os.environ[v] for k, v in _LIVE_ENV_MAP.items() if os.environ.get(v)}
PRESET_KNOBS = _preset_expand(SELECTION_PRESET, _explicit_knobs)

FACTOR_REVENUE = str(PRESET_KNOBS.get("FACTOR_REVENUE", "0")).strip() not in ("0", "false", "False")
MAX_PER_SECTOR = int(PRESET_KNOBS.get("MAX_PER_SECTOR") or 0)
#: 月營收快取缺檔時要不要抓 FinMind（抓過就落地，之後離線可用）。0＝只用快取。
REVENUE_FETCH = os.getenv("SELFSELECT_REVENUE_FETCH", "1").strip() not in ("0", "false", "False")
_INDUSTRY = None
_SECTOR_LOADED = [False]
_Z_STATS = {}          # pick_zscore 的診斷數字（main 印出來，讓使用者看得到因子到底有沒有作用）


def _industry_map():
    """`cache/stock_industry.pkl`（{sid: 產業}）；讀不到就回 {}（此時產業上限自動失效）。"""
    global _INDUSTRY
    if not _SECTOR_LOADED[0]:
        _SECTOR_LOADED[0] = True
        try:
            from core.cache_io import load_cache_or_raw
            m, _meta = load_cache_or_raw("cache/stock_industry.pkl")
            _INDUSTRY = dict(m or {})
        except Exception:
            _INDUSTRY = {}
    return _INDUSTRY or {}


def _rev_yoy(sid, sel_date):
    """月營收 YoY（用公告時間可得的最近一個月，只用 ≤ sel_date 的資訊）；沒有 → None。"""
    try:
        from core.pit_data import load_revenue_rows, revenue_pack
        rows = load_revenue_rows(sid, fetch=REVENUE_FETCH)
        if not rows:
            return None
        pack = revenue_pack(rows, sel_date)
        if not pack.get("available") or not pack.get("items"):
            return None
        return pack["items"][-1].get("yoy")
    except Exception:
        return None


def _zscore_rows(pool, sel_date):
    """收集 z 分數模型需要的欄位（只用 ≤ sel_date 的資料）。

    PER 走 `_get_per()`（磁碟快取優先）；`FACTOR_REVENUE=1` 時另抓月營收 YoY（缺值以中性 0 計，不踢除）。
    """
    rows = []
    for sid in pool:
        df = ssg.load_stock(sid)
        if df is None or not len(df):
            continue
        sd = ssg._snap_date(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        idx = df.index.get_loc(sd)
        win = df.iloc[max(0, idx - 251):idx + 1]
        hi = float(win["high"].max())
        cp = float(df.loc[sd, "close"])
        rows.append({"sid": sid, "per": _get_per(sid, sd),
                     "rev": _rev_yoy(sid, sd) if FACTOR_REVENUE else None,
                     "r63": ssg.trailing_ret(df, sd, 63), "r20": ssg.trailing_ret(df, sd, 20),
                     "dist": (cp / hi - 1.0) if hi > 0 else None})
    return rows


def pick_zscore(pool, sel_date, top_n):
    """`SCORING_MODEL=zscore`：依共用公式（`core/scoring.py`）排序取前 N。

    可選：`FACTOR_REVENUE=1` 加入月營收 YoY、`MAX_PER_SECTOR>0` 套產業分散上限（超過上限者剔除、
    由後面的名次遞補，總檔數不變）。不足 N 檔仍交給 `fill_to_target()`（依 `FILL_MODE`）。
    """
    from core.scoring import apply_sector_cap, score_rows

    rows = _zscore_rows(pool, sel_date)
    ranked = score_rows(rows, use_revenue=FACTOR_REVENUE)
    if MAX_PER_SECTOR > 0:
        industry = _industry_map()
        if industry:
            capped = apply_sector_cap(ranked, industry, MAX_PER_SECTOR)
            pos = {sid: i for i, (sid, _s) in enumerate(ranked)}
            ranked = [(sid, pos[sid]) for sid in capped]        # 分數位置保留（只影響取前 N）
        else:
            print(f"⚠️ 讀不到產業對照（cache/stock_industry.pkl）⇒ MAX_PER_SECTOR={MAX_PER_SECTOR} 忽略")
    eligible = [r for r in rows if r.get("per") is not None]
    _Z_STATS.update({
        "n_rows": len(rows), "n_per": len(eligible),
        "n_rev": sum(1 for r in rows if r.get("rev") is not None),
        "n_ranked": len(ranked),
        "rev_on": FACTOR_REVENUE, "cap": MAX_PER_SECTOR,
    })
    if not ranked:
        print(f"⚠️ zscore 沒有合格候選（報告 {len(rows)} 檔、有 PER 的 {len(eligible)} 檔）")
    ranked_sids = [sid for sid, _s in ranked]
    strict = ranked_sids[:top_n]
    return fill_to_target(strict, ranked_sids, _mom_fallback(pool, sel_date, 63), top_n,
                          sel_date=sel_date)


# ── 選不滿 N 檔時的政策（2026-10-29 新增；與回測的 FILL_MODE 同義）──────────
#   proportional（預設）＝就選出的那幾檔，資金平均分配
#   topup              ＝補滿：先依分數補「被過熱／法人擋掉」的，仍不足再依 63 日動能補
FILL_MODE = os.getenv("SELFSELECT_FILL_MODE", os.getenv("FILL_MODE", "proportional")).strip().lower()
if FILL_MODE not in ("proportional", "topup"):
    FILL_MODE = "proportional"
# 補滿時**只用個股**（2026-10-29 使用者裁定）：ETF 只用在閒置資金停泊，不參與選股。


def fill_to_target(strict, ranked_all, fallback, top_n, sel_date=None):
    """`topup` 模式把 `strict` 補到 `top_n`：先補 ranked_all 中未入選者，再用 fallback（動能排序）。

    ⚠️ 只用**個股**補（2026-10-29 使用者裁定：ETF 只用在閒置資金停泊，不參與選股）。
    """
    out = list(strict)[:top_n]
    if FILL_MODE != "topup" or len(out) >= top_n:
        return out
    for sid in ranked_all:
        if len(out) >= top_n:
            break
        if sid not in out:
            out.append(sid)
    for sid in fallback:
        if len(out) >= top_n:
            break
        if sid not in out:
            out.append(sid)
    return out


def pick_high_profit(pool, sel_date, top_n, min_price, mom_days, inst_ok):
    cands = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < min_price:
            continue
        idx = df.index.get_loc(sd)
        ref = float(df.iloc[max(0, idx - mom_days)]["close"])
        r = (cp / ref - 1) if ref > 0 else None
        mp = ma_pos(df, sd, 20)
        if r is None or mp is None or mp < 0:
            continue
        if not inst_ok(sid):
            continue
        if is_overheated(sid, sel_date):   # 人工降溫：過熱(近52週高+高本益比+大漲) → 剔除
            continue
        cands.append((sid, r))
    cands.sort(key=lambda x: -x[1])
    return fill_to_target([s for s, _ in cands[:top_n]], [s for s, _ in cands],
                          _mom_fallback(pool, sel_date, mom_days), top_n, sel_date=sel_date)


def _mom_fallback(pool, sel_date, mom_days=63):
    """補滿用的備援排序：同池、63 日動能（不看過熱/法人；排除資料不足）。"""
    out = []
    for sid in pool:
        df = ssg.load_stock(sid)
        if df is None or not len(df):
            continue
        sd = ssg._snap_date(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        r = ssg.trailing_ret(df, sd, mom_days)
        if r is None:
            continue
        out.append((sid, r))
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out]


def pick_normal(pool, sel_date, top_n, inst_ok):
    scored = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        if not inst_ok(sid):
            continue
        s = ssg.score_stock(sid, df, sd, dict(ssg.DEFAULT_PARAMS))
        if s is None:
            continue
        if is_overheated(sid, sel_date):   # 人工降溫：過熱 → 剔除
            continue
        scored.append(s)
    scored.sort(key=lambda x: -x["total"])
    return fill_to_target([s["symbol"] for s in scored[:top_n]],
                          [s["symbol"] for s in scored],
                          _mom_fallback(pool, sel_date, 63), top_n, sel_date=sel_date)


def gcloud_scp_command(vm: str, zone: str, dest: str) -> list:
    """組出「從 VM 抓回 logs/holdings.json」的 gcloud 指令（純函式，方便測試）。"""
    remote_home = os.getenv("SYNC_VM_HOME", os.getenv("SYNC_VM_PROJECT_DIR", "~/tw-selfselect"))
    return ["gcloud", "compute", "scp",
            f"{vm}:{remote_home}/logs/holdings.json", str(dest),
            "--zone", zone, "--quiet"]


def fetch_holdings_from_vm(dest=None, vm: str = None, zone: str = None,
                          runner=None):
    """從 VM 抓回實盤 `logs/holdings.json` → `(ok, msg)`。

    為什麼（2026-09-22 使用者裁定「以本機流程為主」）：自選股選股日在本機跑（`.env` 在本機維護），
    但持倉判斷必須用**實盤**的 holdings。忘了先 scp 就會用舊資料 ⇒ 可能把**持有中**的股票列為汰換
    ⇒ 照著改 `.env` 之後，實盤孤兒清倉會在下一個交易日開盤把它賣掉。
    本函式把「scp 後必須真的抓到 >0 筆持倉」也驗掉（VM 關機／抓到空檔時必須當失敗）。
    """
    import subprocess
    vm = vm or os.getenv("SYNC_VM_NAME", "my-vm")
    zone = zone or os.getenv("SYNC_VM_ZONE", "asia-east1-b")
    dest = Path(dest or os.path.join("logs", "holdings.json"))
    runner = runner or subprocess.run
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = gcloud_scp_command(vm, zone, str(dest))
    try:
        r = runner(cmd, capture_output=True, text=True)
    except Exception as e:
        return False, f"執行 gcloud scp 失敗（{type(e).__name__}: {e}）"
    if getattr(r, "returncode", 1) != 0:
        err = (getattr(r, "stderr", "") or "").strip()[:300]
        # 2026-10-17：「VM 上沒有 holdings.json」＝**合法狀態（空倉）**，不是失敗
        #   （例如 `reset_paper_trading.py` 從零重來後會清掉它）⇒ 本機補一份空的再繼續。
        #   其他失敗（VM 關機／認證）維持中止。
        if "no such file" in err.lower():
            dest.write_text("{}\n", encoding="utf-8")
            return True, f"VM 上沒有 logs/holdings.json（視為空倉）→ 已建立空的 {dest}"
        return False, f"gcloud scp 失敗（returncode={r.returncode}）{err}"
    if not dest.exists():
        return False, f"scp 回報成功但找不到 {dest}"
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"抓回的 {dest} 無法解析（{type(e).__name__}）"
    held = {k: v for k, v in (data or {}).items()
            if isinstance(v, (int, float, str)) and str(v).isdigit() and int(v) > 0}
    if not held:
        # 2026-10-17：scp 成功就代表 VM 在線、檔案是真的 ⇒ 空倉是**合法狀態**
        #   （例如 `reset_paper_trading.py` 從零重來之後）。但若帳戶其實有持股就是「帳實不符」
        #   ⇒ 一律大聲提醒先對帳，避免把持有中的股票當成不存在。
        return True, (f"已從 {vm} 取回 0 筆持倉（空倉）"
                      f"—— 若玉山帳戶其實有持股，請先跑 scripts/reconcile_broker_books.py 對帳")
    return True, f"已從 {vm} 取回 {len(held)} 筆持倉"


def cap_new_picks(selected, leg_held_count: int, top_n: int, cap_total: bool = True):
    """把「本次要新增的標的」截到 `top_n - 已持倉檔數`（**總數上限 N**，2026-09-22 使用者裁定）。

    為什麼（口徑對齊）：回測 `SWAP_MODE=addonly` 的做法是
      `new = [sid for sid in S if sid not in positions]` → `new = new[:max(0, TOP_N - active)]`
    （`active`＝該腿持股中檔數）⇒ **本腿總檔數維持 N**，不會因為「已持倉又沒被選中」而累積超標。
    實測這個口徑明顯優於 `full`（每月掉出前 N 名就賣）：2015-2025 正常組 +743.9% vs +291.0%、
    2022-2025 +122.5% vs +76.2%；且 N=5 又優於 N=8（+743.9% vs +441.4%）。

    `cap_total=False`（CLI `--no-cap`）＝舊行為：不管已持倉幾檔，一律取前 N 檔新名。
    回傳截斷後的清單。
    """
    if not cap_total:
        return list(selected)
    room = max(0, int(top_n) - int(leg_held_count))
    return list(selected)[:room]


PICKERS = {"high_profit": pick_high_profit, "normal": pick_normal}


# ── 讀目前持股（.env 的 PC_ 條目）──────────────────────
def read_current_holdings():
    holdings = {}
    env_path = Path(os.getenv("DOTENV_PATH", ".env"))
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("PC_") and "=" in s:
                sym = s[3:].split("=", 1)[0]
                val = s.split("=", 1)[1]
                if "#" in val:                 # 去除行內註解（.env 常帶 # 註解→會破壞 JSON）
                    val = val.split("#", 1)[0].strip()
                try:
                    cfg = json.loads(val)
                    holdings[sym] = cfg
                except Exception:
                    holdings[sym] = {"strategy": "?"}
    return holdings


# ── 讀實際持倉（logs/holdings.json 中 qty>0 = 已持倉）────────
def read_actual_holdings():
    """實際持倉 `{代號: 股數}`（>0）——走共用正規化 `core.live_state.held_quantities`。

    ⚠️ 2026-09-22 修 bug：原本只認 `{sym: {"qty": N}}`（舊格式），但實盤寫的是 `{sym: int}`
    ⇒ 這裡永遠回空 dict ⇒「已持倉一律保留」規則失效，把持有中的股票誤列為「賣出（汰換）」。
    """
    from core.live_state import held_quantities, load_json
    return held_quantities(load_json("logs/holdings.json", {}))


def main():
    p = argparse.ArgumentParser(description="每月換股選股工具（高風險/正常）")
    p.add_argument("--risk", choices=["high_profit", "normal"], default="high_profit")
    p.add_argument("--pool-n", type=int, default=None,
                   help="候選池大小；預設＝SELFSELECT_POOL_N ＞ SELFSELECT_PRESET 的池 ＞ 100")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--min-price", type=float, default=5)
    p.add_argument("--mom-days", type=int, default=63)
    p.add_argument("--no-inst", action="store_true", help="關閉法人確認")
    p.add_argument("--inst-days", type=int, default=15)
    p.add_argument("--strategy", choices=["auto", "fixed"], default="auto",
                   help="每檔建議策略: auto=自動感知 / fixed=該組原固定池")
    p.add_argument("--as-of", default=None, help="選股基準日 YYYY-MM-DD（預設=最新交易日）")
    p.add_argument("--sync-holdings-from-vm", action="store_true",
                   help="先從實盤 VM 抓回 logs/holdings.json 再選股（本機流程用；預設不抓）")
    p.add_argument("--vm", default=os.getenv("SYNC_VM_NAME", "my-vm"), help="VM 名稱（--sync-holdings-from-vm 用）")
    p.add_argument("--zone", default=os.getenv("SYNC_VM_ZONE", "asia-east1-b"), help="VM 區域（--sync-holdings-from-vm 用）")
    p.add_argument("--no-cap", action="store_true",
                   help="關閉「總數上限 N」（預設：本腿總檔數維持 N，只補 N−已持倉 檔新名；"
                        "對齊回測 SWAP_MODE=addonly）")
    p.add_argument("--allow-stale-holdings", action="store_true",
                   help="跳過「本機 logs/holdings.json 是否可信」檢查（預設會中止；"
                        "只有在你確定這份 holdings 就是實盤最新狀態時才用）")
    p.add_argument("--ignore-drawback", action="store_true",
                   help="忽略 MIN_DRAW_BACK 回撤保護（預設：回撤超標就本次續抱、exit 3）")
    args = p.parse_args()

    # 池大小解析：--pool-n ＞ SELFSELECT_POOL_N ＞ preset ＞ 100
    if args.pool_n is None:
        env_pool = os.getenv("SELFSELECT_POOL_N")
        args.pool_n = int(env_pool or PRESET_KNOBS.get("POOL_N") or 100)
        _preset_wants = _PRESETS[SELECTION_PRESET]["knobs"]["POOL_N"]
        if SELECTION_PRESET != "current" and str(args.pool_n) != str(_preset_wants):
            print(f"⚠️ preset `{SELECTION_PRESET}` 想要池 {_preset_wants} 檔，但"
                  f"{'`SELFSELECT_POOL_N=' + env_pool + '`' if env_pool else '目前設定'}"
                  f" 讓它變成 {args.pool_n} 檔 ⇒ 回測數字（以池 {_preset_wants} 檔計）不適用在這個池上。"
                  f" 想照 preset：把 .env 的 `SELFSELECT_POOL_N` 改成 {_preset_wants} 或拿掉它。")
        elif SELECTION_PRESET != "current" and not env_pool:
            print(f"ℹ️ 池大小取自 preset `{SELECTION_PRESET}`：{args.pool_n} 檔")

    print(f"🎚️ 選股口徑 preset: {SELECTION_PRESET}（{_PRESETS[SELECTION_PRESET]['label']}）"
          f"｜池 {args.pool_n}｜營收因子 {'開' if FACTOR_REVENUE else '關'}"
          f"｜產業上限 {MAX_PER_SECTOR or '無'}")
    if SELECTION_PRESET == DEFAULT_PRESET:
        print(_preset_warning(is_default=True, name=SELECTION_PRESET))
        print("   ℹ️ 想保守一點：SELFSELECT_PRESET=revenue（+762.4%）或 current（+411.1%）")
    elif SELECTION_PRESET in HIGH_RETURN_PRESETS:
        print(_preset_warning(name=SELECTION_PRESET))

    global data
    data, pools = load_data(args.pool_n)

    # 基準日：最新交易日 ≤ as_of
    if args.as_of:
        as_of = pd.Timestamp(args.as_of)
    else:
        as_of = pd.Timestamp.now()
    all_days = sorted({d for df in data.values() for d in df.index if pd.Timestamp(d) <= as_of})
    sel_date = all_days[-1] if all_days else as_of
    print(f"📅 選股基準日: {pd.Timestamp(sel_date).strftime('%Y-%m-%d')}  (資料: up to 當下, 無前瞻)")

    # 法人確認
    inst = None
    if not args.no_inst:
        inst = ssg.load_twse_inst_merged(refresh_live=True, as_of=sel_date)
        from bisect import bisect_right
        dates = sorted(pd.Timestamp(d) for d in inst)
        idx = bisect_right(dates, sel_date)
        recent = dates[max(0, idx - args.inst_days):idx]
        acc = {}
        for ts in recent:
            for sid2, (b, s) in inst[ts.strftime("%Y-%m-%d")].items():
                acc[sid2] = acc.get(sid2, 0) + (b - s)
        net = pd.Series(acc)
        def inst_ok(sid):
            v = net.get(sid)
            return v is None or v > 0
    else:
        def inst_ok(sid):
            return True

    # 候選池（該季點 ≤ as_of）
    cand_pool = [q for q in sorted(pools) if pd.Timestamp(q + "-01").to_period("M").end_time <= sel_date]
    pool = pools[cand_pool[-1]] if cand_pool else []
    print(f"候選池: 當時市值前 {args.pool_n} 大（{len(pool)} 檔）")

    if args.risk == "high_profit":
        selected = pick_high_profit(pool, sel_date, args.top_n, args.min_price, args.mom_days, inst_ok)
    else:
        if SCORING_MODEL == "zscore":
            selected = pick_zscore(pool, sel_date, args.top_n)
            if _Z_STATS:
                print(f"🔢 zscore 口徑：候選 {_Z_STATS['n_rows']} 檔｜有 PER {_Z_STATS['n_per']} 檔"
                      f"｜有營收 {_Z_STATS['n_rev']} 檔"
                      f"｜營收因子 {'開' if _Z_STATS['rev_on'] else '關'}"
                      f"｜產業上限 {_Z_STATS['cap'] or '無'}"
                      f"｜可排序 {_Z_STATS['n_ranked']} 檔"
                      f"｜實際選出 {len(selected)} 檔")
        else:
            selected = pick_normal(pool, sel_date, args.top_n, inst_ok)

    # ── 先從 VM 抓回實盤持股（本機流程；2026-09-22 使用者裁定以 B 為主）──
    if args.sync_holdings_from_vm:
        _ok, _msg = fetch_holdings_from_vm(vm=args.vm, zone=args.zone)
        print(f"{'✅' if _ok else '❌'} {_msg}")
        if not _ok:
            print("   ⇒ 中止：沒有可信的實盤持股就不能判斷『已持倉一律保留』。")
            print("      （VM 可能已關機；請確認 VM 在線，或手動 gcloud compute scp 後再跑）")
            sys.exit(2)

    # ── 持倉脈絡檢查（2026-09-22 使用者要求「由程式把控」）────────────────
    # 為什麼：在非實盤機跑時 logs/holdings.json 是舊的／空的 ⇒ 「已持倉一律保留」判斷失效，
    #   會把持有中的股票列進「賣出（汰換）」。照著改 .env 之後，實盤的孤兒清倉會在下一個交易日
    #   開盤把它賣掉（繞過策略賣訊）。2026-09-22 實際發生（本機 logs 停在 9/14）。
    from core.live_utils import holdings_context_check
    _hok, _hmsg, _hdetail = holdings_context_check(env_path=Path(os.getenv("DOTENV_PATH", ".env")))
    if not _hok:
        print(f"\n⛔ 持倉資料不可信：{_hmsg}")
        print(f"   檢查結果：{_hdetail}")
        if not args.allow_stale_holdings:
            print("   ⇒ 已中止（避免把持有中的股票誤列為汰換）。請改用實盤機跑：")
            print("      docker exec tw_selfselect_bot python scripts/monthly_rebalance_picker.py "
                  f"--risk {args.risk} --top-n {args.top_n}")
            print("      或先把 VM 的 logs/holdings.json 抓回本機；確定要用本機這份才加 --allow-stale-holdings。")
            sys.exit(2)
        print("   ⚠️ --allow-stale-holdings：仍以本機這份 holdings 繼續（風險自負）")

    current = read_current_holdings()      # .env PC_ 監控/設定中
    _held_qty = read_actual_holdings()     # logs/holdings.json 實際持倉(qty>0)
    held = set(_held_qty)

    # ── MIN_DRAW_BACK 帳戶回撤防護（2026-10-26 接線）────────────────────────
    # 為什麼放在 picker：這裡是「bot 排程（subprocess）」與「手動選股」的共同入口，
    #   呼叫端（monthly_selfselect_run）依 returncode=3 判定「本次續抱、不改 .env」。
    #   舊版只有 core/drawdown_guard.py 的函式、全 repo 沒有呼叫端 ⇒ 實盤等於沒有這道保護。
    if _held_qty:
        try:
            from core.drawdown_guard import mdb_guard
            _pm = {}
            for _s in _held_qty:
                _df = data.get(_s)
                if _df is not None and not getattr(_df, "empty", True):
                    try:
                        _pm[_s] = float(_df["close"].iloc[-1])
                    except Exception:
                        pass
            _blocked, _dd = mdb_guard(_pm, holdings=_held_qty, fallback_loader=ssg.load_stock)
            if _dd is not None:
                print(f"🛡️ MIN_DRAW_BACK 回撤檢查：{_dd:+.1%}")
            if _blocked:
                if args.ignore_drawback:
                    print("⚠️ --ignore-drawback：忽略回撤保護，照常換股（風險自負）")
                else:
                    print("⚠️ 總回撤超過 MIN_DRAW_BACK → 依規則本次續抱：中止選股、不改 .env")
                    print("   （要強制換股：加 --ignore-drawback，或把 MIN_DRAW_BACK 設 0）")
                    sys.exit(3)
        except SystemExit:
            raise
        except Exception as _e:
            print(f"⚠️ MIN_DRAW_BACK 檢查異常（{_e}），照常選股")
    # ── 總數上限 N（2026-09-22 使用者裁定）：本腿總檔數維持 N ──────────────
    # 只算「由選股管理」的持股（keep_wait 條目視為人工管理，不由選股程式汰換）。
    leg_held = sorted(s for s in held if current.get(s, {}).get("strategy") != "keep_wait")
    if not args.no_cap:
        _all_picks = list(selected)
        selected = cap_new_picks(_all_picks, len(leg_held), args.top_n, cap_total=True)
        _dropped = [x for x in _all_picks if x not in selected]
        print(f"\n🔢 總數上限 N={args.top_n}：本腿已持倉 {len(leg_held)} 檔"
              f"{('（' + ', '.join(leg_held) + '）') if leg_held else ''}"
              f" ⇒ 本次只再補 {len(selected)} 檔"
              + (f"；額度外未列入：{', '.join(_dropped)}" if _dropped else ""))
    sel_set = set(selected)
    # 規則：已持倉→不動（保留）；監控中未持倉且未再選中→汰換；新選中未持倉→買入
    # keep_wait 條目視為人工管理，不列入汰換
    sell = sorted([s for s in current if s not in held and s not in sel_set
                   and current[s].get('strategy') != 'keep_wait'])
    keep = sorted(held)                    # 已持倉一律保留（即使掉出選股）
    buy = sorted([s for s in selected if s not in held])

    print(f"\n[{GROUPS[args.risk]['label']}] 選股完成 → 賣出/維持/買入")
    print(f"  🟢 賣出(汰換未持倉且未選中): {sell or '無'}")
    print(f"  🟡 維持(已持倉, 不動): {keep or '無'}")
    print(f"  🔵 買入(新選中未持倉): {buy or '無'}")

    # 每檔: 原固定策略建議 + 用 auto_sensing 路由看當下型態 + 過熱旗標
    print("\n📌 建議策略（'fixed'=原固定池, 'auto'=型態感知自動分派）")
    table = []
    ov_flags = []
    for i, sid in enumerate(selected):
        # ETF 補滿的標的不在候選池的 data 裡 ⇒ 直接載入，否則 price 會是 0
        df = data.get(sid) if data.get(sid) is not None else ssg.load_stock(sid)
        fixed = GROUPS[args.risk]["strats"][i % len(GROUPS[args.risk]["strats"])]
        routed = route_strategy(df, sel_date) if df is not None else "ma_cross"
        name = ssg.POOL_LABELS.get(sid, "")
        sd = snap(df, sel_date) if df is not None else None
        px = float(df.loc[sd, "close"]) if sd is not None else 0.0
        table.append((sid, name, px, fixed, routed))
        ov = overheat_flags(sid, sel_date)
        ov_flags.append((sid, name, ov))
        ov_mark = ""
        if ov:
            parts = []
            if ov["near_high"]: parts.append(f"貼近52週高({ov['pct_from_high']}%)")
            if ov["huge_ytd"]: parts.append(f"YTD+{ov['ytd']}%")
            if ov["high_pe"]: parts.append(f"P/E{ov['per']:.0f}")
            if parts: ov_mark = "  ⚠️ 偏高:" + ",".join(parts)
        print(f"  {sid:>6} {name:<8} NT${px:>8,.0f}  fixed={fixed:<10} auto→{routed}{ov_mark}")

    # 過熱/偏高摘要：列出「被過熱排除」與「選中但偏高(任一旗標)」
    _warned = []
    for sid, name, ov in ov_flags:
        if ov and (ov["near_high"] or ov["huge_ytd"] or ov["high_pe"]):
            _warned.append(f"{sid} {name}(近高{ov['pct_from_high']}% / YTD+{ov['ytd']}% / P/E{ov['per']:.0f})")
    if _warned:
        print(f"\n⚠️ 【人工降溫】選中但偏高（近52週高 / YTD 大漲 / 高本益比，命中任一）：")
        for w in _warned:
            print("   ", w)
    _mode_txt = {1: "任一項(最嚴)", 2: "命中≥2項(預設/較嚴)", 3: "三項全中『且』(最寬)"}[OV_PARAMS["min_count"]]
    print(f"   (過熱嚴格度: {OV_PARAMS['min_count']}項 → {_mode_txt} | 近52週高上限 {OV_PARAMS['max_from_high']}% / "
          f"YTD 上限 {OV_PARAMS['max_ytd']}% / P/E 上限 {OV_PARAMS['max_per']})")

    # 輸出 PC_ 設定（貼進 .env）
    chosen = args.strategy
    # 舊碼固定 `100/N`（5 檔＝每檔 20%、合計 100%）⇒ 再加上其他部位就爆表。
    # 改成用「腿額度 ÷ N」，來源：SELFSELECT_LEG_PCT（本專案只有一條腿 ⇒ 預設 100%）。
    _leg_pct = float(os.getenv("SELFSELECT_LEG_PCT", "100") or 100)
    alloc = round(_leg_pct / max(1, len(selected)), 2)
    print(f"\n📝 可貼進 .env 的 PC_ 設定（strategy={chosen}, 每檔 alloc={alloc}%"
          f"｜腿額度 {_leg_pct:g}% ÷ {len(selected)}）：")
    for sid, name, px, fixed, routed in table:
        strat = chosen if chosen == "auto" else fixed
        line = {'strategy': strat, 'alloc': alloc, 'max_entry_price': round(px, 2)}
        print(f"PC_{sid}={json.dumps(line, separators=(',', ':'))}")
    print("\n💡 strategy=auto 表示該股套用『型態感知自動分派』（strategies/auto_sensing.py，每天開盤前/收盤後計算）。")
    print("   fixed 表示沿用該組固定策略池。alloc 為建議等權資金比例，你可自行調整。")

    # ── 記錄本次建議 + 與上次比對 ──
    record = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "risk": args.risk, "risk_label": GROUPS[args.risk]["label"],
        "as_of": str(sel_date), "strategy_mode": args.strategy,
        "pool_n": args.pool_n, "top_n": args.top_n,
        "inst_days": (0 if args.no_inst else args.inst_days),
        "selected": [{"sid": sid, "name": name, "price": round(px, 2), "fixed": fixed, "auto": routed}
                     for sid, name, px, fixed, routed in table],
        "sell": sell, "keep": keep, "buy": buy, "current": list(current),
    }
    pc_lines = []
    for sid, name, px, fixed, routed in table:
        strat = chosen if chosen == "auto" else fixed
        line = {"strategy": strat, "alloc": alloc, "max_entry_price": round(px, 2)}
        pc_lines.append(f"PC_{sid}={json.dumps(line, separators=(',', ':'))}")
    record["pc_config"] = pc_lines

    prev = None
    if os.path.exists(LAST_PICK_FILE):
        try:
            prev = json.load(open(LAST_PICK_FILE, encoding="utf-8"))
        except Exception:
            prev = None
    if prev:
        p_sids = {x["sid"] for x in prev.get("selected", [])}
        n_sids = {x["sid"] for x in record["selected"]}
        added, removed, same = sorted(n_sids - p_sids), sorted(p_sids - n_sids), sorted(n_sids & p_sids)
        print(f"\n🔄 上次建議（{prev.get('generated_at', '?')}） vs 本次：")
        print(f"  新增: {added or '無'} | 移除: {removed or '無'} | 維持: {same or '無'}")
        for sid in same:
            pr = next((y["auto"] for y in prev["selected"] if y["sid"] == sid), None)
            nr = next((y["auto"] for y in record["selected"] if y["sid"] == sid), None)
            if pr != nr:
                print(f"    {sid} auto 策略: {pr} → {nr}")

    os.makedirs(os.path.dirname(LAST_PICK_FILE) or ".", exist_ok=True)
    with open(LAST_PICK_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已記錄本次建議 → {LAST_PICK_FILE}")


if __name__ == "__main__":
    main()
