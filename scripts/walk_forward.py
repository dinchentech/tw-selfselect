#!/usr/bin/env python3
"""scripts/walk_forward.py — 前向驗證（walk-forward）：用過去挑參數，只用沒看過的年份驗證。

## 為什麼需要

README 的 +1323.6% 是「同一段 2016-2025 上試 16 組、挑最好的一組」的結果（in-sample 選擇偏誤）。
walk-forward 把時間切開：**只用訓練段挑參數，下一段完全不准回頭改**，然後把窗口往前滾。
真正要看兩個數字：

- **OOS（測試段）串接報酬**：每一輪「用歷史挑出來的組合」在隔年的表現，逐年複利串起來。
- **退化幅度（degradation）**：in-sample 最佳（全期）vs 它自己 OOS 的落差；落差大＝之前是運氣。

## 用法

    # 預設：4 組候選（三個 preset ＋ 池150/營收/無上限）、測試年 2020-2025（擴張式訓練）
    .venv/bin/python scripts/walk_forward.py

    # 完整 16 組網格（慢很多，約 4 倍時間）
    .venv/bin/python scripts/walk_forward.py --combos full

    # 只做參數鄰居穩健性（直接讀 results/delisted_grid 的全期結果，不重跑）
    .venv/bin/python scripts/walk_forward.py --neighbors-only

輸出：`results/walk_forward/wf_<tag>.md`（表格）＋ `.json`（原始數據）；逐次回測的快取在
`results/walk_forward/cache/`（同一個 (組合, 起, 迄) 只跑一次）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
SCRIPT = "scripts/backtest_plan2_monthly_3group.py"
OUTDIR = ROOT / "results" / "walk_forward"
CACHE = OUTDIR / "cache"

#: 固定口徑（與 README 主表一致）：zscore ＋ 大盤年線 ＋ 閒置停泊 0050、TOP5、每月換股、100 萬、含成本
BASE_ENV = {
    "PROFILE": "default",
    "GROUPS_ONLY": "normal",
    "TOP_N": "5",
    "INITIAL": "1000000",
    "SCORING_MODEL": "zscore",
    "MARKET_FILTER": "1",
    "IDLE_CASH_ASSET": "0050",
    "SELFSELECT_PRESET": "aggressive",   # 只是讓 active_name 有名稱；下面的明示值會覆蓋它
}

#: 候選組合：(名稱, POOL_N, FACTOR_REVENUE, MAX_PER_SECTOR)
PRESET_COMBOS = [
    ("current",      100, 0, 0),
    ("revenue",      100, 1, 0),
    ("aggressive",   150, 1, 2),
    ("pool150_rev",  150, 1, 0),
]
FULL_COMBOS = [(f"p{pool}_rev{rev}_cap{cap}", pool, rev, cap)
               for pool in (20, 50, 100, 150) for rev in (0, 1) for cap in (0, 2)]


@dataclass
class Round:
    """一輪 walk-forward：訓練段挑參數 → 測試年只驗證。"""
    year: int                 # 測試年份
    train_start: str
    train_end: str
    best_combo: str
    best_metric: float        # 訓練段的選擇指標（預設夏普）
    train: dict               # 訓練段最佳組合的完整指標
    test: dict                # 測試年（OOS）的指標
    bench: dict               # 測試年 0050 的指標
    train_all: dict           # 訓練段所有候選的指標（算「領先第二名多少」用）


# ── 純函式（可單獨測試）─────────────────────────────────────────────
def oos_years(first: int, last: int) -> list[int]:
    """回傳要驗證的年份清單（含頭含尾，且順序遞增）。"""
    if last < first:
        raise ValueError("last 不可小於 first")
    return list(range(first, last + 1))


def anchored_windows(years: list[int], train_start: str = "2016-01-01") -> list[tuple[int, str, str]]:
    """擴張式（anchored）訓練窗：`(測試年, 訓練起, 訓練迄)`；訓練迄＝測試年前一年年底。"""
    out = []
    for y in years:
        out.append((y, train_start, f"{y - 1}-12-31"))
    return out


def pick_best(results: dict[str, dict], metric: str = "sharpe") -> tuple[str, float]:
    """從 {combo: metrics} 挑指標最高的組合（同分時取字典序最小，可重現）。"""
    if not results:
        raise ValueError("沒有可挑選的結果")
    best = None
    for name in sorted(results):
        val = results[name].get(metric)
        if val is None:
            continue
        if best is None or val > best[1]:
            best = (name, float(val))
    if best is None:
        raise ValueError(f"所有組合都沒有 {metric} 指標")
    return best


def chain(returns: list[float]) -> float:
    """把逐年報酬串接成累積報酬（0.1 = +10%）。"""
    eq = 1.0
    for r in returns:
        eq *= (1.0 + float(r))
    return eq - 1.0


def degradation(is_value: float, oos_value: float) -> float:
    """退化幅度：OOS 減去 in-sample（負值代表 OOS 較差）。"""
    return float(oos_value) - float(is_value)


def neighbor_grid(paths) -> list[dict]:
    """讀全期 16 組網格結果（results/delisted_grid/*_delisted.json），整理成鄰居表。

    這是 **in-sample** 的穩健性證據：看「最好那格附近是不是斷崖」。若換一格報酬就掉一大截，
    代表全期最佳（例如 aggressive 的 +1323.6%）很可能是雜訊而非體質。
    """
    rows = []
    for p in sorted(paths):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        g = (d.get("groups") or {}).get("normal") or {}
        if not g:
            continue
        rows.append({
            "pool": d.get("pool_n"), "revenue": int(bool(d.get("factor_revenue"))),
            "cap": d.get("max_per_sector") or 0,
            "total_return": g.get("total_return"), "annualized": g.get("annualized"),
            "sharpe": g.get("sharpe"), "max_drawdown": g.get("max_drawdown"),
            "bench_total_return": (d.get("benchmark_0050") or {}).get("total_return"),
        })
    rows.sort(key=lambda r: (r["pool"] or 0, -r["revenue"], r["cap"]))
    return rows


# ── 回測呼叫（帶快取）──────────────────────────────────────────────
def _mode_tag() -> str:
    """口徑標記（寫進快取檔名）：`STRAT_MODE` ＋ 是否套 immediate 過熱閘門。

    為什麼必須有：2026-10-31 起「實盤口徑」＝`STRAT_MODE=form`＋`IMM_OVERHEAT=1`，
    與早期主表用的 `group`（輪替四策略）差 664pp；若快取不分口徑，換口徑重跑會**默默沿用舊結果**。
    """
    mode = os.getenv("STRAT_MODE", "group")
    imm = "imm" if os.getenv("IMM_OVERHEAT", "0") == "1" else "noimm"
    return f"{mode}_{imm}"


def _cache_path(combo: str, start: str, end: str) -> Path:
    return CACHE / f"{combo}_{start}_{end}_{_mode_tag()}.json"


def run_backtest(combo: str, pool: int, rev: int, cap: int, start: str, end: str,
                 *, force: bool = False) -> dict:
    """跑一次回測並回傳 `{group, benchmark}`；同一組參數＋區間會快取。"""
    path = _cache_path(combo, start, end)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    env = dict(os.environ)
    env.update(BASE_ENV)
    env.update({
        "POOL_N": str(pool), "FACTOR_REVENUE": str(rev), "MAX_PER_SECTOR": str(cap),
        "START": start, "END": end,
    })
    proc = subprocess.run([PY, SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"回測失敗 {combo} {start}~{end}：\n{proc.stderr[-1200:]}")
    data = json.loads((ROOT / "results/plan2_monthly_3group.json").read_text(encoding="utf-8"))
    group = dict(data["groups"]["normal"])
    bench = dict(data.get("benchmark_0050") or {})
    out = {"group": group, "benchmark_0050": bench, "combo": combo,
           "pool": pool, "factor_revenue": rev, "max_per_sector": cap,
           "start": start, "end": end}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="walk-forward 前向驗證")
    ap.add_argument("--combos", choices=["presets", "full"], default="presets")
    ap.add_argument("--train-start", default="2016-01-01")
    ap.add_argument("--first-test-year", type=int, default=2020)
    ap.add_argument("--last-test-year", type=int, default=2025)
    ap.add_argument("--metric", default="sharpe", choices=["sharpe", "total_return", "annualized"])
    ap.add_argument("--tag", default="")
    ap.add_argument("--force", action="store_true", help="忽略快取重跑")
    ap.add_argument("--neighbors-only", action="store_true",
                    help="只輸出全期參數鄰居穩健性（讀 results/delisted_grid，不重跑回測）")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    combos = PRESET_COMBOS if args.combos == "presets" else FULL_COMBOS
    years = oos_years(args.first_test_year, args.last_test_year)
    windows = anchored_windows(years, args.train_start)

    rounds: list[Round] = []
    if not args.neighbors_only:
        print(f"▶ 候選 {len(combos)} 組 × 測試年 {years[0]}–{years[-1]}"
              f"（每輪 {len(combos)} 次訓練段回測 ＋ 1 次 OOS 回測）", flush=True)
        for i, (year, tr_start, tr_end) in enumerate(windows, 1):
            train: dict[str, dict] = {}
            for name, pool, rev, cap in combos:
                r = run_backtest(name, pool, rev, cap, tr_start, tr_end, force=args.force)
                train[name] = r["group"]
                print(f"  [{i}/{len(windows)}] 訓練 {name:<14} {tr_start}~{tr_end} "
                      f"報酬 {r['group']['total_return']:+.1%} 夏普 {r['group']['sharpe']:.2f}", flush=True)
            best_name, best_val = pick_best(train, args.metric)
            pool, rev, cap = next((p, v, c) for n, p, v, c in combos if n == best_name)
            oos = run_backtest(best_name, pool, rev, cap, f"{year}-01-01", f"{year}-12-31",
                               force=args.force)
            rounds.append(Round(
                year=year, train_start=tr_start, train_end=tr_end, best_combo=best_name,
                best_metric=best_val, train=train[best_name],
                test=oos["group"], bench=oos.get("benchmark_0050") or {},
                train_all={k: {"sharpe": v.get("sharpe"), "total_return": v.get("total_return")}
                           for k, v in train.items()},
            ))
            print(f"  ✅ {year} OOS：{best_name} 報酬 {oos['group']['total_return']:+.1%}"
                  f"（0050 {(oos.get('benchmark_0050') or {}).get('total_return', float('nan')):+.1%}）", flush=True)
    # `--neighbors-only`：不重跑回測，只輸出全期 16 組網格（in-sample 參數鄰居表）

    # 全期參數鄰居表（in-sample，讀既有 results/delisted_grid）；先算好才能一起寫進 JSON
    neigh = neighbor_grid((ROOT / "results" / "delisted_grid").glob("*_delisted.json"))

    tag = args.tag or f"{args.combos}_{years[0]}_{years[-1]}"
    payload = {
        "config": {"combos": [{"name": n, "pool": p, "revenue": v, "cap": c} for n, p, v, c in combos],
                   "metric": args.metric, "train_start": args.train_start,
                   "oos_years": years,
                   "strat_mode": os.getenv("STRAT_MODE", "group"),
                   "imm_overheat": os.getenv("IMM_OVERHEAT", "0") == "1"},
        "rounds": [asdict(r) for r in rounds],
        "neighbor_grid": neigh,
    }
    if rounds:
        oos_rets = [r.test.get("total_return", 0.0) for r in rounds]
        bench_rets = [r.bench.get("total_return", 0.0) for r in rounds]
        payload["summary"] = {
            "oos_chained_return": chain(oos_rets),
            "bench_chained_return": chain(bench_rets),
            "oos_mean_return": sum(oos_rets) / len(oos_rets),
            "oos_win_vs_bench": sum(1 for a, b in zip(oos_rets, bench_rets) if a > b),
            "n_rounds": len(rounds),
            "picked": [r.best_combo for r in rounds],
        }
        _years = float(len(rounds))
        payload["summary"]["oos_chained_annualized"] = (
            (1.0 + payload["summary"]["oos_chained_return"]) ** (1.0 / _years) - 1.0)
    (OUTDIR / f"wf_{tag}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    # ── Markdown ────────────────────────────────────────────────
    L = [f"# Walk-forward 前向驗證（{tag}；口徑 {_mode_tag()}）\n",
         f"- 候選組合：**{len(combos)}** 組（`--combos {args.combos}`）",
         f"- 訓練段：擴張式（anchored），起點 {args.train_start}，迄於測試年前一年年底",
         f"- 測試年：{years[0]}–{years[-1]}（**逐年獨立回測，完全不參與挑參數**）",
         f"- 每輪用**訓練段 {args.metric} 最高**的組合，只用在次一年的 OOS\n",
         "| 測試年 | 訓練段 | 訓練段挑中 | 訓練段夏普 | 訓練段報酬 | OOS 報酬 | OOS MDD | OOS 夏普 | 0050 報酬 |",
         "|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rounds:
        L.append(f"| {r.year} | {r.train_start}~{r.train_end} | `{r.best_combo}` | "
                 f"{r.train.get('sharpe', float('nan')):.2f} | {r.train.get('total_return', float('nan')):+.1%} | "
                 f"{r.test.get('total_return', float('nan')):+.1%} | {r.test.get('max_drawdown', float('nan')):.1%} | "
                 f"{r.test.get('sharpe', float('nan')):.2f} | {r.bench.get('total_return', float('nan')):+.1%} |")
    if rounds:
        s = payload["summary"]
        L += ["", "## 彙總", "",
              f"- **OOS 逐年串接報酬：{s['oos_chained_return']:+.1%}**（同期 0050 串接 {s['bench_chained_return']:+.1%}）",
              f"- OOS 平均年報酬：{s['oos_mean_return']:+.1%}；逐年勝過 0050 的次數："
              f"**{s['oos_win_vs_bench']}/{s['n_rounds']}**",
              f"- 每輪被挑中的組合：{', '.join(f'{y}:{n}' for y, n in zip([r.year for r in rounds], s['picked']))}"]
    # ── 自動判讀（把限制寫進報告，不靠 README 另外叮嚀）──────
    if rounds:
        margins = []
        for r in rounds:
            others = [v["sharpe"] for k, v in (r.train_all or {}).items()
                      if k != r.best_combo and v.get("sharpe") is not None]
            if others:
                margins.append(r.best_metric - max(others))
        picks = {r.best_combo for r in rounds}
        wins = [r.year for r in rounds if (r.test.get("total_return") or 0) >
                (r.bench.get("total_return") or 0)]
        loses = [r.year for r in rounds if (r.test.get("total_return") or 0) <=
                 (r.bench.get("total_return") or 0)]
        s = payload["summary"]
        s["min_margin_sharpe"] = round(min(margins), 3) if margins else None
        s["n_distinct_picks"] = len(picks)
        s["lose_years"] = loses
        L += ["", "## 判讀（自動產生）", ""]
        if len(picks) == 1:
            L.append(f"- ⚠️ **每一輪都挑中同一組 `{rounds[0].best_combo}`**：所以這不是「搜尋出參數」，"
                     f"只是「歷史上它一直最好」。walk-forward 在這裡能證明的只有「它換到沒看過的年份沒有崩」，"
                     f"不能證明「這是被獨立驗證出來的最佳口徑」。")
        else:
            L.append(f"- 各輪挑中的組合共 {len(picks)} 種（{', '.join(sorted(picks))}）。")
        if margins:
            L.append(f"- 訓練段「領先第二名」的夏普差距最小 {min(margins):+.2f}："
                     f"{'差距很小 ⇒ 挑選本身接近擲骰子，OOS 好壞多半是運氣' if min(margins) < 0.05 else '差距不算小 ⇒ 至少訓練段內部排序是穩定的'}。")
        L.append(f"- OOS 勝 0050 的年份：{('、'.join(map(str, wins)) or '無')}；"
                 f"輸的年份：{('、'.join(map(str, loses)) or '無')}"
                 f"（{len(wins)}/{len(rounds)} 勝，串接 {s['oos_chained_return']:+.1%} vs 0050 {s['bench_chained_return']:+.1%}）。")
        L.append("- 測試年逐年獨立回測（每年重新 NT$1,000,000 起跑），"
                 "**不等於**全期回測的年度切片；兩者差異來自起跑資金與停泊狀態，不可互相加總。")
        L.append(f"- OOS 串接換算年化約 **{s.get('oos_chained_annualized', float('nan')):+.2%}**"
                 f"（只看 {rounds[0].year}–{rounds[-1].year} 這段，沒涵蓋 2016-2019 的弱年份）；"
                 f"不可拿它跟全期 in-sample 年化直接比大小。")
        L.append("- 候選網格本身是看過全期結果才挑的（3 個 preset ＋ 池150/無上限），"
                 "所以「OOS 沒崩」仍**不代表**沒有選擇偏誤；參數鄰居表（下節）就是在量這件事。")

    if neigh:
        L += ["", "## 全期參數鄰居表（in-sample，非 walk-forward）", "",
              "同一段 2016-01-01~2025-12-31 上換參數的結果，用來看「最佳那格是不是孤峰」：", "",
              "| 池 | 營收因子 | 產業上限 | 總報酬 | 年化 | 夏普 | MDD |", "|---:|:--:|:--:|---:|---:|---:|---:|"]
        for r in neigh:
            L.append(f"| {r['pool']} | {'✓' if r['revenue'] else '—'} | {r['cap']} | "
                     f"{r['total_return']:+.1%} | {r['annualized']:+.2%} | {r['sharpe']:.2f} | {r['max_drawdown']:.1%} |")
        trs = [r["total_return"] for r in neigh if r["total_return"] is not None]
        if trs:
            L += ["", f"- 16 組總報酬範圍：{min(trs):+.1%} ~ {max(trs):+.1%}（中位數 {sorted(trs)[len(trs)//2]:+.1%}）；"
                  f"最佳為 {max(trs):+.1%}。"]
            best = max((r for r in neigh if r["total_return"] is not None),
                       key=lambda r: r["total_return"])
            nb = [r for r in neigh if r is not best
                  and sum([r["pool"] != best["pool"], r["revenue"] != best["revenue"],
                           r["cap"] != best["cap"]]) == 1]
            if nb:
                L.append(f"- 最佳格 `池{best['pool']}／營收{'開' if best['revenue'] else '關'}／上限{best['cap']}` 的"
                         f"**單旋鈕鄰居**（只換一個參數）：")
                for r in nb:
                    dim = ("池" if r["pool"] != best["pool"] else
                           ("營收" if r["revenue"] != best["revenue"] else "上限"))
                    L.append(f"  - 換 {dim}（{best[{'池': 'pool', '營收': 'revenue', '上限': 'cap'}[dim]]}"
                             f" → {r[{'池': 'pool', '營收': 'revenue', '上限': 'cap'}[dim]]}）："
                             f"{best['total_return']:+.1%} → {r['total_return']:+.1%}"
                             f"（{r['total_return'] - best['total_return']:+.1%} 絕對）")
                L.append("  - 也就是說：最佳格只要換一個參數就掉一截 ⇒ 這個「最佳」不是平台，是尖峰。")
    (OUTDIR / f"wf_{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\n已寫 {OUTDIR / f'wf_{tag}.md'} 與 .json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
