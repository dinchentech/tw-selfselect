"""core/scoring.py — 選股評分的共用實作（2026-10-29 建立）

## 為什麼抽出來

`SCORING_MODEL=zscore`（AI 代理那套固定公式）原本只寫在回測腳本裡，實盤 `monthly_rebalance_picker.py`
無法共用 ⇒ 回測與實盤可能挑出不同名單。這裡做成**純函式**，兩邊都呼叫同一份：
- 回測：`scripts/backtest_plan2_monthly_3group.py` 的 `_zscore_picks()`
- 實盤：`scripts/monthly_rebalance_picker.py` 的 `_zscore_picks()`

## 公式（與 2016-2025 實測用的那套一致）

1. **資格**：`0 < PER <= 40`（沒有 PER 的股票不列入，與 AI 封包一致）。
2. **橫斷面 z 分數**（同一選股日、同一候選池內，母體標準差；缺值以 0 計）：
   - `z(63日報酬)`、`z(20日報酬)`、`z(距52週高)`、`z(PER)`
3. **分數**：`0.40·z(63日) + 0.25·z(20日) + 0.20·z(距52週高) + 0.15·(−z(PER))`
4. 依分數由高到低取前 N。

權重刻意做成模組常數（`WEIGHTS`），改動要一起改測試與文件。
"""
from __future__ import annotations

WEIGHTS = {"r63": 0.40, "r20": 0.25, "dist": 0.20, "per": 0.15}
#: 月營收 YoY 因子的權重（2026-10-29 新增；`FACTOR_REVENUE=1` 時生效）。
#: 啟動時的權重配置＝把 r63 從 0.40 降到 0.25、其餘不變，並加入 rev 0.15（總和仍 1.00）：
#:   0.25·z(63日) + 0.25·z(20日) + 0.20·z(距52週高) + 0.15·z(−PER) + 0.15·z(營收YoY)
WEIGHTS_REVENUE = {"r63": 0.25, "r20": 0.25, "dist": 0.20, "per": 0.15, "rev": 0.15}
PER_MAX = 40.0


def eligible(row) -> bool:
    """`0 < PER <= 40`（`per` 為 None → 不合格）。"""
    per = row.get("per")
    if per is None:
        return False
    try:
        per = float(per)
    except (TypeError, ValueError):
        return False
    return 0.0 < per <= PER_MAX


def _z(values):
    """母體 z 分數（None → 0；全部缺值或標準差 0 → 全 0）。"""
    import numpy as np

    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
    if arr.size == 0:
        return []
    if np.all(np.isnan(arr)):
        return [0.0] * arr.size
    mean, sd = np.nanmean(arr), np.nanstd(arr)
    if not sd or np.isnan(sd):
        return [0.0] * arr.size
    return list(np.nan_to_num((arr - mean) / sd, nan=0.0))


