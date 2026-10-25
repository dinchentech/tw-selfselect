#!/usr/bin/env python3
"""重建 `cache/inst_momentum/mcap_ranking.pkl`（上市普通股市值排名）

## 為什麼需要這支工具

實盤選股的**候選池**來自這份排名（`stock_selector_grid.build_candidate_pool`、
法人動能 `core/inst_data`），但 **repo 內沒有任何產生器**（cairn 記載「寫入者在外部/加密程式」），
檔案因此凍結：2026-09-18 實測 **VM 6/26、本機 6/30**（落後約 2.8 個月）。

後果（2026-09-18 實證）：8/31 即使價格是新鮮的，凍結池仍會選出 **2059 川湖第一**
（2059 當時距高點只剩 −2.1% ⇒ 一進場就套），而用「**當時**真實市值前 100」會選出
**3406 玉晶光 / 6213 聯茂 / 3008 大立光**（動能都 +90% 以上）—— 池子太舊 ⇒
新進榜的高動能股**根本不在候選名單裡** ⇒ 只能從老面孔挑 ⇒ **系統性追高**。
回測用的正是「當時市值前 100」（誠實逐季池），所以池子不更新＝**實盤與回測口徑不一致**。

## 資料源（TWSE OpenAPI，免 token、全市場一次抓）

- 股數：`opendata/t187ap03_L` 的「已發行普通股數或TDR原股發行股數」
- 收盤：`exchangeReport/STOCK_DAY_ALL` 的 `ClosingPrice`
- **市值 = 發行股數 × 收盤價**；只取 4 碼且非 `00` 開頭（排除 ETF/ETN，與舊檔組成一致）

## 用法

    .venv/bin/python scripts/rebuild_mcap_ranking.py            # dry-run（預設，不寫檔）
    .venv/bin/python scripts/rebuild_mcap_ranking.py --apply    # 寫入（先備份舊檔）
    .venv/bin/python scripts/rebuild_mcap_ranking.py --top 100  # 報告用前 N 名（預設 100）

⚠️ 寫入會**改變實盤選股結果**（候選池變了）⇒ 預設 dry-run；要生效需把檔案同步到 VM
   （VM 的 `cache/` 是獨立掛載，本機改了 VM 不會跟著變）。
"""
import argparse
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.cache_io import dump_cache, load_cache_or_raw, read_ranking_codes  # noqa: E402

RANKING = os.path.join(_ROOT, "cache", "inst_momentum", "mcap_ranking.pkl")
URL_SHARES = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
URL_CLOSE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def read_codes_any(path):
    """讀回剛寫出的排名（驗證用；兩種格式都吃）。"""
    return read_ranking_codes(path)


def fetch_json(url, timeout=30):
    """抓 TWSE OpenAPI（回傳 list[dict]）。失敗一律拋錯 —— 寧可大聲失敗也不要寫出假池。"""
    req = urllib.request.Request(url, headers={"User-Agent": "tw-autotrader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{url} 回傳非預期格式（{type(data).__name__}）")
    return data


NAMES_CACHE = os.path.join(_ROOT, "cache", "stock_names.pkl")


def parse_names(rows):
    """[{t187ap03_L}] → {代號: 公司簡稱}（免 token、無次數限制 ⇒ 供名稱快取用）。"""
    out = {}
    for r in rows:
        sid = str(r.get("公司代號", "")).strip()
        name = str(r.get("公司簡稱", "")).strip()
        if sid.isdigit() and len(sid) == 4 and name:
            out[sid] = name
    return out


def save_names(names):
    """寫 cache/stock_names.pkl（供 `stock_selector_grid.POOL_LABELS` 在 FinMind 限流時救援）。"""
    if not names:
        return 0
    dump_cache(NAMES_CACHE, names,
               meta={"source": "TWSE_openapi_t187ap03_L", "count": len(names)})
    return len(names)


def parse_shares(rows):
    """[{t187ap03_L}] → {代號: 發行股數(int)}"""
    out = {}
    for r in rows:
        sid = str(r.get("公司代號", "")).strip()
        raw = str(r.get("已發行普通股數或TDR原股發行股數", "")).replace(",", "").strip()
        if not sid or not raw.isdigit():
            continue
        out[sid] = int(raw)
    return out


def parse_closes(rows):
    """[{STOCK_DAY_ALL}] → ({代號: 收盤價(float)}, 資料日)"""
    out, day = {}, None
    for r in rows:
        sid = str(r.get("Code", "")).strip()
        raw = str(r.get("ClosingPrice", "")).replace(",", "").strip()
        if day is None and r.get("Date"):
            d = str(r["Date"]).strip()                    # 民國 YYMMDD，例 1150916
            if len(d) == 7 and d.isdigit():
                day = f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:]}"
        try:
            px = float(raw)
        except ValueError:
            continue
        if sid and px > 0:
            out[sid] = px
    return out, day


def rank_market_cap(shares, closes):
    """→ [(代號, 市值億)] 依市值由大到小。

    只留 4 碼、非 `00` 開頭（排除 ETF/ETN，與舊檔一致），且股數/價格都取得到。
    """
    caps = {}
    for sid, sh in shares.items():
        if not (sid.isdigit() and len(sid) == 4) or sid.startswith("00"):
            continue
        px = closes.get(sid)
        if not px or sh <= 0:
            continue
        caps[sid] = sh * px / 1e8                          # 億元
    return sorted(caps.items(), key=lambda kv: -kv[1])


