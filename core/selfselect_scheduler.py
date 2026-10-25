"""core/selfselect_scheduler.py — 自選股腿的「每月自動選股」排程與執行（V4.35）

## 目標（使用者 2026-09-23 裁定）

> 「每個月第一個交易日選股、第二個交易日執行。如果對選股有意見，可以於第二個交易日前修改 `.env`。
>   隨時使用者也可以手動執行 `VM_pick` 及 `VM_sync_env` 來手動更新 `.env`，於第二個交易日執行。」

時程：

| 時間 | 誰做 | 做什麼 |
|---|---|---|
| **D1**＝每月第 1 個交易日 **13:36 起** | 程式（容器內，本模組） | 跑選股 → 改 VM 的 `.env`（先備份）→ TG 通知 |
| D1 晚上～**D2 13:25 前** | **人**（可選） | 對選股有意見 ⇒ 改 `.env` 覆寫（本機 `VM_pick`→`VM_sync_env`，或直接改 VM 的 `.env`） |
| **D2**＝每月第 2 個交易日 **13:25–13:30** | 程式（既有 `SELFSELECT_EXEC_MODE=immediate`） | 自動買進新名單 |
| D2 **08:05–08:39** | 程式（本模組**補跑**） | D1 沒跑到（容器關機／逾時／失敗）時補做，跑完強制觸發 08:40 熱重載 |

## 設計原則

選股**全部在容器內由程式自己完成**（跑選股 → 自己改 `.env` → 自己發 TG），不需要人工介入：

- 觸發點寫在主迴圈（`SELFSELECT_AUTO=1` 才啟用），D1 收盤後 13:36 起執行。
- 用**已驗證過的同一支程式**做選股與 `.env` 變更：`scripts/monthly_selfselect_run.py`（含步驟 0 補資料、
  基準日把關、`SafetyError`「絕不刪除已持倉」、`.env` 自動備份）——容器內跑它時持股就是實盤持股，
  所以不需要 `--sync-holdings-from-vm`（傳 `--no-sync`）。
- 不在本模組重新實作交易邏輯：D2 的買進仍由既有的 `immediate` 模式負責。

## 為什麼補跑是 D2 早上、而不是 D2 盤後

`.env` 的生效點是**每天 08:40 熱重載**。D1 13:36 寫入 → D2 08:40 生效 → D2 13:25 買進 ✔
補跑若在 D2 08:40 之後才寫入，就得等 D3 才生效 ⇒ 所以補跑時窗訂在 **08:05–08:39**（跑得完就自動生效），
並且跑完把 `_hot_reload_date` 清掉——若拖過 08:40，主程式下一次迴圈會立刻熱重載，不會漏掉。
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

#: 狀態檔（一個月一筆；`status == "applied"` 才算完成）
STATE_FILE = os.getenv("SELFSELECT_STATE_FILE", os.path.join("logs", "selfselect_auto.json"))

#: 觸發時窗（主程式每圈檢查；分鐘數）
D1_FROM, D1_TO = (13, 36), (13, 55)      # D1 收盤後
D2_FROM, D2_TO = (8, 5), (8, 40)         # D2 補跑（08:40 熱重載之前）
MAX_ATTEMPTS = int(os.getenv("SELFSELECT_MAX_ATTEMPTS", "3"))


def _cal():
    from core.trading_calendar import TradingCalendar
    return TradingCalendar()


def nth_trading_day(now, n, calendar=None):
    """當月第 n 個交易日（date）；`n=-1` ＝最後交易日。找不到回 None。"""
    cal = calendar if calendar is not None else _cal()
    try:
        return cal.get_nth_trading_day(now.year, now.month, n)
    except Exception:
        return None


def first_trading_day(now, calendar=None):
    return nth_trading_day(now, 1, calendar)


def second_trading_day(now, calendar=None):
    return nth_trading_day(now, 2, calendar)


def pick_window_reason(now, calendar=None):
    """現在是否落在「該跑自動選股」的時窗 → `"D1"` / `"D2_補跑"` / `None`。"""
    if now.weekday() >= 5:
        return None
    d1, d2 = first_trading_day(now, calendar), second_trading_day(now, calendar)
    hm = (now.hour, now.minute)
    if d1 is not None and now.date() == d1 and D1_FROM <= hm <= D1_TO:
        return "D1"
    if d2 is not None and now.date() == d2 and D2_FROM <= hm < D2_TO:
        return "D2_補跑"
    return None


def month_key(now):
    return now.strftime("%Y-%m")


def load_state(path=None):
    p = Path(path or STATE_FILE)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state, path=None):
    p = Path(path or STATE_FILE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def should_pick(now=None, state=None, calendar=None):
    """該不該現在跑自動選股 → `None` 或 `{"month","day","label"}`。

    條件：① 在時窗內（D1 收盤後 或 D2 早上補跑）② 本月還沒成功（`status == "applied"`）
    ③ 今天失敗次數還沒超過 `SELFSELECT_MAX_ATTEMPTS`。
    """
    now = now or datetime.now()
    state = state if state is not None else load_state()
    reason = pick_window_reason(now, calendar)
    if not reason:
        return None
    mk = month_key(now)
    if state.get("month") == mk and state.get("status") == "applied":
        return None
    if state.get("month") == mk and now.strftime("%Y-%m-%d") == state.get("last_attempt_date"):
        if int(state.get("attempts", 0)) >= MAX_ATTEMPTS:
            return None
    return {"month": mk, "day": reason,
            "label": "自動選股（每月第 1 個交易日）" if reason == "D1" else "自動選股（D2 早上補跑）"}


def picker_command(top_n=None, risk=None, env_path=".env", extra_args=()):
    """要跑的指令（＝本機那條 SOP 一條指令；容器內不需要 `--sync-holdings-from-vm`）。"""
    cmd = [sys.executable, os.path.join("scripts", "monthly_selfselect_run.py"),
           "--risk", risk or os.getenv("SELFSELECT_RISK", "normal"),
           "--top-n", str(top_n or os.getenv("SELFSELECT_TOP_N", "5")),
           "--env", env_path,
           "--no-sync",          # 容器內持股就是實盤持股，不必去 VM 抓
           "--apply"]            # 真的寫 .env（腳本自己會先備份）
    cmd += list(extra_args)
    return cmd


def parse_pick_output(stdout: str):
    """從 `monthly_selfselect_run.py` 的輸出抓重點 → `{"summary","picks","stale","refused"}`。"""
    out = {"summary": "", "picks": [], "stale": False, "refused": False}
    for line in (stdout or "").splitlines():
        s = line.strip()
        if s.startswith("本月選出："):
            out["picks"] = [x.strip() for x in s.split("：", 1)[1].replace("（無）", "").split(",") if x.strip()]
        elif "新增 " in s and "保留已持倉" in s:
            out["summary"] = s
        # 這三項各自獨立判斷：拒絕寫入的那一行同時含「落後預期」字樣，用 elif 會漏掉
        if "落後預期的" in s:
            out["stale"] = True
        if "拒絕寫入 .env" in s:
            out["refused"] = True
        if s.startswith("✅ 已寫入"):
            out["wrote"] = True
    return out


def run_pick(root=None, runner=None, timeout=900, env_path=".env", extra_args=(), env=None):
    """執行選股＋`.env` 變更 → `{"ok","returncode","summary","picks","stdout_tail"}`。

    逾時或非 0 離開碼 ⇒ `ok=False`（**不會**改 `.env`：腳本本身在寫入前就中止）。
    """
    runner = runner or subprocess.run
    cmd = picker_command(env_path=env_path, extra_args=extra_args)
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=timeout, cwd=root or None,
                   env=env if env is not None else None)
    except Exception as e:
        return {"ok": False, "returncode": None, "summary": "", "picks": [],
                "stdout_tail": f"{type(e).__name__}: {e}"}
    rc = getattr(r, "returncode", None)
    stdout = getattr(r, "stdout", "") or ""
    stderr = getattr(r, "stderr", "") or ""
    info = parse_pick_output(stdout)
    tail = "\n".join([l for l in stdout.strip().splitlines() if l.strip()][-6:])
    if rc != 0:
        tail = (stderr.strip().splitlines() or [tail])[-1] if stderr.strip() else tail
    return {"ok": rc == 0, "returncode": rc, "summary": info.get("summary", ""),
            "picks": info.get("picks", []), "stdout_tail": tail,
            "stale": bool(info.get("stale")), "refused": bool(info.get("refused"))}


def _notify_text(res, day, month):
    if res.get("ok"):
        head = f"🤖 *自選股自動選股完成*（{month}／{day}）"
        body = res.get("summary") or "（無變更）"
        tail = (f"\n本月選出：{', '.join(res['picks'])}\n"
                f"已寫入 `.env`（先備份）並會在 **下一個交易日 13:25–13:30** 自動買進。\n"
                f"⚠️ 若對選股有意見：請在**下一個交易日 13:25 前**改 `.env`"
                f"（本機 `VM_pick` → `VM_sync_env`，或直接改 VM 的 `.env`）。")
        return head + "\n" + body + tail
    return (f"⚠️ *自選股自動選股未完成*（{month}／{day}）\n"
            f"離開碼 {res.get('returncode')}｜{res.get('stdout_tail') or '（無輸出）'}\n"
            f"`.env` **未被修改**（腳本在寫入前就中止）。請人工執行 `VM_pick` 檢查。")


def run_if_due(now=None, state_path=None, root=None, runner=None, notify=None,
               calendar=None, timeout=900, env_path=".env"):
    """主程式每圈呼叫：該跑就跑（含狀態記錄與 TG 通知）→ `{"ran":bool, ...}`。"""
    now = now or datetime.now()
    state = load_state(state_path)
    due = should_pick(now, state, calendar)
    if not due:
        return {"ran": False}
    res = run_pick(root=root, runner=runner, timeout=timeout, env_path=env_path)
    mk = due["month"]
    state = {"month": mk, "day": due["day"], "label": due["label"],
             "last_attempt_date": now.strftime("%Y-%m-%d"),
             "attempts": (int(state.get("attempts", 0)) + 1
                          if state.get("month") == mk else 1),
             "picked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
             "status": "applied" if res.get("ok") else "failed",
             "picks": res.get("picks", []), "summary": res.get("summary", ""),
             "returncode": res.get("returncode")}
    save_state(state, state_path)
    if notify:
        try:
            notify(_notify_text(res, due["day"], mk))
        except Exception:
            pass
    return {"ran": True, "ok": bool(res.get("ok")), "day": due["day"], "month": mk,
            "picks": res.get("picks", []), "summary": res.get("summary", ""),
            "tail": res.get("stdout_tail", "")}
