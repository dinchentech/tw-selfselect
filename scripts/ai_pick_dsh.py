#!/usr/bin/env python3
"""scripts/ai_pick_dsh.py — 「在 DSH 對話框貼日期，就用 DSH 目前的模型選股」的雙步驟工具

## 為什麼是兩步

DSH（這個對話介面）本身就是模型：**不需要另外設定 API 金鑰**，你在 DSH 裡換模型就等於換選股模型。
但模型不能自己去讀磁碟，所以流程切成兩步、中間用檔案銜接：

    ┌─ 步驟 1（在你貼日期後，助理執行）──────────────────────────────┐
    │  ai_pick_dsh.py --as-of <日期> --emit prompt                  │
    │  → 重建「當時」的誠實池、建立 point-in-time 封包、印出 prompt   │
    │  → 同時把封包落地 logs/ai_pick/<日期>/pack.json（稽核用）        │
    └───────────────────────────────────────────────────────────────┘
    ┌─ 步驟 2（助理依 prompt 只用封包資料作答）─────────────────────┐
    │  ai_pick_dsh.py --as-of <日期> --picks '<模型回傳的 JSON>'     │
    │  → parse_selection 驗證（不得新增標的、要引用 [R#]、數量要對） │
    │  → 寫 logs/ai_pick/<日期>/response.json＋audit.json            │
    └───────────────────────────────────────────────────────────────┘

之後 `ai_pick_ab.py --reuse` 會直接吃 `response.json`，把這次選股納入 AI vs 規則的統計，
不需要任何 API、不需要重跑模型。

## 用法

    # 1) 產生 prompt（給 DSH 的模型看）
    .venv/bin/python scripts/ai_pick_dsh.py --as-of 2022-01-03 --pool-n 50 --top-n 5 --emit prompt

    # 2) 把模型的 JSON 落地（--model 只是標記，換 DSH 模型時改字串就好）
    .venv/bin/python scripts/ai_pick_dsh.py --as-of 2022-01-03 --top-n 5 \
        --picks '{"as_of":"2022-01-03","picks":[{"sid":"2330","reasons":["…[R1]"],"citations":["R1"]}]}' \
        --model "dsh:deepseek-flash"

    # 3) 納入 A/B（沿用稽核檔）
    .venv/bin/python scripts/ai_pick_ab.py --start 2022-01-01 --end 2022-12-31 --reuse --require-full

## 口徑與限制（與 `cairn/ai-stock-selection.md` 一致）

- 封包只含 **≤ 選股日 13:30** 的資料（價格／PER／法人／月營收；新聞需 `--news`）。
- `assert_no_lookahead()` 會擋掉任何晚於選股日的欄位；封包與 prompt 一律落地可稽核。
- **模型本身的記憶無法被證明沒有先見之明** → 這些選股是「假設」，要當證據得靠 A/B 累積 ≥30 個選股日。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

from core.ai_pick import (assert_no_lookahead, build_pack, build_prompt,  # noqa: E402
                          parse_selection, write_audit)


def load_pool_data(as_of, pool_n):
    """重建 as_of 當時的誠實池與每檔的 point-in-time 封包。"""
    import pandas as pd
    import scripts.stock_selector_grid as ssg
    from core.cache_io import load_cache_or_raw
    from core.candidate_pool import build_quarterly_pool, load_historical_shares
    from core.pit_data import load_revenue_rows

    hist, _hs = load_historical_shares()
    rows, px = {}, {}
    for sid in sorted({k[0] for k in hist}):
        df = ssg.load_stock(sid)
        if df is None or not len(df):
            continue
        px[sid] = df
        d2 = df.reset_index()
        rows[sid] = d2.rename(columns={d2.columns[0]: "date"})
    pools = build_quarterly_pool(hist, rows, top_n=pool_n)
    cut = pd.Timestamp(as_of)
    cand = [q for q in sorted(pools) if pd.Timestamp(q + "-01").to_period("M").end_time <= cut]
    return (pools[cand[-1]] if cand else []), (cand[-1] if cand else None), px


def build_packs(as_of, pool, px, ssg, with_revenue=True, news=False, news_lookback=14):
    import pandas as pd
    from core.pit_data import load_revenue_rows

    inst = ssg.load_twse_inst_merged() or {}
    from core.cache_io import load_cache_or_raw

    packs = []
    for sid in pool:
        df = px.get(sid)
        if df is None or pd.Timestamp(as_of) not in df.index:
            continue
        per_series = None
        p = os.path.join("cache", "stock_per", f"per_{sid}.pkl")
        if os.path.exists(p):
            per_series, _ = load_cache_or_raw(p)
        inst_series = {}
        for d, row in inst.items():
            if sid in row:
                b, s = row[sid]
                inst_series[d] = b - s
        rev = load_revenue_rows(sid) if with_revenue else None
        pack = build_pack(sid, as_of, price_df=df, inst_series=inst_series or None,
                          per_series=per_series, revenue_rows=rev)
        assert_no_lookahead(pack, as_of)
        packs.append(pack)
    return packs


def main():
    ap = argparse.ArgumentParser(description="DSH 對話內選股：產生 prompt 或落地模型回答")
    ap.add_argument("--as-of", required=True, help="選股日 YYYY-MM-DD")
    ap.add_argument("--pool-n", type=int, default=50, help="當時市值前 N 大的誠實池")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--emit", choices=["prompt", "pack", "none"], default="prompt")
    ap.add_argument("--picks", default=None, help="模型回傳的 JSON 字串（步驟 2）")
    ap.add_argument("--picks-file", default=None, help="模型回傳的 JSON 檔（步驟 2）")
    ap.add_argument("--model", default=os.getenv("DSH_MODEL", "dsh:current"),
                    help="只做標記用（你在 DSH 換模型時改這個字串，稽核才知道是哪個模型選的）")
    ap.add_argument("--audit-dir", default="logs/ai_pick")
    ap.add_argument("--no-revenue", dest="revenue", action="store_false", default=True)
    ap.add_argument("--news", action="store_true", help="啟用 FinMind 新聞（很貴，預設關）")
    ap.add_argument("--news-lookback", type=int, default=14)
    ap.add_argument("--apply-env", action="store_true",
                    help="驗證通過後立刻把這份名單寫進 .env（走 monthly_selfselect_run 的安全檢查）")
    ap.add_argument("--sync-env-to-vm", action="store_true", help="寫入後一併同步 .env 到 VM")
    ap.add_argument("--env", default=".env", help="--apply-env 要寫的 .env 路徑")
    args = ap.parse_args()

    import scripts.stock_selector_grid as ssg

    day_dir = os.path.join(args.audit_dir, args.as_of)
    pack_path = os.path.join(day_dir, "pack.json")

    # ── 步驟 2：把模型的回答落地（優先；不重建封包，直接讀 pack.json）──
    if args.picks or args.picks_file:
        if not os.path.exists(pack_path):
            print(f"❌ 找不到封包 {pack_path}；請先跑 --emit prompt 產生（避免選股日與封包不一致）")
            return 1
        with open(pack_path, encoding="utf-8") as f:
            doc = json.load(f)
        packs = doc.get("packs") or []
        pool = [p["sid"] for p in packs]
        text = args.picks if args.picks else open(args.picks_file, encoding="utf-8").read()
        try:
            obj = parse_selection(text, pool=pool, top_n=args.top_n)
        except Exception as e:
            print(f"❌ 模型輸出不合格：{e}")
            return 2
        prompt = ""
        pp = os.path.join(day_dir, "prompt.txt")
        if os.path.exists(pp):
            prompt = open(pp, encoding="utf-8").read()
        meta = write_audit(args.audit_dir, args.as_of, packs, prompt,
                           json.dumps(obj, ensure_ascii=False), model=args.model,
                           extra={"quarter_point": doc.get("extra", {}).get("quarter_point")})
        print("✅ 通過驗證並落地：" + "、".join(p["sid"] for p in obj["picks"]))
        print(f"   稽核：{day_dir}（model={args.model}｜pack_sha256 {meta['pack_sha256'][:16]}…）")
        print(f"   納入 A/B：.venv/bin/python scripts/ai_pick_ab.py --start {args.as_of} "
              f"--end {args.as_of} --pool-n <同值> --top-n {args.top_n} --reuse")
        if args.apply_env:
            sids = ",".join(p["sid"] for p in obj["picks"])
            cmd = [sys.executable, os.path.join("scripts", "monthly_selfselect_run.py"),
                   "--picks", sids, "--top-n", str(args.top_n), "--ai", "--apply",
                   "--env", args.env]
            if args.sync_env_to_vm:
                cmd.append("--sync-env-to-vm")
            print("\n▶ 寫入 .env：" + " ".join(cmd))
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            print(r.stdout[-4000:] if r.stdout else "")
            if r.returncode != 0:
                print(r.stderr[-1500:] if r.stderr else "")
                print(f"❌ 寫入 .env 失敗（rc={r.returncode}）；AI 名單已落地在稽核檔，稍後可重跑 --apply-env")
                return 3
        return 0

    # ── 步驟 1：重建封包並輸出 prompt ──
    pool, quarter, px = load_pool_data(args.as_of, args.pool_n)
    if not pool:
        print(f"❌ {args.as_of} 找不到當時的候選池（資料不足或非交易日）")
        return 1
    if args.news:
        os.environ["NEWS_PROVIDER"] = "finmind"
        from core.pit_news import register as _reg
        _np = _reg()
        _np.lookback_days = args.news_lookback
        print(f"新聞來源：FinMind（lookback {args.news_lookback} 天、cutoff {_np.cutoff}）")
    packs = build_packs(args.as_of, pool, px, ssg, with_revenue=args.revenue, news=args.news)
    if len(packs) < args.top_n:
        print(f"❌ 封包只有 {len(packs)} 檔 < top_n={args.top_n}")
        return 1
    prompt = build_prompt(packs, top_n=args.top_n)
    write_audit(args.audit_dir, args.as_of, packs, prompt, None, model=args.model,
                extra={"quarter_point": quarter})
    print(f"選股日 {args.as_of}｜當時池（{quarter} 季點）前 {args.pool_n} 檔｜封包 {len(packs)} 檔"
          f"｜封包已存 {pack_path}")
    print(f"（下一步：把下面 prompt 交給模型，再用 --picks 把 JSON 貼回來；"
          f"模型標記 --model {args.model}）\n")
    if args.emit == "prompt":
        print(prompt)
    elif args.emit == "pack":
        print(json.dumps({"as_of": args.as_of, "packs": packs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
