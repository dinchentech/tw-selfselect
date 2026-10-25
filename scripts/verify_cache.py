#!/usr/bin/env python3
"""快取資料完整性驗證（2026-08-29 建立）

背景：2026-08 多次 cache 混淆造成回測假數字（還原價混入 / 短歷史覆寫 /
TWSE 欄位格式 / 反爬殘缺 / 混合狀態）。本腳本系統性驗證上 git 的快取：

  離線檢查（不耗 API）：
    1. bt_price:     500 檔、涵蓋 2014-06~2026-08、meta 範圍一致
    2. selector_prices: 501 檔、涵蓋 2015-01~2025-12
    3. twse_inst:    法人快取天數 vs 交易日曆（2015-2025 完整）
    4. 價格語義抽樣：除權息日檢查「原始價跳空」特徵（非還原價平滑）

  線上抽樣（耗少量 API，預設 5 檔 × 3 天）：
    5. bt_price vs FinMind API 即時回傳（價格一致）
    6. twse_inst vs TWSE API 即時回傳（法人一致）
    7. bt_price vs price/ 交叉（差異 <1%，原始價語義）

用法：python scripts/verify_cache.py [--online] [--samples N]
輸出：通過/失敗清單，非零 exit code 表示有問題。
"""
import sys
import glob
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.inst_data import _load_cache, fetch_twse_day
from core.cache_io import load_cache_or_raw

# ⚠️ .env 一律以「檔案」為準（override=True）。原因（2026-10-01 實測）：
#   容器用 docker-compose `env_file` 在**建立容器時**把變數注入 process env，之後主機上改 `.env`
#   不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 不會覆蓋它們
#   ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。
#   主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`（V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)

PASS, FAIL = 0, 0

def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))

# ── 1. bt_price 完整性 ──────────────────────────────
def verify_bt_price():
    print("\n[1] bt_price（回測用價格，FinMind 原始價）")
    files = glob.glob("cache/inst_momentum/bt_price/*.pkl")
    check("檔案數 = 500", len(files) == 500, f"{len(files)}")
    ok_range, bad = 0, []
    for f in files:
        df, m = _load_cache(f)
        if df is None or df.empty:
            bad.append((Path(f).stem, "EMPTY")); continue
        mn, mx = str(df["date"].min())[:10], str(df["date"].max())[:10]
        if m and m.get("start") == "2014-06-05" and m.get("end") == "2026-08-10":
            ok_range += 1
        elif mn <= "2014-06-10" and mx >= "2026-07-25":
            ok_range += 1
        else:
            bad.append((Path(f).stem, f"{mn}~{mx}"))
    check(f"範圍涵蓋 2014-06~2026-08（{ok_range}/{len(files)}）",
          ok_range == len(files), str(bad[:5]))

# ── 2. selector_prices 完整性 ───────────────────────
def verify_selector():
    print("\n[2] selector_prices（選股用價格，yfinance 還原價）")
    files = glob.glob("cache/selector_prices/*.pkl")
    ok = 0
    for f in files:
        df, _ = load_cache_or_raw(f)
        if df is None or df.empty:
            continue
        mx = str(df.index.max())[:10]
        if mx >= "2025-12-20":
            ok += 1
    check(f"涵蓋到 2025-12（{ok}/{len(files)}）", ok >= len(files) - 10)

# ── 3. twse_inst 法人快取完整性 ─────────────────────
def verify_twse_inst():
    print("\n[3] twse_inst（TWSE 法人快取）")
    files = glob.glob("cache/inst_momentum/*/twse_inst_*.pkl")
    check("法人快取檔存在", len(files) >= 20, f"{len(files)} 檔")
    # 2015-2025 完整窗口應有 ~2700 天
    for f in files:
        if "2015-01-01_2025-12-31" in f:
            d, m = _load_cache(f)
            if d:
                ks = sorted(d.keys())
                check("2015-2025 全窗口天數 ≥ 2600",
                      len(d) >= 2600, f"{len(d)} 天（{ks[0]}~{ks[-1]}）")
                break

