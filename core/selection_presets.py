"""core/selection_presets.py — 「選股口徑」的具名預設（預設 `revenue`，其餘由使用者選）

## 為什麼要有這個

2026-10-29 的重測（宇宙補回 62 檔已下市股＋PER 補齊 672 檔）得到一個**有代價的結論**：

| 口徑 | 池 | 營收因子 | 產業上限 | 2016-2025 總報酬 | 最大回撤 | 夏普 |
|---|---:|---|---|---:|---:|---:|
| `current`    | 100 | 關 | 無 | +411.1% | −52.4% | 0.75 |
| `revenue`    | 100 | 開 | 無 | **+762.4%** | **−53.7%** | 0.95 |
| `aggressive` | 150 | 開 | 2 | **+1323.6%** | −40.2% | **1.15** |
| （對照）0050 買進持有 | — | — | — | +477.6% | −34.0% | 1.06 |

**只有「大池＋營收因子」這一類口徑的總報酬能超過 0050**，而且 `aggressive` 的回撤（−40.2%）
比 `current`／`revenue`（−52~−54%）**小**——產業上限把回撤壓回去了；夏普 1.15 也首次超過 0050（1.06）。

**預設是 `revenue`（2026-10-29 使用者裁定）**：總報酬 +762.4%（0050 +477.6%），但**回撤 −53.7% 是三個裡最深的**
（0050 −34.0%）。想回到舊行為（無營收因子）用 `SELFSELECT_PRESET=current`，想追最高歷史報酬用 `aggressive`。

## 但這是「有代價、且尚未站穩」的選擇，要看清楚

1. **回撤沒有贏**：預設 `revenue` 的回撤 **−53.7%**（0050 −34.0%）是三個 preset 裡最深的，
   夏普 0.95 也還低於 0050 的 1.06；`aggressive` 的夏普 1.15 才首次超過，但回撤 −40.2% 仍大於 0050。
2. **這是同一段 2016-2025 上 16 組實驗裡挑出來的最好一組**（in-sample 選擇偏誤），
   **沒有**非重疊窗口或 walk-forward 驗證。真實上線很可能拿不到同樣的數字。
3. 大池＋營收因子的高報酬，集中在中小型股的動能段；遇到 2018／2022 這種空頭，
   回撤會比 `current` 更深（`revenue` 就是 −53.7%）。
4. 因子本身只用了動能＋評價＋月營收 YoY，**沒有**品質／低波動／法人籌碼，也沒有滑價假設。

> 所以本模組只提供「開關」：**預設 `revenue`**，另外兩個（`current`＝舊行為、`aggressive`＝最高歷史報酬）
> 由使用者自己切；切換時 `warning_text()` 會把代價印出來，後果自負、但已經被告知。

## 用法

    # 實盤（選股口徑）；預設已經是 revenue，要別的口徑才需要寫
    SELFSELECT_PRESET=current               # 或 aggressive（預設＝revenue）

    # 回測（同一組 preset；個別環境變數仍然優先）
    PRESET=aggressive START=2016-01-01 END=2025-12-31 \
      .venv/bin/python scripts/backtest_plan2_monthly_3group.py

**明示的環境變數優先**：`SELFSELECT_PRESET=aggressive SELFSELECT_MAX_PER_SECTOR=0` ⇒ 產業上限會是 0。
"""
from __future__ import annotations

import os

DEFAULT_PRESET = "revenue"

PRESETS: dict[str, dict] = {
    "current": {
        "label": "舊行為（池 100、不含營收因子）",
        "desc": "2026-10-29 之前的口徑（**已不是預設**）：池 100 檔、zscore 動能＋評價、不含營收因子。"
                "2016-2025：+411.1%／MDD −52.4%／夏普 0.75（0050 +477.6%／−34.0%／1.06）"
                "⇒ 報酬比預設低 351pp，回撤卻只小 1.3pp。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "0", "MAX_PER_SECTOR": "0"},
    },
    "revenue": {
        "label": "預設（池 100＋營收因子）",
        "desc": "只多一個月營收 YoY 因子。**總報酬超過 0050，但回撤最深**："
                "2016-2025 +762.4%／MDD −53.7%／夏普 0.95（同段 0050 −34.0%／1.06）。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "1", "MAX_PER_SECTOR": "0"},
    },
    "aggressive": {
        "label": "積極（池 150＋營收因子＋產業上限 2）",
        "desc": "歷史報酬最高的一組，且產業上限把回撤壓回 −40%。"
                "2016-2025 +1323.6%／MDD −40.2%／夏普 **1.15**（夏普首次超過 0050 的 1.06，回撤仍比 0050 的 −34.0% 大）；"
                "屬 16 組裡事後挑出來的最好一組，**未經 walk-forward 驗證**。",
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


def warning_text() -> str:
    """切到非預設 preset 時要印給使用者的後果提醒（誠實、可稽核）。"""
    return (
        "⚠️ 你切換了選股口徑 preset：這是「用更大的回撤換更高的歷史報酬」，"
        "不是穩健的超額報酬。\n"
        "   · 超過 0050 的總報酬都集中在 2016-2025 這段 in-sample 結果，"
        "而且是在 16 組實驗裡事後挑出來的（沒有 walk-forward）。\n"
        "   · 回撤 −40~−54%（0050 −34%）；`aggressive` 的夏普 1.15 首次超過 0050，"
        "但那是在同一段歷史上挑出來的，不能外推。\n"
        "   · 建議先用小額或紙上跑一段時間，再決定要不要把它變成正式的實盤口徑。"
    )
