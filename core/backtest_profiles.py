"""core/backtest_profiles.py — 回測「口徑」的具名設定（給使用者選）

## 為什麼要有 profile

同一套策略在不同「閒置資金怎麼算」下，報酬可以差一倍以上，很容易拿錯數字去跟 0050 比。
這裡把口徑變成**具名、可選**的：

| profile | 口徑 | 適合回答 | 特性 |
|---|---|---|---|
| `conservative` | 全現金（閒置資金領 0%），大盤年線開 | 「最壞情況下我會拿到什麼」 | 回撤最小（現金是避風港） |
| `fair` | 閒置資金停泊 `IDLE_CASH_ASSET`（預設 0050），年線開 | 「跟 0050 一樣滿倉，誰比較強」 | 總曝險≈100%、可直接比報酬 |
| `levered` | 部位放大到平均滿倉（`SCALE_TO_UTIL=100`，融資 6%/年） | 「等效滿倉，但用同一批部位」 | 需要融資，回撤放大 |
| `raw` | 舊口徑（不套大盤年線濾網、閒置領 0%） | 對照「若沒有年線濾網」 | 與實盤不一致，僅供研究 |

## 用法

    PROFILE=fair START=2022-01-01 END=2025-12-31 POOL_N=50 TOP_N=5 INITIAL=1000000 \
      .venv/bin/python scripts/backtest_plan2_monthly_3group.py

**明示的環境變數優先**：`PROFILE=fair IDLE_CASH_ASSET=00878 ...` 會用 00878（profile 只提供預設值）。
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {
    "default": {
        "label": "預設（zscore 評分 ＋ 停泊 0050）",
        "desc": "2026-10-29 起的預設口徑：zscore 評分＋閒置資金停泊 0050＋大盤年線開。"
                "2016-2025：+369.4%／年化 16.73%／MDD −34.6%／夏普 0.89。",
        "env": {
            "SCORING_MODEL": "zscore",
            "MARKET_FILTER": "1",
            "IDLE_CASH_ASSET": "0050",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "0",
            "LEVERAGE": "1",
        },
    },
    "conservative": {
        "label": "保守版（zscore 評分、全現金）",
        "desc": "同樣的 zscore 評分，但閒置資金領 0%（不押 0050）。回撤較小、總曝險只有 60% 左右。",
        "env": {
            "SCORING_MODEL": "zscore",
            "MARKET_FILTER": "1",
            "IDLE_CASH_ASSET": "",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "0",
            "LEVERAGE": "1",
        },
    },
    "fair": {
        "label": "公平版（舊評分 legacy ＋ 停泊 0050）",
        "desc": "保留舊評分器（legacy），只把閒置資金停泊 0050 ⇒ 用來單獨看「停泊」的效果（+57.0% → +203.5%）。",
        "env": {
            "SCORING_MODEL": "legacy",
            "MARKET_FILTER": "1",
            "IDLE_CASH_ASSET": "0050",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "0",
            "LEVERAGE": "1",
        },
    },
    "legacy": {
        "label": "舊版（legacy 評分、全現金、年線開）",
        "desc": "2026-10-29 之前的預設行為：legacy 綜合分＋閒置領 0%。+57.0%／夏普 0.41。",
        "env": {
            "SCORING_MODEL": "legacy",
            "MARKET_FILTER": "1",
            "IDLE_CASH_ASSET": "",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "0",
            "LEVERAGE": "1",
        },
    },
    "levered": {
        "label": "等效滿倉（融資放大）",
        "desc": "zscore 評分＋部位放大到平均曝險≈100%（SCALE_TO_UTIL=100），超額部位付 6%/年融資利息。",
        "env": {
            "SCORING_MODEL": "zscore",
            "MARKET_FILTER": "1",
            "IDLE_CASH_ASSET": "",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "100",
            "LEVERAGE": "1",
        },
    },
    "raw": {
        "label": "舊口徑（無年線濾網）",
        "desc": "legacy 評分＋不套大盤年線＋閒置領 0%。與實盤不一致，只當研究對照。",
        "env": {
            "SCORING_MODEL": "legacy",
            "MARKET_FILTER": "0",
            "IDLE_CASH_ASSET": "",
            "FILL_MODE": "proportional",
            "SCALE_TO_UTIL": "0",
            "LEVERAGE": "1",
        },
    },
}

DEFAULT_PROFILE = None      # 沒指定 PROFILE ⇒ 完全照環境變數（＝與舊行為相同）


def resolve(name: str | None) -> dict | None:
    """回傳 profile 定義；`None`／空字串 ⇒ `None`（不套用）。名稱不存在 → ValueError。"""
    if not name:
        return None
    key = str(name).strip().lower()
    if key not in PROFILES:
        raise ValueError(f"未知的 PROFILE='{name}'；可用：{', '.join(PROFILES)}")
    return PROFILES[key]


def expand(name: str | None, explicit: dict | None = None) -> dict:
    """把 profile 展開成 `{env: value}`；`explicit`（使用者明示的變數）優先，不被覆寫。"""
    prof = resolve(name)
    if prof is None:
        return {}
    explicit = explicit or {}
    out = {}
    for k, v in prof["env"].items():
        out[k] = explicit.get(k, v)
    return out


def describe() -> str:
    """給 CLI／文件用的說明表。"""
    lines = ["| profile | 名稱 | 內容 |", "|---|---|---|"]
    for k, p in PROFILES.items():
        env = "、".join(f"`{kk}={vv or '(空)'}`" for kk, vv in p["env"].items())
        lines.append(f"| `{k}` | {p['label']} | {p['desc']}（{env}） |")
    return "\n".join(lines)
