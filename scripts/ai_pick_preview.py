#!/usr/bin/env python3
"""scripts/ai_pick_preview.py — 「AI 選股」的預覽／稽核工具（預設**不呼叫**任何模型）

## 它做什麼

1. 依 `--as-of` 重建**當時**的誠實候選池（`core/candidate_pool.build_quarterly_pool`：當時市值前 N）；
2. 為池內每檔建立 **point-in-time 封包**（只用 ≤ as-of 的價格／PER／法人）；
3. 產生 prompt（含硬規則：不得引用資料以外的記憶、必須引用 [R#]）；
4. 把封包、prompt、hash 寫進 `logs/ai_pick/<as_of>/`（可稽核、可重跑）；
5. 若給了 `--llm-cmd`，把 prompt 從 stdin 餵給該指令、收 stdout 當回應，驗證後一起落地。

## 用法

    # 只看封包與 prompt（安全，不呼叫模型）
    .venv/bin/python scripts/ai_pick_preview.py --as-of 2022-01-03 --pool-n 50 --top-n 5

    # 有模型時（任何能「stdin 進、stdout 出」的 CLI；金鑰由你自己的工具管理）
    .venv/bin/python scripts/ai_pick_preview.py --as-of 2022-01-03 \
        --llm-cmd "llm-cli --model my-model --temperature 0"

## 重要限制（務必看）

- LLM 的內部知識**可能包含 as-of 之後的事**，本工具只能保證「提供的資料沒有未來資訊」，
  **無法證明**模型沒用到未來知識 ⇒ 結果是**假設**，不是證據。
- 月營收／新聞目前**沒有**快取或來源，封包一律標 `unavailable`（不憑空生成）。
- 法人資料快取只有少數交易日，缺就標 `null`（不要靠猜）。
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
sys.path.insert(0, _ROOT)

from core.ai_pick import (build_pack, build_prompt, parse_selection,  # noqa: E402
                          assert_no_lookahead, write_audit)


def honest_pool(as_of, pool_n):
    """重建 as_of 當時的誠實池（當時市值前 pool_n）。"""
    import pandas as pd
    from core.cache_io import load_cache_or_raw
    from core.candidate_pool import build_quarterly_pool, load_historical_shares
    import scripts.stock_selector_grid as ssg

    hist, _hs = load_historical_shares()
    data = {}
    for sid in {k[0] for k in hist}:
        df = ssg.load_stock(sid)
        if df is not None and len(df):
            d2 = df.reset_index()
            d2 = d2.rename(columns={d2.columns[0]: "date"})
            data[sid] = d2
    pools = build_quarterly_pool(hist, data, top_n=pool_n)
    cut = pd.Timestamp(as_of)
    cand = [q for q in sorted(pools)
            if pd.Timestamp(q + "-01").to_period("M").end_time <= cut]
    return (pools[cand[-1]] if cand else []), cand[-1] if cand else None


def main():
    ap = argparse.ArgumentParser(description="建立 AI 選股的 point-in-time 封包與 prompt（預設不呼叫模型）")
    ap.add_argument("--as-of", required=True, help="選股日 YYYY-MM-DD（只會用到這天（含）以前的資料）")
    ap.add_argument("--pool-n", type=int, default=50, help="當時市值前 N 大的誠實池（預設 50）")
    ap.add_argument("--top-n", type=int, default=5, help="要求模型選幾檔（預設 5）")
    ap.add_argument("--out-dir", default="logs/ai_pick")
    ap.add_argument("--llm-cmd", default=None, help="把 prompt 從 stdin 餵進去、stdout 當回應的指令（可選）")
    ap.add_argument("--show", action="store_true", help="把 prompt 印出來")
    ap.add_argument("--no-revenue", dest="revenue", action="store_false", default=True,
                    help="不載入月營收（預設會用快取／FinMind 抓一次）")
    ap.add_argument("--no-revenue-fetch", dest="revenue_fetch", action="store_false", default=True,
                    help="只用月營收快取，不連 FinMind")
    ap.add_argument("--news", action="store_true",
                    help="啟用 FinMind 新聞（一檔一天一次呼叫，很貴；預設關）")
    ap.add_argument("--news-lookback", type=int, default=14)
    args = ap.parse_args()

    import pandas as pd
    import scripts.stock_selector_grid as ssg
    from core.cache_io import load_cache_or_raw

    pool, quarter = honest_pool(args.as_of, args.pool_n)
    if not pool:
        print(f"❌ {args.as_of} 找不到當時的候選池")
        return 1
    print(f"選股日 {args.as_of}｜當時池（{quarter} 季點）前 {len(pool)} 檔")

    if args.news:
        os.environ["NEWS_PROVIDER"] = "finmind"
        from core.pit_news import register as _reg_news
        _np = _reg_news()
        _np.lookback_days = args.news_lookback
        print(f"新聞來源：FinMind（lookback {args.news_lookback} 天、cutoff {_np.cutoff}）")
    else:
        os.environ.pop("NEWS_PROVIDER", None)

    inst = ssg.load_twse_inst_merged() or {}
    packs, dropped = [], []
    for sid in pool:
        df = ssg.load_stock(sid)
        if df is None or not len(df) or pd.Timestamp(args.as_of) not in df.index:
            dropped.append(sid)
            continue
        per_series = None
        p = os.path.join("cache", "stock_per", f"per_{sid}.pkl")
        if os.path.exists(p):
            per_series, _ = load_cache_or_raw(p)
        net = {d: sum(b - s for b, s in v.items() if True) for d, v in [] }  # 佔位：法人逐日已在 inst 內
        inst_series = {}
        if inst:
            for d, row in inst.items():
                if sid in row:
                    b, s = row[sid]
                    inst_series[d] = b - s
        rev_rows = None
        if args.revenue:
            try:
                from core.pit_data import load_revenue_rows
                rev_rows = load_revenue_rows(sid, fetch=args.revenue_fetch)
            except Exception:
                rev_rows = None
        pack = build_pack(sid, args.as_of, price_df=df, inst_series=inst_series, per_series=per_series,
                          extra={"quarter_point": quarter}, revenue_rows=rev_rows)
        assert_no_lookahead(pack, args.as_of)
        packs.append(pack)

    print(f"封包 {len(packs)} 檔（{len(dropped)} 檔當日無價格 → 略過）")
    prompt = build_prompt(packs, top_n=args.top_n)
    if args.show:
        print("\n" + prompt + "\n")

    response = None
    if args.llm_cmd:
        print(f"呼叫模型：{args.llm_cmd}")
        r = subprocess.run(args.llm_cmd, shell=True, input=prompt, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"❌ 模型呼叫失敗（rc={r.returncode}）：{(r.stderr or '').strip()[:300]}")
            write_audit(args.out_dir, args.as_of, packs, prompt, None, model=args.llm_cmd)
            return 1
        response = r.stdout
        picks = parse_selection(response, pool=[p["sid"] for p in packs], top_n=args.top_n)
        print("✅ 模型輸出通過驗證：" + "、".join(p["sid"] for p in picks["picks"]))
    meta = write_audit(args.out_dir, args.as_of, packs, prompt, response,
                      model=args.llm_cmd or "(未呼叫)", extra={"quarter_point": quarter})
    print(f"稽核檔已寫入 {os.path.join(args.out_dir, args.as_of)}｜pack_sha256 {meta['pack_sha256'][:16]}…")
    if not args.llm_cmd:
        print("（未呼叫模型：這是「封包＋prompt」預覽。要真的選股請給 --llm-cmd）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
