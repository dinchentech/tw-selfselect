#!/usr/bin/env python3
"""scripts/ai_pick_ab.py — AI 選股 vs 純規則的 A/B 實測（可離線跑規則組，AI 組需 `--llm-cmd`）

## 它做什麼

對一串「選股日」：
1. 重建**當時**的誠實池（`build_quarterly_pool`，市值前 N）；
2. 產生 point-in-time 封包（價格／PER／法人／月營收；新聞預設留空）；`assert_no_lookahead` 把關；
3. **規則組**：用本專案的評分（`ssg.score_stock`）＋過熱剔除排出前 `top_n`（與實盤 `pick_normal` 同精神）；
4. **AI 組**：有 `--llm-cmd` 就呼叫模型（prompt 從 stdin 進、JSON 從 stdout 出），
   沒有就沿用既有稽核檔（`--reuse`）或標成缺席；
5. 用**還原價**算 1/3/6/12 個月後的等權報酬，做配對比較（`core.ai_pick_ab.summarize`）。

## 用法

    # 先看規則組能跑、日期與池子正確（完全離線）
    .venv/bin/python scripts/ai_pick_ab.py --start 2022-01-01 --end 2022-12-31 --pool-n 50 --top-n 5

    # 接上模型做真的 A/B
    .venv/bin/python scripts/ai_pick_ab.py --start 2022-01-01 --end 2024-12-31 \
        --llm-cmd "my-llm-cli --model x" --out results/ai_ab.json

## 誠實提醒

- 這是「**選股能力**」的比較：不含交易成本、不含進出場策略（回測那邊才算總報酬）。
- LLM 可能用訓練語料裡的未來資訊；封包只保證「供給的資料」沒有未來，**無法證明**模型沒用未來知識。
- 樣本 < 10 個選股日時，`summarize()` 會直接標「勿下結論」。
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

from core.ai_pick import build_pack, build_prompt, parse_selection, assert_no_lookahead, write_audit  # noqa: E402
from core.ai_pick_ab import basket_return, eligible_for_compare, forward_return, summarize  # noqa: E402


def _log(msg):
    print(msg, flush=True)


def honest_pool(as_of, pool_n, hist, data_rows, ssg):
    """as_of 當時的誠實池（季度點收盤市值前 pool_n）。"""
    import pandas as pd
    from core.candidate_pool import build_quarterly_pool, load_historical_shares

    pools = build_quarterly_pool(hist, data_rows, top_n=pool_n)
    cut = pd.Timestamp(as_of)
    cand = [q for q in sorted(pools) if pd.Timestamp(q + "-01").to_period("M").end_time <= cut]
    return (pools[cand[-1]] if cand else []), (cand[-1] if cand else None)


def _mom_fallback(pool, as_of, ssg, exclude=()):
    """補滿用的備援排序：同池、63 日動能（與回測 `_fallback_rank()` 同精神）。"""
    import pandas as pd

    out = []
    for sid in pool:
        if sid in exclude:
            continue
        df = ssg.load_stock(sid)
        if df is None or not len(df):
            continue
        cut = pd.Timestamp(as_of)
        sd = pd.Timestamp(ssg._snap_date(df, cut))
        if sd is None or sd not in df.index:
            continue
        r = ssg.trailing_ret(df, sd, 63)
        if r is None:
            continue
        out.append((sid, r))
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out]


def rules_picks(pool, as_of, top_n, ssg, inst=None, overheat=True, fill_mode="proportional"):
    """規則組：`ssg.score_stock` 打分 → 過熱剔除 → 取前 top_n（與 `pick_normal` 同精神）。

    `fill_mode="topup"`：不足 N 檔時先補「被過熱擋掉」的，再依 63 日動能補滿（與回測 `FILL_MODE` 同義）。
    """
    import pandas as pd

    ranked = []
    cutoff = pd.Timestamp(as_of)
    for sid in pool:
        df = ssg.load_stock(sid)
        if df is None or not len(df) or cutoff not in df.index:
            continue
        sd = pd.Timestamp(ssg._snap_date(df, cutoff))     # score_stock 需要 Timestamp（會 .strftime）
        if sd is None:
            continue
        sc = ssg.score_stock(sid, df, sd, dict(ssg.DEFAULT_PARAMS))
        if sc is None:
            continue
        ok = not (overheat and _overheated(df, sd))
        ranked.append((sid, float(sc.get("total") or 0), ok))
    ranked.sort(key=lambda x: -x[1])
    strict = [sid for sid, _t, ok in ranked if ok][:top_n]
    if fill_mode != "topup" or len(strict) >= top_n:
        return strict
    out = list(strict)
    for sid, _t, ok in ranked:                 # 先補「被過熱擋掉」的
        if len(out) >= top_n:
            break
        if not ok and sid not in out:
            out.append(sid)
    if len(out) < top_n:                       # 再依 63 日動能補
        for sid in _mom_fallback(pool, as_of, ssg, exclude=set(out)):
            if len(out) >= top_n:
                break
            out.append(sid)
    return out


def _overheated(df, sd, max_from_high=7.0, max_ytd=100.0):
    """簡化版過熱（與回測同精神）：貼近 52 週高 or YTD 漲太多。"""
    import pandas as pd

    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    win = df.iloc[max(0, idx - 251):idx + 1]
    hi = float(win["high"].max())
    near_high = hi > 0 and cp >= hi * (1 - max_from_high / 100.0)
    ys = df[df.index <= pd.Timestamp(str(pd.Timestamp(sd).year) + "-01-01")]
    ytd = (cp / float(ys.iloc[-1]["close"]) - 1) if len(ys) and float(ys.iloc[-1]["close"]) > 0 else 0.0
    return near_high or (ytd > max_ytd / 100.0)


def pick_dates(start, end, months_step, calendar=None):
    """每 N 個月的選股日 → **對齊到當天或之後的第一個交易日**。

    ⚠️ 2026-10-28 修：原本用 `pd.date_range(start, end, freq="NMS")`，若 `start` 不是月初
    （例如 `--start 2022-01-03`），整個區間會算出 **0 個日期**（實測：靜默 0 筆）。
    改成「從 start 所屬月份起逐個月初往後走、只留落在 [start, end] 的」，
    且找不到任何月初時至少回傳 start 那天（單日區間也能跑）。
    """
    import pandas as pd

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    cur = start_ts.to_period("M").to_timestamp()
    raw = []
    while cur <= end_ts:
        # 月初早於 start ⇒ 用 start 那天（否則 `--start 2022-01-03` 會整個 1 月都不見）
        raw.append(max(cur, start_ts))
        cur = cur + pd.DateOffset(months=max(1, int(months_step)))
    if not raw:
        raw = [start_ts]
    out = []
    for d in raw:
        if calendar is not None:
            nxt = calendar[calendar >= d]
            if len(nxt) == 0 or nxt[0] > end_ts:
                continue
            d = nxt[0]
        out.append(pd.Timestamp(d).strftime("%Y-%m-%d"))
    return out


def main():
    ap = argparse.ArgumentParser(description="AI 選股 vs 純規則 A/B")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--every-months", type=int, default=1, help="每幾個月取一個選股日（預設 1）")
    ap.add_argument("--pool-n", type=int, default=50)
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--horizons", default="1,3,6,12", help="持有期（月），逗號分隔")
    ap.add_argument("--llm-cmd", default=None, help="呼叫模型的指令（stdin=prompt、stdout=JSON）")
    ap.add_argument("--reuse", action="store_true", help="已有稽核回應就沿用，不重打模型")
    ap.add_argument("--audit-dir", default="logs/ai_pick")
    ap.add_argument("--no-revenue", dest="revenue", action="store_false", default=True)
    ap.add_argument("--rules-fill", choices=["proportional", "topup"], default="proportional",
                    help="規則組選不滿 N 檔時：proportional（預設＝就那幾檔）或 topup（補滿）")
    ap.add_argument("--require-full", action="store_true",
                    help="兩邊都必須選滿 top_n 檔才納入比較（嚴格等量）")
    ap.add_argument("--news", action="store_true",
                    help="啟用 FinMind 新聞（一檔一天一次呼叫，很貴；預設關）")
    ap.add_argument("--news-lookback", type=int, default=14)
    ap.add_argument("--out", default=None, help="結果 JSON 路徑")
    args = ap.parse_args()

    import pandas as pd
    import scripts.stock_selector_grid as ssg
    from core.cache_io import load_cache_or_raw
    from core.pit_data import load_revenue_rows

    if args.news:
        os.environ["NEWS_PROVIDER"] = "finmind"
        from core.pit_news import register as _reg_news
        _np = _reg_news()
        _np.lookback_days = args.news_lookback
        _log(f"新聞來源：FinMind（lookback {args.news_lookback} 天、cutoff {_np.cutoff}）")
    else:
        os.environ.pop("NEWS_PROVIDER", None)

    hist, _hs = load_historical_shares()
    data_rows, px = {}, {}
    for sid in sorted({k[0] for k in hist}):
        df = ssg.load_stock(sid)
        if df is None or not len(df):
            continue
        px[sid] = df["close"]
        d2 = df.reset_index()
        data_rows[sid] = d2.rename(columns={d2.columns[0]: "date"})

    cal = None
    if "0050" in px:
        cal = px["0050"].index
    else:
        cal = sorted({d for s in px.values() for d in s.index})
        import pandas as _pd
        cal = _pd.DatetimeIndex(cal)
    # 法人與 PER（與 preview 相同的資料源；缺就留 null，不得臆測）
    inst = ssg.load_twse_inst_merged() or {}
    dates = pick_dates(args.start, args.end, args.every_months, calendar=cal)
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]
    _log(f"A/B：{len(dates)} 個選股日、池 {args.pool_n}、取 {args.top_n}、持有期 {horizons} 個月")

    rows, skipped = [], []
    for d in dates:
        pool, quarter = honest_pool(d, args.pool_n, hist, data_rows, ssg)
        if not pool:
            _log(f"  {d}: 無當時池 → 略過")
            continue
        packs = []
        for sid in pool:
            df = ssg.load_stock(sid)
            if df is None or pd.Timestamp(d) not in df.index:
                continue
            rev = load_revenue_rows(sid, fetch=args.revenue) if args.revenue else None
            per_series = None
            per_path = os.path.join("cache", "stock_per", f"per_{sid}.pkl")
            if os.path.exists(per_path):
                per_series, _ = load_cache_or_raw(per_path)
            inst_series = {}
            for _d, row in inst.items():
                if sid in row:
                    b, sell = row[sid]
                    inst_series[_d] = b - sell
            pack = build_pack(sid, d, price_df=df, inst_series=inst_series or None,
                              per_series=per_series, revenue_rows=rev,
                              extra={"quarter_point": quarter})
            assert_no_lookahead(pack, d)
            packs.append(pack)
        if len(packs) < args.top_n:
            _log(f"  {d}: 封包只有 {len(packs)} 檔 → 略過")
            continue
        rules = rules_picks([p["sid"] for p in packs], d, args.top_n, ssg,
                            fill_mode=args.rules_fill)
        ai, model = None, "(未呼叫)"
        prompt = build_prompt(packs, top_n=args.top_n)
        cached = os.path.join(args.audit_dir, d, "response.json")
        if args.llm_cmd:
            r = subprocess.run(args.llm_cmd, shell=True, input=prompt, capture_output=True,
                               text=True, timeout=900)
            if r.returncode == 0:
                try:
                    ai = [p["sid"] for p in parse_selection(
                        r.stdout, [p["sid"] for p in packs], args.top_n)["picks"]]
                    model = args.llm_cmd
                    write_audit(args.audit_dir, d, packs, prompt, r.stdout, model=model,
                                extra={"quarter_point": quarter})
                except Exception as e:
                    _log(f"  {d}: 模型輸出不合格（{e}）")
            else:
                _log(f"  {d}: 模型呼叫失敗 rc={r.returncode}")
        elif args.reuse and os.path.exists(cached):
            try:
                ai = [p["sid"] for p in parse_selection(open(cached, encoding="utf-8").read(),
                                                        [p["sid"] for p in packs], args.top_n)["picks"]]
                model = "快取"
            except Exception:
                ai = None
        ok, why = eligible_for_compare(ai, rules, args.top_n, args.require_full)
        if not ok:
            _log(f"  {d}: 不納入比較（{why}）")
            skipped.append({"date": d, "reason": why})
            continue
        rows.append({"date": d, "quarter": quarter, "n_packs": len(packs),
                     "rules": rules, "ai": ai, "model": model,
                     "returns": {
                         str(h): {"rules": basket_return(px, rules, d, h)[0],
                                  "ai": basket_return(px, ai, d, h)[0] if ai else None}
                         for h in horizons}})
        _log(f"  {d}: 規則={rules}｜AI={ai or '（無）'}")

    summary = {}
    for h in horizons:
        pairs = [(r["returns"][str(h)]["ai"], r["returns"][str(h)]["rules"]) for r in rows]
        summary[str(h)] = summarize(pairs)
    if skipped:
        _log(f"（另有 {len(skipped)} 個選股日不納入比較）")
    _log("\n=== 彙總（AI vs 規則，等權、未計成本）===")
    for h, s in summary.items():
        if s["n"] == 0:
            _log(f"  {h:>2} 個月：沒有可比樣本（AI 組缺席？）")
            continue
        t_txt = "n/a" if s["t_stat"] is None else f"{s['t_stat']:.2f}"
        _log(f"  {h:>2} 個月：n={s['n']}｜AI 平均 {s['ai_mean']:+.2%}｜規則 {s['rules_mean']:+.2%}"
             f"｜差 {s['diff_mean']:+.2%}｜勝率 {s['win_rate']:.0%}｜t={t_txt}｜{s['verdict']}")

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "config": {"start": args.start, "end": args.end, "every_months": args.every_months,
                      "pool_n": args.pool_n, "top_n": args.top_n, "horizons": horizons,
                      "llm_cmd": args.llm_cmd, "revenue": args.revenue},
           "rules_fill": args.rules_fill,
           "rows": rows, "skipped": skipped, "summary": summary}
    path = args.out or f"results/ai_ab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    _log(f"\n已存 {path}")
    if not args.llm_cmd:
        _log("（未接模型：目前只有規則組結果。要真的比較請給 --llm-cmd）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
