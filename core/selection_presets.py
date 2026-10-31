"""core/selection_presets.py — 「選股口徑」的具名預設（預設 `aggressive`，其餘由使用者選）

## 為什麼要有這個

2026-10-29 的重測（宇宙補回 62 檔已下市股＋PER 補齊 672 檔）得到一個**有代價的結論**：

口徑＝**實盤路徑**（選股後由 `auto` 型態路由決定策略；回測對應 `STRAT_MODE=form` ＋ `IMM_OVERHEAT=1`）：

| 口徑 | 池 | 營收因子 | 產業上限 | 2016-2025 總報酬 | 最大回撤 | 夏普 |
|---|---:|---|---|---:|---:|---:|
| `current`    | 100 | 關 | 無 | +992.6% | −51.3% | 1.02 |
| `revenue`    | 100 | 開 | 無 | **+1445.2%** | −56.7% | **1.17** |
| `aggressive` | 150 | 開 | 2 | +1306.9% | **−46.1%** | 1.11 |
| （對照）0050 買進持有 | — | — | — | +477.6% | −34.0% | 1.06 |

（窗口＝2016-04-01~2026-10-23、含「選股端過熱過濾」（`Z_OVERHEAT=1`，2026-10-31 起預設）。
若改成 `STRAT_MODE=group`「輪替四策略」：+411.1%／+762.4%／+1323.6%，夏普 0.75／0.95／1.15——
**那不是實盤會走的路徑**，只當上限參考，見 `策略說明.md` §6.7。）

**三個 preset 的總報酬都超過 0050**，而且 `aggressive` 的回撤（−46.1%）
比 `current`／`revenue`（−51~−57%）**小**——產業上限把回撤壓回去了。
但**夏普仍輸 0050**（1.02／1.17／1.11 vs 0050 的 1.17 打平）。

**預設是 `revenue`（2026-10-31 使用者裁定；2026-10-30～10-31 之間曾是 `aggressive`）**：池 150＋營收因子＋產業上限 2，
總報酬 **+1306.9%**、MDD **−46.1%**、夏普 **1.11**；代價是**夏普略輸 0050（1.17）、回撤比 0050（−34.0%）深**，
而且**它是 16 組實驗裡事後挑出的最好一組**。想保守一點：`SELFSELECT_PRESET=revenue`（+1445.2%，但回撤 −56.7%）
或 `current`（+992.6%）。

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

DEFAULT_PRESET = "revenue"   # 2026-10-31 使用者裁定：預設改回 revenue（理由見版本沿革 1.1.12）

PRESETS: dict[str, dict] = {
    "current": {
        "label": "舊行為（池 100、不含營收因子）",
        "desc": "2026-10-29 之前的口徑（**已不是預設**）：池 100 檔、zscore 動能＋評價、不含營收因子。"
                "2016-04~2026-10（實盤口徑）：+992.6%／MDD −51.3%／夏普 1.02（0050 +793.4%／−34.0%／1.17）"
                "⇒ 報酬比預設（aggressive）低 314pp。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "0", "MAX_PER_SECTOR": "0"},
    },
    "revenue": {
        "label": "預設（池 100＋營收因子）",
        "desc": "**預設（2026-10-31 使用者裁定）**：池 100＋月營收 YoY 因子、無產業上限。"
                "2016-04~2026-10（實盤口徑）**+1445.2%／MDD −56.7%／夏普 1.17**（同段 0050 +793.4%／−34.0%／1.17）"
                "⇒ 報酬與夏普都是三個 preset 最好的，**代價是回撤 −56.7%（比 0050 深 22.7pp）**；"
                "它同樣是 16 組裡事後挑出來的，walk-forward 顯示參數挑選接近擲骰子（見 `策略說明.md` §6.9）。",
        "knobs": {"POOL_N": "100", "FACTOR_REVENUE": "1", "MAX_PER_SECTOR": "0"},
    },
    "aggressive": {
        "label": "高報酬高回撤（池 150＋營收因子＋產業上限 2）",
        "desc": "**（已不是預設）**產業上限 2 檔換取較小回撤：把回撤從 revenue 的 −56.7% 壓到 −46.1%，代價是報酬少 138pp。"
                "2016-04~2026-10（實盤口徑）+1306.9%／MDD −46.1%／夏普 1.11（報酬與夏普都略輸 revenue，但回撤小 10.6pp）；"
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
    n = name or (DEFAULT_PRESET if is_default else "aggressive／revenue")
    head = (f"⚠️ 預設選股口徑 `{n}` 是「用更大的回撤換更高的歷史報酬」，不是穩健的超額報酬。"
            if is_default else
            f"⚠️ 你切換到 `{n}`：這是「用更大的回撤換更高的歷史報酬」，不是穩健的超額報酬。")
    return (
        head + "\n"
        "   · 報酬集中在 2016-2021 這段 in-sample 結果，而且是 16 組實驗裡事後挑出來的；"
        "walk-forward 六輪挑中三組、領先第二名最小只有 0.00 夏普（接近擲骰子），參數鄰居換一顆就掉一大截（尖峰不是平台）。\n"
        "   · 實盤口徑（`auto` 型態路由＋過熱閘門＋選股端過熱過濾、2016-04~2026-10）："
        "`revenue` +1445.2%／MDD **−56.7%**／夏普 1.17、`aggressive` +1306.9%／−46.1%／1.11、"
        "`current` +992.6%／−51.3%／1.02；0050 +793.4%／−34.0%／1.17 "
        "⇒ **夏普只打平 0050，回撤卻深 22.7pp**。\n"
        "   · 實測 84.8% 的選股會被路由到順勢策略（純動能暴露），2022 年 −24.0%、2023 年之後的相對優勢也很薄。\n"
        "   · 建議先用小額或紙上跑一段時間，再決定要不要把它用在正式資金上。"
    )