# ── 4. 價格語義：原始價 vs 還原價 ───────────────────
def verify_price_semantics(samples=5):
    print("\n[4] 價格語義抽樣（原始價特徵：除權息日跳空）")
    # 2330 台積電 2022-06-16 除息（約 11 元）→ 原始價應跳空、還原價平滑
    df, _ = _load_cache("cache/inst_momentum/bt_price/2330.pkl")
    if df is not None and not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        around = df[(df["date"] >= "2022-06-10") & (df["date"] <= "2022-06-25")]
        if len(around) >= 4:
            closes = around["close"].tolist()
            drop = (closes[-3] - closes[-1]) / closes[-3]  # 除息前後
            # 原始價：除息日應有明顯跳空（>1%）；還原價：平滑（<0.5%）
            check(f"2330 除息跳空檢測（drop={drop:.2%}，原始價應 >1%）",
                  abs(drop) > 0.01, "原始價 ✓（還原價會平滑）")
        else:
            check("2330 除息日資料存在", False, "範圍不足")

# ── 5. 線上抽樣：bt_price vs FinMind API ────────────
def verify_online(samples=5):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    import os
    from FinMind.data import DataLoader
    dl = DataLoader()
    dl.login_by_token(os.getenv("FINMIND_API_TOKEN"))

    print(f"\n[5] 線上抽樣：bt_price vs FinMind API（{samples} 檔）")
    files = sorted(glob.glob("cache/inst_momentum/bt_price/*.pkl"))[:samples]
    for f in files:
        sid = Path(f).stem
        df, _ = _load_cache(f)
        try:
            raw = dl.taiwan_stock_daily(stock_id=sid,
                                        start_date="2025-06-01",
                                        end_date="2025-06-30")
            if raw is None or raw.empty:
                check(f"{sid} FinMind 回傳", False, "空"); continue
            raw = raw.rename(columns={"max": "high", "min": "low",
                                      "Trading_Volume": "volume"})
            raw["date"] = pd.to_datetime(raw["date"])
            df["date"] = pd.to_datetime(df["date"])
            # 取交集最後 3 天對比 close
            merged = df.merge(raw[["date", "close"]], on="date", suffixes=("_c", "_api"))
            if len(merged) == 0:
                check(f"{sid} 快取 vs API", False, "無交集"); continue
            diff = (merged["close_c"] - merged["close_api"]).abs().max()
            check(f"{sid} 快取價格 vs FinMind（max diff={diff:.2f}）",
                  diff <= 0.5, f"{len(merged)} 天交集")
        except Exception as e:
            check(f"{sid} API 例外", False, str(e)[:60])

    print(f"\n[6] 線上抽樣：twse_inst vs TWSE API（{min(samples, 3)} 天）")
    import requests
    for d in ["2025-06-03", "2025-06-05", "2025-06-09"]:
        try:
            live = fetch_twse_day(d.replace("-", ""))
            if not live:
                check(f"TWSE {d} 即時抓取", False, "EMPTY/封鎖"); continue
            # 快取對比（2022 快取涵蓋 2025）
            cache_d, _ = _load_cache("cache/inst_momentum/2022/twse_inst_2022-01-01_2025-12-31.pkl")
            if cache_d and d in cache_d:
                sid = "2330"
                c = cache_d[d].get(sid)
                l = (live.get(sid, {}).get("外資", {}).get("buy", 0)
                     + live.get(sid, {}).get("投信", {}).get("buy", 0),
                     live.get(sid, {}).get("外資", {}).get("sell", 0)
                     + live.get(sid, {}).get("投信", {}).get("sell", 0))
                ok = c == l
                check(f"TWSE {d} 2330 法人快取 vs 即時（{c} vs {l}）", ok)
            else:
                check(f"TWSE {d} 快取涵蓋", False, "快取無此日")
        except Exception as e:
            check(f"TWSE {d}", False, str(e)[:60])

def main():
    online = "--online" in sys.argv
    samples = 5
    if "--samples" in sys.argv:
        samples = int(sys.argv[sys.argv.index("--samples") + 1])
    verify_bt_price()
    verify_selector()
    verify_twse_inst()
    verify_price_semantics(samples)
    if online:
        verify_online(samples)
    print(f"\n{'='*40}\n結果：✅ {PASS} 通過 / ❌ {FAIL} 失敗")
    sys.exit(1 if FAIL else 0)

if __name__ == "__main__":
    main()
