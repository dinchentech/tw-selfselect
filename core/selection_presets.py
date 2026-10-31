"""core/selection_presets.py — 「選股口徑」的具名預設（預設 `aggressive`，其餘由使用者選）

## 為什麼要有這個

2026-10-29 的重測（宇宙補回 62 檔已下市股＋PER 補齊 672 檔）得到一個**有代價的結論**：

口徑＝**實盤路徑**（選股後由 `auto` 型態路由決定策略；回測對應 `STRAT_MODE=form` ＋ `IMM_OVERHEAT=1`）：

| 口徑 | 池 | 營收因子 | 產業上限 | 2016-2025 總報酬 | 最大回撤 | 夏普 |
|---|---:|---|---|---:|---:|---:|
| `current`    | 100 | 關 | 無 | +536.2% | −51.4% | 0.82 |
| `revenue`    | 100 | 開 | 無 | +723.5% | −55.6% | 0.93 |
| `aggressive` | 150 | 開 | 2 | **+926.5%** | **−45.6%** | **1.01** |
| （對照）0050 買進持有 | — | — | — | +477.6% | −34.0% | 1.06 |

（若改成 `STRAT_MODE=group`「輪替四策略」：+411.1%／+762.4%／+1323.6%，夏普 0.75／0.95／1.15——
**那不是實盤會走的路徑**，只當上限參考，見 `策略說明.md` §6.7。）

**只有「大池＋營收因子」這一類口徑的總報酬能超過 0050**，而且 `aggressive` 的回撤（−45.6%）
比 `current`／`revenue`（−51~−56%）**小**——產業上限把回撤壓回去了。但**三個 preset 的夏普都輸 0050**（0.82／0.93／1.01 vs 1.06）。

**預設是 `aggressive`（2026-10-30 使用者裁定，先前為 `revenue`）**：池 150＋營收因子＋產業上限 2，
總報酬 **+926.5%**、MDD **−45.6%**、夏普 **1.01**；代價是**夏普略輸 0050（1.06）、回撤比 0050（−34.0%）深**，
而且**它是 16 組實驗裡事後挑出的最好一組**。想保守一點：`SELFSELECT_PRESET=revenue`（+723.5%）
或 `current`（+536.2%）。

## 但這是「有代價、且尚未站穩」的選擇，要看清楚

1. **回撤沒有贏**：預設 `aggressive` 的回撤 **−40.2%**（0050 −34.0%）仍比 0050 深；夏普 1.15 首次超過 0050 的 1.06。
   若換成 `revenue` 回撤會更深（−53.7%）、夏普降到 0.95。
2. **這是同一段 2016-2025 上 16 組實驗裡挑出來的最好一組**（in-sample 選擇偏誤），
   **沒有**非重疊窗口或 walk-forward 驗證。真實上線很可能拿不到同樣的數字。
3. 大池＋營收因子的高報酬，集中在中小型股的動能段；遇到 2018／2022 這種空頭，
   `revenue`／無產業上限時回撤會到 −53.7%；`aggressive` 靠產業上限壓回 −40.2%。
4. 因子本身只用了動能＋評價＋月營收 YoY，**沒有**品質／低波動／法人籌碼，也沒有滑價假設。

> 所以本模組只提供「開關」：**預設 `aggressive`**（使用者 2026-10-30 裁定），另外兩個（`revenue`＝中等、
> `current`＝舊行為）由使用者自己切；高報酬口徑執行時 `warning_text()` 會把代價印出來。

## 用法

    # 實盤（選股口徑）；預設已經是 aggressive，要別的口徑才需要寫
    SELFSELECT_PRESET=revenue               # 或 current（預設＝aggressive）

    # 回測（同一組 preset；個別環境變數仍然優先）
    PRESET=revenue START=2016-01-01 END=2025-12-31 \
      .venv/bin/python scripts/backtest_plan2_monthly_3group.py

**明示的環境變數優先**：`SELFSELECT_PRESET=aggressive SELFSELECT_MAX_PER_SECTOR=0` ⇒ 產業上限會是 0。
"""
from __future__ import annotations

import os

DEFAULT_PRESET = "aggressive"

