"""core/park_asset.py — 實盤「閒置資金停泊」（2026-10-31 新增；**預設關閉**）

## 使用者裁定（2026-10-31）

1. **預設不停泊**；要用才設 `.env` 的 `SELFSELECT_PARK_ASSET=0050`（或任一 ETF／個股；預設值就是 0050）。
2. **只在「本月名單已建倉完成」之後**才把剩下的閒置資金停泊上去，不影響當月建倉。

## 為什麼要有它

回測 `IDLE_CASH_ASSET=0050` 會把每天閒置的錢（平均約 35–40% 的資金）押在 0050，這是主表報酬的一大半
（預設 `revenue`、2016-04~2026-10：停泊 +1445.2% vs 純現金 +656.9%，差 788pp）。實盤原本沒有這一步，
空手期就是現金（領 0%）⇒ 實盤與回測口徑對不上。本模組把「停泊」做成**可選、可控**的實盤行為。

## 設計邊界（刻意保守）

- **只在 immediate 模式**（`SELFSELECT_EXEC_MODE=immediate`）且名單每一檔都「已持有」或「今天已嘗試買進」時才停泊；
  `signal` 模式（等訊號）資金要留給尚未出現的訊號，因此**不停泊**。
- 停泊部位記在 **獨立帳本** `logs/park_position.json`，**不進** `holdings.json`／分帳本
  ⇒ 不會被「總數上限 N=5」「已持倉一律保留」「孤兒清倉」當成自選股。
- 要買股票時**先全部賣掉停泊部位**再買（單一動作、可稽核），不會邊買邊賣。
- 金額太小（< `MIN_PARK_NTD`）不做，避免手續費吃掉收益；以**整股**買進（0050 一張 ≈ 10 萬）。

## 純函式（`test/test_park_asset.py` 釘住）

`park_symbol()`／`idle_amount()`／`park_shares()`／`release_shares()`／`can_park_after_build()`／`enabled()`
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

STATE_PATH = "logs/park_position.json"
MIN_PARK_NTD = 10_000.0      # 低於這個金額不停泊（手續費不划算）
DEFAULT_SYMBOL = "0050"      # 使用者指定要停泊、但沒寫標的時的預設


def park_symbol(env=None) -> str:
    """要停泊的標的；未設定／空字串 ⇒ `""`（＝不停泊，這是預設行為）。"""
    src = os.environ if env is None else env
    raw = (src.get("SELFSELECT_PARK_ASSET") or "").strip()
    return raw


def enabled(env=None) -> bool:
    return bool(park_symbol(env))


def idle_amount(leg_capital: float, stock_value: float, park_value: float = 0.0) -> float:
    """可停泊金額 = 腿額度 − 自選股持股市值 − 目前已停泊市值（不足為 0）。"""
    try:
        return max(0.0, float(leg_capital) - float(stock_value) - float(park_value))
    except (TypeError, ValueError):
        return 0.0


def park_shares(idle: float, price: float, min_ntd: float = MIN_PARK_NTD) -> int:
    """可買幾股（整股、向下取整）；金額或價格不合理時回 0。"""
    try:
        idle, price, min_ntd = float(idle), float(price), float(min_ntd)
    except (TypeError, ValueError):
        return 0
    if price <= 0 or idle < max(min_ntd, price):
        return 0
    return int(idle // price)


def release_shares(need_cash: float, price: float, held_shares: int) -> int:
    """為了湊足 `need_cash` 要賣幾股（向上取整、不超過持有張數）。"""
    try:
        need_cash, price = float(need_cash), float(price)
        held = int(held_shares)
    except (TypeError, ValueError):
        return 0
    if price <= 0 or held <= 0 or need_cash <= 0:
        return 0
    need = int(math.ceil(need_cash / price))
    return max(0, min(held, need))


def can_park_after_build(exec_mode: str, watch_symbols, holdings: dict,
                         filled: dict, park_sym: str) -> bool:
    """名單是否「已建倉完成」：每一檔（排除停泊標的）都已持有或今天已嘗試買進。

    `exec_mode` 必須是 `immediate`（`signal` 模式要把資金留給還沒出現的訊號）。
    """
    if (exec_mode or "").strip().lower() != "immediate":
        return False
    syms = [s for s in (watch_symbols or []) if s and s != park_sym]
    if not syms:
        return False
    return all((holdings.get(s, 0) or 0) > 0 or s in (filled or {}) for s in syms)


def load_state(path: str | Path = STATE_PATH) -> dict:
    """讀停泊帳本；不存在或壞掉一律回空狀態（不讓停泊擋住交易）。"""
    try:
        p = Path(path)
        if not p.exists():
            return {"symbol": "", "shares": 0, "cost": 0.0}
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"symbol": str(d.get("symbol") or ""), "shares": int(d.get("shares") or 0),
                "cost": float(d.get("cost") or 0.0),
                "opened": d.get("opened"), "updated": d.get("updated"),
                "last_park_date": d.get("last_park_date")}
    except Exception:
        return {"symbol": "", "shares": 0, "cost": 0.0}


def save_state(state: dict, path: str | Path = STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
