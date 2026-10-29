#!/usr/bin/env python3
"""scripts/backtest_profile_compare.py — 用「口徑 profile」跑同一組設定的並排比較

    .venv/bin/python scripts/backtest_profile_compare.py \
        --windows 2022-01-01:2025-12-31,2023-01-01:2026-10-23 \
        --profiles conservative,fair --top-n 5

輸出：每個期間 × 每個 profile × 每組的 報酬／MDD／夏普／總曝險，最後存成 markdown。

刻意用 subprocess 呼叫 `scripts/backtest_plan2_monthly_3group.py`（不是 import）——
那支腳本在 import 時就會載入全市場快取，重複 import 會互相污染模組級別名。
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

NAME = {"high_profit": "高風險", "normal": "正常", "stable": "高穩定", "megacap": "權值動能"}


def run_profile(profile, start, end, top_n, pool_n, initial=1_000_000, out_dir="results/profile_runs",
                groups_only=None):
    os.makedirs(out_dir, exist_ok=True)
    tag = f"{profile}_{start}_{end}_top{top_n}"
    env = dict(os.environ, PROFILE=profile, START=start, END=end,
               TOP_N=str(top_n), POOL_N=str(pool_n), INITIAL=str(int(initial)))
    if groups_only:
        env["GROUPS_ONLY"] = groups_only
    log = os.path.join(out_dir, f"{tag}.log")
    cp = subprocess.run([sys.executable, "scripts/backtest_plan2_monthly_3group.py"],
                        env=env, capture_output=True, text=True, timeout=3600)
    with open(log, "w", encoding="utf-8") as f:
        f.write(cp.stdout + "\n" + cp.stderr)
    if cp.returncode != 0:
        print(f"❌ {tag} 失敗（rc={cp.returncode}），見 {log}")
        return None
    with open("results/plan2_monthly_3group.json", encoding="utf-8") as f:
        d = json.load(f)
    d["_profile"] = profile
    with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return d


def main():
    ap = argparse.ArgumentParser(description="口徑 profile 並排比較")
    ap.add_argument("--windows", default="2022-01-01:2025-12-31",
                    help="期間清單，逗號分隔 `START:END`")
    ap.add_argument("--profiles", default="default,conservative,fair,legacy",
                    help="要比較的 profile（逗號分隔；空字串代表「完全照環境變數」）")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--pool-n", type=int, default=50)
    ap.add_argument("--out", default=None, help="markdown 輸出路徑")
    ap.add_argument("--groups-only", default=None,
                    help="只跑指定組別（例 normal；留空＝四組全跑，比較慢）")
    args = ap.parse_args()

    windows = [w.split(":") for w in args.windows.split(",") if w.strip()]
    profiles = [p.strip() for p in args.profiles.split(",")]
    lines = [f"# 口徑 profile 並排比較（{datetime.now():%Y-%m-%d %H:%M}）\n",
             f"設定：TOP_N={args.top_n}、POOL_N={args.pool_n}、本金 100 萬、每月換股\n"]
    data = {}
    for start, end in windows:
        for prof in profiles:
            d = run_profile(prof, start, end, args.top_n, args.pool_n,
                            groups_only=args.groups_only)
            if d is None:
                continue
            data[(start, end, prof)] = d
            b = d.get("benchmark_0050") or {}
            lines += [f"\n## {start} ~ {end}｜profile = `{prof or '(未指定)'}`｜0050 {b.get('total_return', 0):+.1%}\n",
                      "| 組別 | 總報酬 | 年化 | MDD | 夏普 | 股票曝險 | 總曝險 | 平均停泊 |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|"]
            for g in [k for k in ("normal", "high_profit", "stable", "megacap") if k in d["groups"]]:
                x = d["groups"][g]
                util_total = x.get("util_total_avg")
                park = x.get("park_avg") or 0
                park_txt = f"NT${park:,}" if park else "—"
                util_txt = "—" if util_total is None else f"{util_total:.1%}"
                lines.append(
                    f"| {NAME[g]} | {x['total_return']:+.1%} | {x['annualized']:+.2%} | {x['max_drawdown']:.1%} | "
                    f"{x['sharpe']:.2f} | {x['util_avg']:.1%} | {util_txt} | {park_txt} |")
    out = args.out or f"results/profile_compare_{datetime.now():%Y%m%d_%H%M%S}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"已寫入 {out}（共 {len(data)} 組結果）")


if __name__ == "__main__":
    main()