PRESETS: dict[str, dict] = {
    "current": {
        "label": "舊行為（池 100、不含營收因子）",
        "desc": "2026-10-29 之前的口徑（**已不是預設**）：池 100 檔、zscore 動能＋評價、不含營收因子。"
                "2016-2025（實盤口徑）：+536.2%／MDD −51.4%／夏普 0.82（0050 +477.6%／−34.0%／1.06）"
                "⇒ 報酬比預設（aggressive）低 390pp。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "0", "MAX_PER_SECTOR": "0"},
    },
    "revenue": {
        "label": "中等（池 100＋營收因子）",
        "desc": "只多一個月營收 YoY 因子。**總報酬超過 0050，但回撤最深**："
                "2016-2025（實盤口徑）+723.5%／MDD −55.6%／夏普 0.93（同段 0050 −34.0%／1.06）。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "1", "MAX_PER_SECTOR": "0"},
    },
    "aggressive": {
        "label": "預設（池 150＋營收因子＋產業上限 2）",
        "desc": "歷史報酬最高的一組，且產業上限把回撤從 −55.6% 壓回 −45.6%。"
                "2016-2025（實盤口徑）+926.5%／MDD −45.6%／夏普 **1.01**（仍略輸 0050 的 1.06，回撤也比 −34.0% 深）；"
                "屬 16 組裡事後挑出來的最好一組，walk-forward 顯示是「尖峰不是平台」。",
        "knobs": {"POOL_N": "150", "FACTOR_REVENUE": "1", "MAX_PER_SECTOR": "2"},
    },
}


def resolve(name: str | None) -> dict | None:
    """名稱 → preset 定義；空字串／None ⇒ `None`（不套用）。名稱錯 → ValueError（大聲失敗）。"""
    if name is None:
        return None
    key = str(name).strip().lower()
    if not key:
        return None
    if key not in PRESETS:
        raise ValueError(f"未知的 SELECTION_PRESET='{name}'；可用：{', '.join(PRESETS)}")
    return PRESETS[key]


def active_name(env=None) -> str:
    """目前生效的 preset 名稱：`SELFSELECT_PRESET` ＞ `PRESET` ＞ `current`。"""
    src = os.environ if env is None else env
    raw = (src.get("SELFSELECT_PRESET") or src.get("PRESET") or DEFAULT_PRESET).strip().lower()
    return raw if raw in PRESETS else DEFAULT_PRESET


def expand(name: str | None = None, explicit: dict | None = None) -> dict:
    """把 preset 展開成 `{knob: value}`；`explicit`（使用者明示的變數）優先，不被覆寫。"""
    prof = resolve(name if name is not None else active_name())
    if prof is None:
        return {}
    explicit = explicit or {}
    return {k: str(explicit.get(k, v)) for k, v in prof["knobs"].items()}


def apply_to_env(name: str | None = None, env=None) -> dict:
    """**就地把 preset 寫進 `env`**（只寫使用者沒明示的鍵），回傳實際套用的 dict。

    回測腳本與實盤選股器都在「讀旋鈕之前」呼叫這支，所以個別環境變數仍然優先。
    """
    src = os.environ if env is None else env
    resolved = expand(name if name is not None else active_name(), explicit=dict(src))
    for k, v in resolved.items():
        src.setdefault(k, v)
    return resolved


def describe() -> str:
    """文件／CLI 用的說明表（含後果）。"""
    lines = ["| preset | 內容 | 2016-2025 實測（含成本，0050 +477.6%） |", "|---|---|---|"]
    for k, p in PRESETS.items():
        lines.append(f"| `{k}` | {p['label']} | {p['desc']} |")
    return "\n".join(lines)


#: 高報酬口徑（總報酬 > 0050）——執行時要印後果提醒；`current` 不算。
HIGH_RETURN_PRESETS = ("revenue", "aggressive")


def warning_text(is_default: bool = False, name: str | None = None) -> str:
    """高報酬口徑的後果提醒（誠實、可稽核）。

    `is_default=True` 用於「這就是預設口徑」的措辭（預設 `aggressive` 也會印，避免使用者不知道代價）。
    """
    n = name or (DEFAULT_PRESET if is_default else "revenue／aggressive")
    head = (f"⚠️ 預設選股口徑 `{n}` 是「用更大的回撤換更高的歷史報酬」，不是穩健的超額報酬。"
            if is_default else
            f"⚠️ 你切換到 `{n}`：這是「用更大的回撤換更高的歷史報酬」，不是穩健的超額報酬。")
    return (
        head + "\n"
        "   · 超過 0050 的總報酬都集中在 2016-2025 這段 in-sample 結果，"
        "而且是在 16 組實驗裡事後挑出來的；walk-forward 六輪挑中兩組、領先第二名最小只有 0.01 夏普，參數鄰居換一顆就掉一大截（尖峰不是平台）。\n"
        "   · 實盤口徑（`auto` 型態路由＋過熱閘門）：`aggressive` +926.5%／MDD −45.6%／夏普 1.01，"
        "`revenue` +723.5%／−55.6%／0.93、`current` +536.2%／−51.4%／0.82；"
        "0050 +477.6%／−34.0%／1.06 ⇒ **夏普全部輸 0050**。\n"
        "   · 實測 84.8% 的選股會被路由到順勢策略（純動能暴露），2022、2024 都輸大盤。\n"
        "   · 建議先用小額或紙上跑一段時間，再決定要不要把它用在正式資金上。"
    )
