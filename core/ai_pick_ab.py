"""core/ai_pick_ab.py — AI 選股 vs 純規則的 A/B 評估（純函式，可獨立測試）

## 為什麼要 A/B

AI 選股最常見的失敗模式不是「選得不好」，而是**沒有人知道它到底有沒有比較好**：
沒有對照組、樣本太少、只看一次結果就想換策略。這個模組把「比較」變成可重跑的算式：

    對每個選股日 d、每個持有期 h：
        r_ai(d, h)    = AI 選出的 N 檔等權報酬（d → d+h 個月）
        r_rules(d, h) = 純規則選出的 N 檔等權報酬
        diff(d, h)    = r_ai − r_rules
    再彙總：平均、勝率（AI 贏的比例）、配對 t 統計量、樣本數。

## 口徑（與回測一致）

- 價格用**還原價**（專案快取）；期末價 = 目標日期（含）以前最後一個交易日收盤。
- 等權：每檔投入相同金額，不加權（AI 與規則都一樣，才公平）。
- **不做交易成本**：這裡比較的是「選股能力」，成本另計（若要比總報酬請套回測）。
- 樣本 < 10 個選股日時只印「樣本不足，勿下結論」。
"""
from __future__ import annotations

import math


def forward_return(prices, start, months: int, horizon_days=None):
    """單檔的持有期報酬（`start` 之後 `months` 個月，或指定 `horizon_days` 個交易日）。

    `prices`：DatetimeIndex 的收盤序列（已還原）。找不到起始或結束價 → `None`。
    """
    import pandas as pd

    s = prices.dropna()
    if len(s) == 0:
        return None
    d0 = pd.Timestamp(start)
    if d0 not in s.index:
        after = s.index[s.index >= d0]
        if len(after) == 0:
            return None
        d0 = after[0]
    i0 = s.index.get_loc(d0)
    if horizon_days is not None:
        i1 = min(len(s) - 1, i0 + int(horizon_days))
    else:
        target = d0 + pd.DateOffset(months=int(months))
        upto = s.index[s.index <= target]
        if len(upto) == 0:
            return None
        i1 = s.index.get_loc(upto[-1])
    p0, p1 = float(s.iloc[i0]), float(s.iloc[i1])
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def basket_return(px_by_sid: dict, sids, start, months: int, horizon_days=None):
    """一籃子（等權）的持有期報酬；缺資料的標的會被略過（回傳 (ret, used)）。"""
    rets = []
    for sid in sids:
        px = px_by_sid.get(sid)
        if px is None:
            continue
        r = forward_return(px, start, months, horizon_days)
        if r is not None:
            rets.append(r)
    if not rets:
        return None, 0
    return sum(rets) / len(rets), len(rets)


def summarize(pairs):
    """`pairs`：`[(ai_ret, rules_ret), ...]` → 平均差、勝率、配對 t、樣本數。

    配對 t = mean(diff) / (std(diff)/sqrt(n))；n<2 或 std=0 → `None`。
    """
    clean = [(float(a), float(b)) for a, b in pairs if a is not None and b is not None]
    n = len(clean)
    if n == 0:
        return {"n": 0, "ai_mean": None, "rules_mean": None, "diff_mean": None,
                "win_rate": None, "t_stat": None, "verdict": "沒有可比樣本"}
    diffs = [a - b for a, b in clean]
    mean = sum(diffs) / n
    ai_mean = sum(a for a, _b in clean) / n
    rules_mean = sum(b for _a, b in clean) / n
    win = sum(1 for d in diffs if d > 0) / n
    if n >= 2:
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        sd = math.sqrt(var)
        t = (mean / (sd / math.sqrt(n))) if sd > 0 else None
    else:
        t = None
    if n < 10:
        verdict = "樣本不足（<10 個選股日），勿下結論"
    elif t is not None and t >= 2.0:
        verdict = "AI 顯著較好（t >= 2）"
    elif t is not None and t <= -2.0:
        verdict = "AI 顯著較差（t <= -2）"
    else:
        verdict = "沒有顯著差異"
    return {"n": n, "ai_mean": ai_mean, "rules_mean": rules_mean,
            "diff_mean": mean, "win_rate": win, "t_stat": t, "verdict": verdict}


def eligible_for_compare(ai_picks, rules_picks, top_n: int, require_full: bool = False):
    """這一組（AI／規則）能不能拿來做等量比較？→ `(ok, reason)`。

    `require_full=True` 時兩邊都必須剛好選滿 `top_n` 檔（等權、等檔數才公平）。
    規則組在濾網下常選不滿（實測 2022-09 只有 2 檔），這種日子預設仍然比較
    （＝比「實際會持有的籃子」），但嚴格模式會把它排除並記錄原因。
    """
    n_ai = 0 if not ai_picks else len(ai_picks)
    n_rules = 0 if not rules_picks else len(rules_picks)
    if n_ai == 0:
        return False, "AI 組缺席"
    if n_rules == 0:
        return False, "規則組沒選出任何標的"
    if require_full and (n_ai != top_n or n_rules != top_n):
        return False, f"檔數不符（AI {n_ai}、規則 {n_rules}，要求各 {top_n}）"
    return True, ""