def main():
    ap = argparse.ArgumentParser(description="重建市值排名快取（候選池來源）")
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設 dry-run）")
    ap.add_argument("--top", type=int, default=100, help="報告用前 N 名（預設 100）")
    ap.add_argument("--names-only", action="store_true",
                    help="只更新股票名稱快取 cache/stock_names.pkl（不重建排名）")
    ap.add_argument("--emit", default="", help="另外輸出到指定路徑（不碰正式快取；供同步到 VM 用）")
    ap.add_argument("--legacy-list", action="store_true",
                    help="輸出成舊版「裸 list」pickle（給還沒 deploy 新讀取器的機器用；"
                         "v4.24 的 core/inst_data 用裸 pickle.loads 讀，收到 v2 dict 會靜默退假池）")
    args = ap.parse_args()

    print("📥 抓 TWSE OpenAPI（發行股數 + 當日收盤）...")
    _shr_rows = fetch_json(URL_SHARES)
    shares = parse_shares(_shr_rows)
    _n = save_names(parse_names(_shr_rows))
    print(f"   名稱快取：{NAMES_CACHE}（{_n} 檔）")
    if args.names_only:
        print("✅ 只更新名稱快取，結束。")
        return 0
    closes, day = parse_closes(fetch_json(URL_CLOSE))
    ranked = rank_market_cap(shares, closes)
    new_list = [s for s, _ in ranked]
    print(f"   股數 {len(shares)} 檔、收盤 {len(closes)} 檔 → 可用 {len(ranked)} 檔（資料日 {day}）")

    old, old_meta = (None, {})
    if os.path.exists(RANKING):
        old, old_meta = load_cache_or_raw(RANKING)
        if isinstance(old, dict):
            old = old.get("data") or old.get("ranking") or []
    old = [str(s) for s in (old or [])]
    print(f"   現有排名 {len(old)} 檔（舊格式 meta: {old_meta or '（無）'}）")

    n = args.top
    print(f"\n{'=' * 70}\n📊 新排名前 {n} 大（市值，億元）\n{'=' * 70}")
    for i, (sid, cap) in enumerate(ranked[:20], 1):
        mark = "" if sid in old[:n] else "  ← 新進榜"
        print(f"  {i:>3}. {sid} {cap:>10,.0f} 億{mark}")

    if old:
        in_new = [s for s in new_list[:n] if s not in old[:n]]
        out_old = [s for s in old[:n] if s not in new_list[:n]]
        print(f"\n前 {n} 名變動：**新進 {len(in_new)} 檔、掉出 {len(out_old)} 檔**")
        print(f"  新進：{'、'.join(in_new) if in_new else '（無）'}")
        print(f"  掉出：{'、'.join(out_old) if out_old else '（無）'}")
        old_rank = {s: i + 1 for i, s in enumerate(old)}
        new_rank = {s: i + 1 for i, s in enumerate(new_list)}
        moved = [(s, old_rank.get(s), new_rank.get(s)) for s in new_list[:n] if s in old_rank]
        big = sorted(moved, key=lambda t: -(t[1] - t[2]))[:5]
        if big:
            print("  名次躍升前 5：" + "、".join(f"{s} #{o}→#{nw}" for s, o, nw in big))

    # 現有 .env 持股目前的排名（放進來才看得出「還在不在前 100」）
    try:
        held = []
        for line in open(os.path.join(_ROOT, ".env"), encoding="utf-8"):
            if line.startswith("PC_") and "=" in line:
                held.append(line.split("=", 1)[0].replace("PC_", "").strip())
        rk = {s: i + 1 for i, s in enumerate(new_list)}
        if held:
            print("\n.env 現有標的的新排名：" + "、".join(
                f"{s}{'#' + str(rk[s]) if s in rk else '(不在排名內)'}" for s in held))
    except FileNotFoundError:
        pass

    if args.emit:
        import pickle as _pkl
        if args.legacy_list:
            with open(args.emit, "wb") as f:
                _pkl.dump(new_list, f)
        else:
            dump_cache(args.emit, new_list,
                       meta={"source": "TWSE_openapi", "data_date": day, "count": len(new_list)})
        back = read_codes_any(args.emit)
        assert back == new_list, "emit 寫後驗證失敗"
        print(f"\n📤 已輸出：{args.emit}"
              f"（{len(new_list)} 檔，{'裸 list 舊格式' if args.legacy_list else 'v2 格式'}）")

    if not args.apply:
        print("\n🔎 dry-run：未寫入正式快取。確認無誤後加 `--apply`。")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    if os.path.exists(RANKING):
        bak = f"{RANKING}.bak-{ts}"
        shutil.copy2(RANKING, bak)
        print(f"\n🗄️ 舊檔備份：{bak}")
    dump_cache(RANKING, new_list,
               meta={"source": "TWSE_openapi_t187ap03_L_x_STOCK_DAY_ALL",
                     "data_date": day, "count": len(new_list),
                     "rebuilt_at": datetime.now().isoformat(timespec="seconds")})
    back, meta = load_cache_or_raw(RANKING)
    assert back and len(back) == len(new_list), "寫後驗證失敗"
    print(f"✅ 已寫入 {RANKING}（{len(new_list)} 檔，資料日 {day}）")
    print("⚠️ VM 的 cache 是獨立掛載 ⇒ 要生效需另外同步到 VM（並確認選股結果合理）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
