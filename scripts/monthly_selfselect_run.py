#!/usr/bin/env python3
"""scripts/monthly_selfselect_run.py — 自選股「每月作業」一條指令（SOP 步驟 1–4 合成）

把使用手冊「🤖 自選股每月作業流程（SOP）」的步驟 0–4 合成一支程式：

  0. **補資料**（V4.34）：重建市值排名 ＋ 把價格快取補到最近交易日（**只在盤後做**）
  1. 抓回實盤持股（VM 的 `logs/holdings.json`）
  2. 跑選股（`scripts/monthly_rebalance_picker.py`；含過熱過濾、法人確認、總數上限 N）
  3. 算出本機 `.env` 的 `PC_` 區段變更（新增本月選中者、汰換 0 股未選中者）
  4. （可選）把 `.env` scp 到 VM（scp 後比對本機／VM 的 md5）

⚠️ **為什麼一定要有步驟 0**（V4.34）：`monthly_rebalance_picker.py` **不會自己補價** ——
`stock_selector_grid.load_stock()` 只讀 `cache/selector_prices/*.pkl`，而補價函式 `ensure_fresh()`
只在 `stock_selector_grid.py --recommend` 裡跑。沒補價就會**用舊價格選股**：
實測 2026-09-22 那次跑的基準日是 **09-16**（落後 4 個交易日，`logs/monthly_pick.json` 的 `as_of` 就是證據）。
⇒ 本程式會在選股前補價，並在**基準日落後**時大聲警告、且**拒絕 `--apply`**（要硬寫得加 `--allow-stale-data`）。
補價寫入的是「當日日 K」，所以**盤中（交易日 13:30 前）一律跳過補價**（會把未定案的 K 棒寫進快取）。

⚠️ **想「修改選股結果」不要用手改 `.env` 的名單**（V4.33）：本程式的計畫是**由選股結果重算**的，
所以重跑時會把手動「刪掉的被選中股」加回來、把「手動新增的非選中股」當汰換刪掉。想剔除某檔請用
`--exclude`（宣告式、可重跑）；若已經手改好 `.env` 只想上傳，用 `--sync-only`（純上傳、不重算計畫，
但仍會擋「已持倉變成孤兒」這種會導致開盤清倉的錯誤）。

⚠️ **安全設計（刻意保留人為關卡）**
  - **預設 dry-run**：只印 diff 與摘要，不寫任何檔；要真的寫入必須加 `--apply`（會先備份 `.env`）。
  - **絕不刪除「已持倉」的股票**：實盤的孤兒清倉會在下一個交易日開盤把「有股數但不在 `.env`」的股票
    直接賣掉（繞過策略賣訊）⇒ 這是硬性檢查，違反就 `SafetyError` 中止。
  - **絕不動 `keep_wait` 條目**：keep_wait 視為人工管理（低接加碼型），選股程式不增不刪。
  - **不代跑部署**：程式改動仍需人工 `./deploy_source.sh`（部署硬規則）；本工具最多只 scp `.env`。

用法：
    # 只預覽（預設；會先補資料 → 抓回 holdings → 選股）
    .venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5

    # 真正寫入 .env（自動備份到 backups/）
    .venv/bin/python scripts/monthly_selfselect_run.py --apply

    # 寫入並把 .env 同步到 VM（不部署程式）
    .venv/bin/python scripts/monthly_selfselect_run.py --apply --sync-env-to-vm

    # 已經跑過 picker，想直接沿用上次結果（logs/monthly_pick.json）
    .venv/bin/python scripts/monthly_selfselect_run.py --reuse-pick --apply

    # 這次不想買 2884、2881（宣告式剔除，可重跑）
    .venv/bin/python scripts/monthly_selfselect_run.py --exclude 2884,2881 --apply --sync-env-to-vm

    # 已手改好本機 .env，只要上傳（不重跑選股、不改本機檔；上傳前驗孤兒）
    .venv/bin/python scripts/monthly_selfselect_run.py --sync-only

    # 特殊情況：不想動快取（--no-refresh-data）／明知基準日舊仍要寫（--allow-stale-data）
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 專案根：動態推導（container 內是 /app；不要寫死家目錄）
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())

# ⚠️ .env 一律以「檔案」為準（override=True）。原因（2026-10-01 實測）：
#   容器用 docker-compose `env_file` 在**建立容器時**把變數注入 process env，之後主機上改 `.env`
#   不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 不會覆蓋它們
#   ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。
#   主程式 `live_trader_multi.py` 也是 `load_dotenv(override=True)`（V4.36 熱重載）——這裡保持一致。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.isdir(_ROOT):
    os.chdir(_ROOT)

PICK_FILE = Path(os.getenv("MONTHLY_PICK_FILE", os.path.join("logs", "monthly_pick.json")))


class SafetyError(RuntimeError):
    """計畫違反安全規則（例如想刪掉已持倉的股票）。"""


# ── 解析 / 計畫（純函式，可獨立測試）────────────────────────────
def parse_pc_lines(env_text: str) -> dict:
    """回傳 `{代號: cfg dict}`（只含可解析的 PC_ 條目）。"""
    out = {}
    for line in env_text.splitlines():
        s = line.strip()
        if not (s.startswith("PC_") and "=" in s):
            continue
        sym = s[3:].split("=", 1)[0]
        val = s.split("=", 1)[1]
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        try:
            out[sym] = json.loads(val)
        except Exception:
            out[sym] = {"strategy": "?"}
    return out


def _pc_line(sym: str, cfg: dict) -> str:
    body = json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
    return f"PC_{sym}={body}"


def _is_clean_start(env_path=".env") -> bool:
    """全新安裝判定：`.env` 裡**一條 `PC_` 都沒有**（沒有任何監控/持股）⇒ 空 holdings 是合法狀態。

    為什麼需要：`logs/holdings.json` 沒有持倉時，程式原本一律中止 —— 那是為了擋「本機那份
    holdings 已經過期，會把持有中的股票當成沒持有」。但全新安裝（第一次跑、還沒建倉）
    兩邊都是空的，中止只會讓人卡住。只要 `.env` 也沒有 PC_ 條目，就沒有「被誤賣」的風險。
    """
    try:
        text = Path(env_path).read_text(encoding="utf-8")
    except Exception:
        return False
    return not any(line.strip().startswith("PC_") for line in text.splitlines())


def resolve_leg_alloc(cur_leg=0.0, top_n=5, args_leg_pct=None, args_per_name=None,
                      env_leg_pct=None):
    """決定「每檔 alloc」→ `(per_name, leg_pct, 來源說明)`。

    優先序：`--per-name-alloc` ＞ `--leg-pct` ＞ `.env` 現有腿額度 ＞ `SELFSELECT_LEG_PCT`（預設 100）÷ N。

    本專案只有一條腿，所以預設把全部資金分給 N 檔（100 ÷ N）；想留現金就調低 `SELFSELECT_LEG_PCT`。

    ⚠️ 2026-10-17（「從零重來」後修）：`.env` 的 `PC_*` 被清空時 `cur_leg` 會是 0。
    舊碼直接 `0 ÷ N = 0%`（等於不分配）；而 `monthly_rebalance_picker.py` 那邊更糟，
    它固定建議 `100 ÷ N`（5 檔＝每檔 20%、合計 100% ⇒ 再加上其他部位就爆表）。
    現在改成有明確的腿額度來源與預設值，並把來源印出來。
    """
    n = max(1, int(top_n or 5))
    if args_per_name is not None:
        return round(float(args_per_name), 2), round(float(args_per_name) * n, 2), "命令列 --per-name-alloc"
    if args_leg_pct is not None:
        return round(float(args_leg_pct) / n, 2), float(args_leg_pct), "命令列 --leg-pct"
    if cur_leg and float(cur_leg) > 0:
        return round(float(cur_leg) / n, 2), float(cur_leg), ".env 現有自選股腿額度"
    pct = float(env_leg_pct if env_leg_pct is not None
                else os.getenv("SELFSELECT_LEG_PCT", "100") or 100)
    return round(pct / n, 2), pct, f"SELFSELECT_LEG_PCT={pct:g}%（預設 100%）"


def plan_env_changes(env_text: str, held: dict, selected: list, per_name_alloc: float,
                     total_capital: float = 0.0, force_remove=None, prices: dict = None,
                     realloc: bool = False):
    """算出 `.env` 要怎麼改 → dict（含 `env_text` 新版、`add`/`remove`/`keep_held`、`warnings`、`summary`）。

    規則（與使用手冊 SOP 一致）：
      · 已持倉（held>0）→ **一律保留**
      · 非 keep_wait、0 股、且本月未選中 → 移除（汰換）
      · 本月選中、尚未在 `.env` → 新增（`per_name_alloc`%）
      · keep_wait 條目完全不動
    """
    cur = parse_pc_lines(env_text)
    selected = [str(s) for s in selected]
    force_remove = set(str(s) for s in (force_remove or []))

    keep_held, remove, add, keep_sel = [], [], [], []
    for sym, cfg in cur.items():
        if cfg.get("strategy") == "keep_wait":
            continue                                    # keep_wait＝人工管理：完全不動
        if held.get(sym, 0) > 0:
            keep_held.append(sym)                       # 已持倉：保留
        elif sym in selected:
            keep_sel.append(sym)                        # 本月仍有選中：留著
        else:
            remove.append(sym)                          # 0 股且未選中：汰換
    for sym in selected:
        if sym not in cur and held.get(sym, 0) <= 0:
            add.append(sym)

    # ── 硬性安全檢查 ────────────────────────────────────────────
    offenders = sorted({s for s in remove if held.get(s, 0) > 0} | set(force_remove))
    if offenders:
        raise SafetyError(
            f"計畫要移除『已持倉』的股票 {offenders} —— 這會讓實盤在下一個交易日開盤把它們清倉賣掉，"
            f"因此拒絕產生計畫（請檢查 holdings 是否為實盤最新）")

    remove_set = set(remove)
    kept_lines = []
    for line in env_text.split("\n"):
        s = line.strip()
        if s.startswith("PC_") and "=" in s:
            sym = s[3:].split("=", 1)[0]
            if sym in remove_set:
                continue                                # 汰換：刪掉該行
        kept_lines.append(line)
    new_env = "\n".join(kept_lines)

    def _new_lines():
        prices_ = prices or {}
        out = []
        for sym in add:
            cfg = {"strategy": "auto", "alloc": round(per_name_alloc, 2)}
            if prices_.get(sym):
                cfg["max_entry_price"] = round(float(prices_[sym]), 2)   # 選股當日價（僅記錄）
            out.append(_pc_line(sym, cfg))
        return out

    if realloc or add:
        final_lines = new_env.split("\n")
        if realloc:
            for i, line in enumerate(final_lines):
                st = line.strip()
                if st.startswith("PC_") and "=" in st:
                    sym_i = st[3:].split("=", 1)[0]
                    cfg_i = cur.get(sym_i, {})
                    if cfg_i.get("strategy") != "keep_wait" and cfg_i:
                        cfg_new = dict(cfg_i)
                        cfg_new["alloc"] = round(per_name_alloc, 2)
                        # 保留原本的行尾註解（例：「已持倉 689 股：保留到賣訊」）
                        _tail = line.split("=", 1)[1] if "=" in line else ""
                        _cmt = ("   #" + _tail.split("#", 1)[1]) if "#" in _tail else ""
                        final_lines[i] = _pc_line(sym_i, cfg_new) + _cmt
        if add:
            # 插在「最後一條非 keep_wait 的 PC_」之後（保持. env 區段語意），找不到才附在檔尾
            idx = None
            for i, line in enumerate(final_lines):
                st = line.strip()
                if st.startswith("PC_") and "=" in st:
                    if cur.get(st[3:].split("=", 1)[0], {}).get("strategy") != "keep_wait":
                        idx = i
            block = _new_lines()
            if idx is not None:
                final_lines[idx + 1:idx + 1] = block
            else:
                final_lines += block
        new_env = "\n".join(final_lines)

    # ── 檢查與摘要 ─────────────────────────────────────────────
    final = parse_pc_lines(new_env)
    total_alloc = sum(float(c.get("alloc", 0) or 0) for c in final.values())
    keep_alloc = sum(float(c.get("alloc", 0) or 0) for s, c in final.items()
                     if c.get("strategy") == "keep_wait")
    leg_alloc = total_alloc - keep_alloc
    warnings = []
    if total_alloc > 100.0:
        warnings.append(f"ΣPC_ alloc = {total_alloc:.1f}% 超過 100%（其中 keep_wait {keep_alloc:.1f}%）"
                        f"⇒ 請調低 alloc 或 SELFSELECT_LEG_PCT")
    new_buy_amount = round(len(add) * (per_name_alloc / 100.0) * (total_capital or 0))
    summary = (f"新增 {len(add)} 檔 {add or ''}｜保留已持倉 {len(keep_held)} 檔 {sorted(keep_held)}"
               f"｜汰換 {len(remove)} 檔 {sorted(remove)}"
               f"｜腿額度 {leg_alloc:.1f}%（keep_wait {keep_alloc:.1f}%、合計 {total_alloc:.1f}%）"
               + (f"｜本次新買約 NT${new_buy_amount:,}（{len(add)}×{per_name_alloc}%×"
                  f"NT${total_capital:,.0f}）" if new_buy_amount else ""))
    return {"env_text": new_env, "add": add, "remove": remove, "keep_held": sorted(keep_held),
            "keep_selected": sorted(keep_sel), "total_alloc": total_alloc,
            "leg_alloc": leg_alloc, "keep_wait_alloc": keep_alloc,
            "new_buy_amount": new_buy_amount, "warnings": warnings, "summary": summary,
            "selected": selected}


def unified_diff(old: str, new: str) -> str:
    import difflib
    return "".join(difflib.unified_diff(old.splitlines(keepends=True),
                                        new.splitlines(keepends=True),
                                        fromfile=".env (現在)", tofile=".env (計畫)"))


def parse_exclude(raw) -> list:
    """`--exclude 2884,2881` / `--exclude 2884 --exclude 2881` → `["2884", "2881"]`（去重、保序）。"""
    out = []
    for item in (raw or []):
        for s in str(item).replace(";", ",").split(","):
            s = s.strip()
            if s and s not in out:
                out.append(s)
    return out


def validate_env_for_push(env_text: str, held: dict) -> list:
    """上傳 `.env` 前的安全檢查（純函式）→ 問題清單（空 = 可以上傳）。

    最重要的一條：**已持倉的股票不可變成孤兒**。實盤對「有股數但不在 `.env`」的股票，
    會在下一個交易日開盤直接清倉（繞過策略賣訊）⇒ 手改 `.env` 最容易犯的致命錯誤。
    """
    cur = parse_pc_lines(env_text)
    problems = []
    orphans = sorted(str(s) for s, q in (held or {}).items() if q > 0 and str(s) not in cur)
    if orphans:
        problems.append(f"已持倉但不在 .env：{orphans} ⇒ 上傳後實盤會在下一個交易日開盤把它們清倉賣掉")
    if not cur:
        problems.append("解析不到任何 PC_ 條目 ⇒ .env 可能被改壞了")
    bad = sorted(s for s, c in cur.items() if c.get("strategy") == "?")
    if bad:
        problems.append(f"PC_ 條目 JSON 解析失敗：{bad} ⇒ 該行格式有誤，程式會忽略它")
    return problems


def env_md5(path) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ── 步驟 0：補資料（V4.34）─────────────────────────────────────
REFRESH_STEPS = (
    ("rebuild_mcap_ranking.py", "重建市值排名 cache/inst_momentum/mcap_ranking.pkl"),
    ("append_selector_prices.py", "把 cache/selector_prices/ 補到最近交易日"),
)


def _is_trading_date(d) -> bool:
    """該日期是否為台股交易日（日曆壞掉時保守回「非週末即交易日」）。"""
    try:
        from core.trading_calendar import TradingCalendar
        return bool(TradingCalendar().is_trading_day(d))
    except Exception:
        return d.weekday() < 5


def expected_data_date(now=None) -> str:
    """選股基準日**應該**是什麼 ＝ 最後一個已收盤的交易日（YYYY-MM-DD）。

    交易日但尚未收盤（13:30 前）⇒ 前一個交易日（今天的日 K 還沒定案，不該當基準）。
    """
    from datetime import timedelta
    now = now or datetime.now()
    d = now.date()
    if _is_trading_date(d) and (now.hour, now.minute) < (13, 30):
        d -= timedelta(days=1)
    for _ in range(30):
        if _is_trading_date(d):
            return d.isoformat()
        d -= timedelta(days=1)
    return d.isoformat()


def refresh_guard_reason(now=None):
    """現在「不該補價」的原因；`None` ＝ 可以補價。

    為什麼：補價寫入的是**當日日 K**。盤中（交易日 13:30 前）那根 K 棒還沒定案，
    寫進快取就成為選股基準日 ⇒ 用半成品資料選股（2026-09-17 的 NaN K 棒就是同一類事故）。
    """
    now = now or datetime.now()
    if _is_trading_date(now.date()) and (now.hour, now.minute) < (13, 30):
        return (f"現在是盤中（{now.strftime('%H:%M')}，交易日 13:30 前）⇒ 跳過補價："
                f"補價會把未定案的當日 K 棒寫進快取")
    return None


def refresh_basis_data(root=None, runner=None, now=None, allow_intraday=False):
    """跑步驟 0 的兩支腳本 → `{"skipped": 原因}` 或 `{"results": [(腳本, rc, 訊息)]}`。

    兩支腳本都**預設 dry-run**，這裡一律加 `--apply` 才會真的寫入（寫入前它們各自備份舊檔）。
    任何失敗都**不阻斷**後續選股（`使用手冊` §10.7 的既有原則）——
    資料新不新鮮由 `basis_data_warning()` 在寫入 `.env` 前把關。
    """
    root = root or _ROOT
    runner = runner or subprocess.run
    reason = None if allow_intraday else refresh_guard_reason(now)
    if reason:
        return {"skipped": reason}
    results = []
    for script, desc in REFRESH_STEPS:
        path = os.path.join(root, "scripts", script)
        if not os.path.exists(path):
            results.append((script, None, f"找不到 {path} ⇒ 略過（{desc}）"))
            continue
        cmd = [sys.executable, path, "--apply"]
        try:
            r = runner(cmd, capture_output=True, text=True)
        except Exception as e:
            results.append((script, None, f"{type(e).__name__}: {e}"))
            continue
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        tail = out[-1] if out else ""
        results.append((script, r.returncode, tail))
    return {"results": results}


def basis_data_latest_date(cache_dir=None):
    """目前 `cache/selector_prices/` 的最新日期（抽樣 40 檔取最大值；讀不到回 None）。"""
    from core.cache_io import load_cache
    d = cache_dir or os.path.join(_ROOT, "cache", "selector_prices")
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.endswith(".pkl"))
    newest = None
    for f in files[:40]:
        try:
            df, _ = load_cache(os.path.join(d, f))
            if df is None or df.empty:
                continue
            last = str(df.index[-1])[:10]
            if newest is None or last > newest:
                newest = last
        except Exception:
            continue
    return newest


def basis_data_warning(as_of, expected, latest_cache=None):
    """基準日落後時回傳警告字串（否則 `None`）。as_of ＝ picker 回報的選股基準日。"""
    as_of = str(as_of or "")[:10]
    if not as_of or not expected:
        return None
    if as_of >= expected:
        return None
    msg = (f"選股基準日 {as_of} 落後預期的 {expected} ⇒ 這次選股用的是**過期資料**"
           f"（落後 {_trading_days_between(as_of, expected)} 個交易日）")
    if latest_cache and latest_cache < expected:
        msg += f"；價格快取最新只到 {latest_cache}"
    return msg


def _trading_days_between(a: str, b: str) -> int:
    """a（不含）到 b（含）之間的交易日數（日曆壞掉時回 0）。"""
    from datetime import date as _date, timedelta
    try:
        d0, d1 = _date.fromisoformat(a), _date.fromisoformat(b)
    except Exception:
        return 0
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if _is_trading_date(d):
            n += 1
    return n


def push_env_to_vm(env_path, vm: str = "tw-autotrader", zone: str = "asia-east1-b", runner=None):
    """scp `.env` 到 VM 的**專案目錄**（`SYNC_VM_HOME/.env`），再比對遠端 md5。

    回傳 `(ok, msg, local_md5, remote_md5)`（只上傳 `.env`，不部署程式）。

    ⚠️ 2026-10-26 修 bug：原本寫 `f"{vm}:~/{env_path}"`，`env_path` 是相對路徑 `.env`
    ⇒ 實際上傳到 VM 家目錄 `~/.env`，容器（掛載 `./.env`）根本讀不到，還會在 VM 家目錄
    留下一個孤兒檔案。現在改用 `.env` 的 `SYNC_VM_HOME`（預設 `~/tw-selfselect`）組遠端路徑。
    """
    runner = runner or subprocess.run
    local = env_md5(env_path)
    remote_dir = (os.getenv("SYNC_VM_HOME", "~/tw-selfselect") or "~/tw-selfselect").rstrip("/")
    remote_env = f"{remote_dir}/.env"
    r = runner(["gcloud", "compute", "scp", str(env_path), f"{vm}:{remote_env}",
                "--zone", zone, "--quiet"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"scp 失敗：{(r.stderr or '')[:300]}", local, None
    remote = None
    try:
        r2 = runner(["gcloud", "compute", "ssh", vm, "--zone", zone, "--quiet", "--command",
                     f"md5sum {remote_env}"], capture_output=True, text=True)
        if r2.returncode == 0 and (r2.stdout or "").strip():
            remote = r2.stdout.split()[0]
    except Exception:
        pass
    return True, "", local, remote


def resolve_pool_n(cli_value=None, env=None) -> int:
    """候選池大小：`--pool-n` ＞ `SELFSELECT_POOL_N` ＞ `SELFSELECT_PRESET` 的池 ＞ 100。

    （2026-10-29 加 preset：使用者切 `SELFSELECT_PRESET=aggressive` 時，池會變 150，
    除非另外明示 `SELFSELECT_POOL_N`；預設 preset `current` ⇒ 行為與舊版完全相同。）
    """
    src = env if env is not None else os.environ
    if cli_value:
        try:
            return max(1, int(cli_value))
        except (TypeError, ValueError):
            pass
    try:
        n = int(src.get("SELFSELECT_POOL_N", ""))
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    try:
        from core.selection_presets import active_name, resolve
        prof = resolve(active_name(src))
        if prof:
            n = int(prof["knobs"].get("POOL_N") or 0)
    except (ImportError, ValueError):
        n = 0
    return n if n > 0 else 100


def build_picker_cmd(args, pool_n: int) -> list:
    """組 picker 指令（純函式；2026-10-27 起接上 `--pool-n`）。"""
    cmd = [sys.executable, os.path.join(_ROOT, "scripts", "monthly_rebalance_picker.py"),
           "--risk", args.risk, "--top-n", str(args.top_n), "--pool-n", str(pool_n)]
    if getattr(args, "sync_holdings_from_vm", False):
        cmd += ["--sync-holdings-from-vm", "--vm", args.vm, "--zone", args.zone]
    if getattr(args, "allow_stale_holdings", False):
        cmd.append("--allow-stale-holdings")
    if getattr(args, "ignore_drawback", False):
        cmd.append("--ignore-drawback")
    return cmd


# ── CLI ────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="自選股每月作業（SOP 1–4 一條指令；預設只預覽）")
    p.add_argument("--risk", choices=["high_profit", "normal"], default="normal")
    p.add_argument("--top-n", type=int, default=5, help="本腿總檔數上限 N（預設 5）")
    p.add_argument("--pool-n", type=int, default=None,
                   help="候選池大小（誠實池）；預設讀 SELFSELECT_POOL_N，再退 100")
    p.add_argument("--leg-pct", type=float, default=None,
                   help="本腿資金上限 %%（預設＝沿用現有 .env 的腿額度）；每檔 alloc＝leg_pct ÷ top_n")
    p.add_argument("--per-name-alloc", type=float, default=None, help="直接指定每檔 alloc%%（覆寫 --leg-pct）")
    p.add_argument("--env", default=".env")
    p.add_argument("--sync-holdings-from-vm", action="store_true", default=None,
                   help="先從 VM 抓回實盤 logs/holdings.json（預設開）")
    p.add_argument("--no-sync", dest="sync_holdings_from_vm", action="store_false")
    p.add_argument("--reuse-pick", action="store_true",
                   help="沿用上次 picker 結果（logs/monthly_pick.json），不重跑選股")
    p.add_argument("--allow-stale-holdings", action="store_true")
    p.add_argument("--realloc", action="store_true",
                   help="把本腿所有條目的 alloc 一併重設為 --per-name-alloc（腿額度 ÷ N）")
    p.add_argument("--exclude", action="append", metavar="SYM[,SYM]",
                   help="宣告式剔除本月選中的股票（可重複／逗號分隔）；只影響「不新買」，已持倉不受影響")
    p.add_argument("--sync-only", action="store_true",
                   help="純上傳本機 .env 到 VM（不重跑選股、不改本機檔）；上傳前驗『已持倉不可成孤兒』")
    p.add_argument("--refresh-data", action="store_true", default=True,
                   help="選股前補資料（重建市值排名＋補價；預設開，V4.34）")
    p.add_argument("--no-refresh-data", dest="refresh_data", action="store_false",
                   help="跳過步驟 0（只用現有快取；基準日落後會被擋 --apply）")
    p.add_argument("--allow-stale-data", action="store_true",
                   help="基準日落後仍要寫入 .env（風險自負；預設拒絕）")
    p.add_argument("--allow-intraday-refresh", action="store_true",
                   help="盤中也補價（危險：會把未定案的當日 K 寫進快取；只在你很清楚後果時用）")
    p.add_argument("--ignore-drawback", action="store_true",
                   help="忽略 MIN_DRAW_BACK 回撤保護（預設：回撤超標就本次續抱、不改 .env）")
    p.add_argument("--apply", action="store_true", help="真的寫入 .env（預設只預覽；會先備份）")
    p.add_argument("--picks", default="", help="外部指定選股結果（逗號分隔代號；AI 選股用，會跳過內建選股）")
    p.add_argument("--picks-file", default="", help="外部選股結果 JSON（{'as_of':...,'selected':[{'sid':...}]}）")
    p.add_argument("--ai", action="store_true",
                   help="標記本次是 AI 選股（寫入成功後在 logs/selfselect_auto.json 記 ai_applied，避免 D1 fallback 覆蓋）")
    p.add_argument("--sync-env-to-vm", action="store_true", help="寫入後把 .env scp 到 VM（不部署程式）")
    p.add_argument("--vm", default=os.getenv("SYNC_VM_NAME"), help="VM 名稱（預設讀 .env 的 SYNC_VM_NAME）")
    p.add_argument("--zone", default=os.getenv("SYNC_VM_ZONE", "asia-east1-b"))
    args = p.parse_args()
    # 預設值：有設定 SYNC_VM_NAME（或 --vm）就預設「先從 VM 抓回實盤持股」（安全優先，避免用舊資料判孤兒）；
    # 沒設定就跳過（本機使用者 / 單機部署的情境），並在下面印提醒。
    if args.sync_holdings_from_vm is None:
        args.sync_holdings_from_vm = bool(args.vm)
    if args.sync_holdings_from_vm and not args.vm:
        print("⚠️ 未設定 SYNC_VM_NAME（VM 名稱）⇒ 跳過『從 VM 抓回實盤持股』，改用本機 logs/holdings.json")
        args.sync_holdings_from_vm = False

    exclude = parse_exclude(args.exclude)
    if args.sync_only and (args.apply or args.realloc or args.exclude or args.reuse_pick):
        sys.exit("❌ --sync-only 是『純上傳本機 .env』，不能與 "
                 "--apply / --realloc / --exclude / --reuse-pick 併用（它不重算計畫）")
    if args.sync_only and args.refresh_data:
        args.refresh_data = False          # 純上傳不需要補資料

    env_path = Path(args.env)
    if not env_path.exists():
        sys.exit(f"❌ 找不到 {env_path}")
    env_text = env_path.read_text(encoding="utf-8")

    def _load_held():
        try:
            from core.live_state import held_quantities, load_json
            return held_quantities(load_json("logs/holdings.json", {}))
        except Exception as e:
            sys.exit(f"❌ 讀不到 logs/holdings.json（{e}）→ 中止（沒有可信持股就不能改 .env）")

    # 0) 純上傳模式：不重跑選股、不改本機 .env，只驗安全後 scp
    if args.sync_only:
        held = _load_held()
        if not held:
            # 2026-10-17：從零重來後「空倉」是合法狀態；只要持股是剛從 VM 抓回來的就放行，
            #   但一律提醒對帳（避免帳實不符時把持股當不存在）。
            if not getattr(args, "sync_holdings_from_vm", False) and not _is_clean_start(args.env):
                sys.exit("❌ logs/holdings.json 沒有持倉 → 中止（請用 --sync-holdings-from-vm 更新；"
                         "全新安裝且 .env 也沒有任何 PC_ 條目時會自動放行）")
            print("⚠️ logs/holdings.json 沒有持倉（空倉，來源＝VM 實盤）"
                  "—— 若帳戶其實有持股請先跑 scripts/reconcile_broker_books.py")
        problems = validate_env_for_push(env_text, held)
        if problems:
            for pr in problems:
                print(f"❌ {pr}")
            sys.exit(f"❌ {env_path} 未通過上傳前安全檢查 → 中止，未同步（本機檔未動）")
        print(f"ℹ️ 上傳前檢查通過：{len(parse_pc_lines(env_text))} 條 PC_、"
              f"實盤持股 {len(held)} 檔都在 .env（無孤兒）")
        ok, msg, local, remote = push_env_to_vm(env_path, args.vm, args.zone)
        if not ok:
            sys.exit(f"❌ .env 同步失敗：{msg}")
        print(f"✅ 已上傳 {env_path} → VM（本機 md5 {local[:12]}…）")
        if remote is None:
            print("⚠️  無法回讀 VM 的 md5（SSH 失敗）⇒ 請自行確認："
                  f"gcloud compute ssh {args.vm} --zone={args.zone} --command='md5sum ~/{env_path}'")
        elif remote == local:
            print(f"✅ VM 端 md5 一致（{remote[:12]}…）⇒ 內容確認相同")
        else:
            print(f"⚠️  VM 端 md5 不一致（VM {remote[:12]}… vs 本機 {local[:12]}…）⇒ 請重跑一次")
        print("ℹ️ 不必重啟容器：主程式 08:40 熱重載 .env（急件再人工重啟）")
        return

    # 1a) 外部選股結果（AI 選股／人工指定）：不跑內建選股器，其餘安全檢查完全不變
    external_pick = None
    if args.picks or args.picks_file:
        if args.picks and args.picks_file:
            sys.exit("❌ --picks 與 --picks-file 只能擇一")
        if args.picks_file:
            try:
                doc = json.loads(Path(args.picks_file).read_text(encoding="utf-8"))
            except Exception as e:
                sys.exit(f"❌ 讀不到 --picks-file（{e}）")
            sids, as_of = [], doc.get("as_of")
            for x in doc.get("selected") or doc.get("picks") or []:
                sids.append(x["sid"] if isinstance(x, dict) else str(x))
        else:
            sids = [x.strip() for x in args.picks.split(",") if x.strip()]
            as_of = None
        if not sids:
            sys.exit("❌ 外部選股結果是空的")
        external_pick = {"as_of": as_of or expected_data_date(), "risk_label": "AI 選股",
                         "source": "external", "selected": [{"sid": x} for x in sids]}
        print(f"ℹ️ 使用外部選股結果（{len(sids)} 檔）：{', '.join(sids)}"
              f"（基準日 {external_pick['as_of']}）")

    # 1) 抓實盤持股 + 2) 跑選股
    if external_pick is not None:
        pass        # 已指定名單，不必跑選股器
    elif args.reuse_pick:
        if not PICK_FILE.exists():
            sys.exit(f"❌ --reuse-pick 但找不到 {PICK_FILE}")
        print(f"ℹ️ 沿用上次建議：{PICK_FILE}")
        if args.refresh_data:
            print("ℹ️ --reuse-pick：不補資料（沿用既有選股結果；基準日仍會被檢查）")
    else:
        # 0) 補資料（V4.34）：先讓基準日是新鮮的，否則等於用舊價格選股
        if args.refresh_data:
            _rep = refresh_basis_data(allow_intraday=args.allow_intraday_refresh)
            if "skipped" in _rep:
                print(f"⚠️  步驟 0 跳過：{_rep['skipped']}")
            else:
                print("▶ 步驟 0：補資料（市值排名 ＋ 價格快取）")
                for script, rc, tail in _rep["results"]:
                    print(f"   {'✅' if rc == 0 else '⚠️ '} {script}: {tail}")
        pool_n = resolve_pool_n(args.pool_n)
        cmd = build_picker_cmd(args, pool_n)
        print(f"▶ 候選池：當時市值前 {pool_n} 檔")
        try:      # preset 想用的池與實際不同時要講出來（否則會拿別的口徑的回測數字套在自己身上）
            from core.selection_presets import PRESETS, active_name
            _preset = active_name()
            _want = PRESETS[_preset]["knobs"]["POOL_N"]
            if _preset != "current" and str(pool_n) != str(_want):
                print(f"⚠️ preset `{_preset}` 預設池 {_want} 檔，但目前用 {pool_n} 檔"
                      f"（`SELFSELECT_POOL_N` 優先）⇒ 該 preset 的回測數字不適用在這個池上")
        except (ImportError, KeyError, ValueError):
            pass
        print("▶", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout[-3000:] if r.stdout else "")
        if r.returncode != 0:
            print(r.stderr[-1500:] if r.stderr else "")
            if r.returncode == 3:
                print("🛡️ MIN_DRAW_BACK 觸發 ⇒ 本次續抱（維持現有名單、不改 .env、不重試）")
                return
            sys.exit(f"❌ 選股失敗（returncode={r.returncode}）→ 中止，未改任何檔")

    pick = external_pick if external_pick is not None else json.loads(PICK_FILE.read_text(encoding="utf-8"))
    selected_all = [x["sid"] for x in pick.get("selected", [])]
    selected = [s for s in selected_all if s not in exclude]
    held = _load_held()
    if not held:
        if not getattr(args, "sync_holdings_from_vm", False) and not _is_clean_start(args.env):
            sys.exit("❌ logs/holdings.json 沒有持倉 → 中止（請確認是否為實盤最新；本機流程請用 "
                     "--sync-holdings-from-vm）")
        print("⚠️ 實盤沒有持倉（空倉）⇒ 本次所有選中標的都視為新買；"
              "若帳戶其實有持股請先跑 scripts/reconcile_broker_books.py")

    # 每檔 alloc：--per-name-alloc 優先，其次 leg_pct ÷ N，最後沿用現有腿額度 ÷ N
    cur_cfg = parse_pc_lines(env_text)
    cur_leg = sum(float(c.get("alloc", 0) or 0) for c in cur_cfg.values()
                  if c.get("strategy") != "keep_wait")
    per_name, leg_pct, leg_src = resolve_leg_alloc(
        cur_leg=cur_leg, top_n=args.top_n,
        args_leg_pct=args.leg_pct, args_per_name=args.per_name_alloc)
    tc = float(os.getenv("TOTAL_CAPITAL", "0") or 0)
    for line in env_text.splitlines():
        if line.strip().startswith("TOTAL_CAPITAL="):
            try:
                tc = float(line.split("=", 1)[1].split("#")[0].strip())
            except Exception:
                pass

    # 3) 計畫
    prices = {x["sid"]: x.get("price") for x in pick.get("selected", [])}
    plan = plan_env_changes(env_text, held, selected, per_name_alloc=per_name,
                            total_capital=tc, prices=prices, realloc=args.realloc)
    # 基準日把關（V4.34）：選股用的價格資料若落後，這個計畫就是「用舊價格算出來的」
    _expected = expected_data_date()
    _stale_msg = basis_data_warning(pick.get("as_of"), _expected, basis_data_latest_date())
    print("\n" + "=" * 60)
    print(f"選股結果（{pick.get('as_of', '?')}／{pick.get('risk_label', args.risk)}／N={args.top_n}）")
    if _stale_msg:
        print(f"⚠️  {_stale_msg}")
        if args.refresh_data and not args.reuse_pick:
            print("   ⇒ 步驟 0 補價沒有成功（看上面的步驟 0 輸出）；"
                  "可手動跑 scripts/append_selector_prices.py --apply 後重跑")
    else:
        print(f"  資料基準日：{str(pick.get('as_of', ''))[:10]}（預期 {_expected}）✅")
    print(f"  本月選出：{', '.join(selected) or '（無）'}")
    if exclude:
        print(f"  人工剔除：{', '.join(exclude)}"
              f"（其中 {', '.join(s for s in exclude if s in selected_all) or '無'} 原本有選中）")
    print(f"  實盤持股：{held}")
    print(f"  每檔 alloc：{per_name}%（腿額度 {leg_pct}% ÷ {args.top_n}；來源：{leg_src}）")
    print("=" * 60)
    print(plan["summary"])
    for w in plan["warnings"]:
        print(f"⚠️  {w}")
    for s in exclude:
        if held.get(s, 0) > 0:
            print(f"ℹ️  剔除的 {s} 仍有持股 {held[s]} 股 ⇒ 仍保留在 .env，"
                  f"要等它的賣訊才會出場（剔除只代表本月不新買）")
        elif s in cur_cfg:
            print(f"ℹ️  剔除的 {s} 在 .env 但 0 股 ⇒ 本月未選中，會被汰換刪除（不會下單）")
    print("\n--- .env diff ---")
    print(unified_diff(env_text, plan["env_text"]) or "（無變更）")

    if not args.apply:
        print("\nℹ️ 這是 dry-run，未寫入任何檔。確認無誤後加 --apply 真正寫入。")
        if _stale_msg:
            print("⚠️  注意：基準日落後 ⇒ 即使加 --apply 也會被拒絕（除非 --allow-stale-data）")
        return

    if _stale_msg and not args.allow_stale_data:
        sys.exit(f"❌ 拒絕寫入 .env：{_stale_msg}\n"
                 f"   ⇒ 先讓資料變新鮮（.venv/bin/python scripts/append_selector_prices.py --apply，"
                 f"盤後執行）再重跑；確定要用過期資料才加 --allow-stale-data")

    # 4) 寫入（備份）＋（可選）scp
    (Path("backups")).mkdir(parents=True, exist_ok=True)
    bak = Path("backups") / f".env.bak-selfselect-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(env_path, bak)
    env_path.write_text(plan["env_text"], encoding="utf-8")
    print(f"\n✅ 已寫入 {env_path}（備份：{bak}）")
    if args.ai or external_pick is not None:
        # 外部（AI）選股寫入成功 ⇒ 標記本月完成，避免 D1 fallback 用規則選股覆蓋
        try:
            from core.selfselect_scheduler import mark_applied
            _src = "ai" if args.ai else "external"
            mark_applied(picks=selected, source=_src if _src == "ai" else "external")
            print(f"✅ 已標記本月選股完成（source={_src}）：{', '.join(selected)}")
        except Exception as e:
            print(f"⚠️ 無法寫入選股狀態（可能導致 D1 fallback 覆蓋這份名單）：{e}")
    if plan["add"]:
        print(f"   下一個交易日 13:25–13:30 預期買進：{', '.join(plan['add'])}"
              f"（各約 NT${round(per_name / 100 * tc):,}）")
    if plan["remove"]:
        print(f"   已從 .env 移除（0 股，不會下單）：{', '.join(plan['remove'])}")

    if args.sync_env_to_vm:
        problems = validate_env_for_push(env_path.read_text(encoding="utf-8"), held)
        if problems:
            for pr in problems:
                print(f"❌ {pr}")
            sys.exit("❌ 寫入後的 .env 未通過安全檢查 → 中止同步（本機檔已寫入，可從備份還原）")
        ok, msg, local, remote = push_env_to_vm(env_path, args.vm, args.zone)
        if not ok:
            print(f"❌ .env 同步失敗：{msg}")
        else:
            print(f"✅ .env 已同步到 VM（本機 md5 {local[:12]}…）")
            if remote is None:
                print("⚠️  無法回讀 VM 的 md5（SSH 失敗）⇒ 請自行確認 VM 上的檔案")
            elif remote == local:
                print(f"✅ VM 端 md5 一致（{remote[:12]}…）⇒ 內容確認相同")
            else:
                print(f"⚠️  VM 端 md5 不一致（VM {remote[:12]}… vs 本機 {local[:12]}…）⇒ 請重跑一次")
    else:
        print("ℹ️ 尚未同步到 VM：可執行 `--sync-only` 純上傳本機 .env（若同時有**程式**改動，"
              "一定要人工跑 ./deploy_source.sh）")
    print("ℹ️ 收尾建議：docker exec tw_selfselect_bot python scripts/check_holdings_vs_env.py（驗孤兒）")


if __name__ == "__main__":
    try:
        main()
    except SafetyError as _e:
        # 容器內自動選股（core/selfselect_scheduler）也會呼叫本檔；乾淨收尾比 traceback 好判斷
        print(f"❌ {_e}")
        print("   ⇒ 未改任何檔（安全檢查失敗即中止）。請確認 logs/holdings.json 是實盤最新。")
        raise SystemExit(2)