def score_rows(rows, weights=None, use_revenue=False):
    """`rows`：`[{"sid","r63","r20","dist","per","rev"}, ...]` → `[(sid, score)]`（依分數高→低）。

    會先套 `eligible()`（只留 0 < PER <= 40）再算 z 分數；分數相同時以 sid 升冪（可重現）。
    `use_revenue=True` ⇒ 改用 `WEIGHTS_REVENUE` 並把 `rev`（月營收 YoY）納入橫斷面 z 分數；
    `rev` 缺值以 0 計（不因為沒營收資料就把該檔踢掉）。
    """
    base = WEIGHTS_REVENUE if use_revenue else WEIGHTS
    w = dict(base)
    w.update(weights or {})
    kept = [r for r in rows if eligible(r)]
    if not kept:
        return []
    z63 = _z([r.get("r63") for r in kept])
    z20 = _z([r.get("r20") for r in kept])
    zd = _z([r.get("dist") for r in kept])
    zp = _z([float(r["per"]) for r in kept])
    zr = _z([r.get("rev") for r in kept]) if "rev" in w else [0.0] * len(kept)
    out = []
    for i, r in enumerate(kept):
        s = (w.get("r63", 0) * z63[i] + w.get("r20", 0) * z20[i] + w.get("dist", 0) * zd[i]
             + w.get("per", 0) * (-zp[i]) + w.get("rev", 0) * zr[i])
        out.append((r["sid"], float(s)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def picks_from_rows(rows, top_n=5, weights=None):
    """只要代號清單（等同回測／實盤的「取前 N」）。"""
    return [sid for sid, _s in score_rows(rows, weights)[:max(0, int(top_n))]]


def apply_sector_cap(ranked, industry, max_per_sector=0):
    """產業分散上限：每個產業最多取 `max_per_sector` 檔（`0`＝不限）。

    `ranked`：已排序的 `[sid, ...]`（或 `[(sid, score), ...]`，只取第一欄）；
    `industry`：`{sid: industry}`。超過上限的標的**往後遞補**，讓總檔數不變。
    沒有產業資料的標的視為同一類 `"unknown"`。
    """
    if not max_per_sector or max_per_sector <= 0:
        return [x[0] if isinstance(x, (tuple, list)) else x for x in ranked]
    out, cnt = [], {}
    for x in ranked:
        sid = x[0] if isinstance(x, (tuple, list)) else x
        cat = industry.get(sid, "unknown")
        if cnt.get(cat, 0) >= max_per_sector:
            continue
        cnt[cat] = cnt.get(cat, 0) + 1
        out.append(sid)
    return out


# ── 實驗旋鈕（2026-10-31）：降低追高／非動能名單 ─────────────────────────────
# 背景：實測 2016-2025 的 600 筆選股，98% 站上 MA60／MA200、r63 中位 +31.5%
# （母體中位只 +1.9%）、距 52 週高中位 −4.0% ⇒ 選股幾乎只輸出「已經漲一大段的後段趨勢股」。
# 這兩個工具讓「不追高」與「加一點非動能名單」可以被獨立測試，**預設全關**（＝行為不變）。

def prerank(rows, key="r63", keep_pct=None):
    """先依 `key` 排名，只留前 `keep_pct`% 的人再進評分（`None`／<=0／>=100 ⇒ 原樣）。

    用途：`keep_pct=30` = 「只在 63 日動能前 30% 裡挑」⇒ 池子先縮小，分數不會被少數暴衝股主導。
    缺值（None）一律剔除（既然要靠它排名，沒有值就不該進來）。
    """
    if not keep_pct or keep_pct <= 0 or keep_pct >= 100:
        return list(rows)
    vals = sorted(float(r[key]) for r in rows if r.get(key) is not None)
    if not vals:
        return []
    import numpy as np
    thr = float(np.percentile(vals, 100.0 - float(keep_pct)))
    return [r for r in rows if r.get(key) is not None and float(r[key]) >= thr]


#: 非動能名單的配方（低基期＋營收轉機）：負的 r63/r20/dir 權重＝越落後越前面。
NONMOM_WEIGHTS = {"r63": -0.30, "r20": -0.15, "dist": 0.0, "per": -0.25, "rev": 0.40}
#: 非動能名單的預設條件：63 日動能落在池內後 30%、且月營收 YoY > 0。
NONMOM_QUANTILE = 0.30
NONMOM_REV_MIN = 0.0


def nonmom_picks(rows, quantile=NONMOM_QUANTILE, rev_min=NONMOM_REV_MIN,
                 weights=None, use_revenue=True):
    """「低基期＋營收轉機」候選（`[(sid, score)]`，已排序）。

    - 條件：`r63` 在池內後 `quantile`（預設 30%）**且**月營收 YoY `> rev_min`（預設 0）；
      與動能名單相反，這裡刻意挑「還沒漲、但營收在成長」的股票。
    - 沒有營收資料者剔除（這個名單的存在理由就是營收轉機）。
    """
    cand = [r for r in rows if r.get("r63") is not None and r.get("rev") is not None
            and float(r["rev"]) > float(rev_min)]
    if not cand:
        return []
    q = max(0.0, min(1.0, float(quantile)))
    r63s = sorted(float(r["r63"]) for r in cand)
    import numpy as np
    cut = float(np.percentile(r63s, q * 100.0)) if r63s else 0.0
    low = [r for r in cand if float(r["r63"]) <= cut]
    if not low:
        return []
    w = dict(NONMOM_WEIGHTS)
    w.update(weights or {})
    return score_rows(low, weights=w, use_revenue=use_revenue)


def pick_sleeves(mom_ranked, nonmom_ranked, top_n=5, nonmom_slots=0):
    """把「動能名單」與「非動能名單」組成最終清單：先取動能 `top_n-nonmom_slots` 檔，
    再用非動能遞補 `nonmom_slots` 檔（重的代號不重複）。`nonmom_slots<=0` ⇒ 純動能（現況）。"""
    n = max(0, int(top_n))
    k = max(0, min(int(nonmom_slots), n))
    if k == 0:
        return list(mom_ranked)[:n]
    mom = list(mom_ranked)
    take_mom = mom[:max(0, n - k)]
    taken = {x[0] if isinstance(x, (tuple, list)) else x for x in take_mom}
    extra = []
    for item in nonmom_ranked:
        sid = item[0] if isinstance(item, (tuple, list)) else item
        if sid in taken:
            continue
        extra.append(item)
        taken.add(sid)
        if len(extra) >= k:
            break
    return take_mom + extra
