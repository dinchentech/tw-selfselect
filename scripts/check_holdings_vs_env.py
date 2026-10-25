#!/usr/bin/env python3
"""scripts/check_holdings_vs_env.py — 唯讀檢查：「持股」與「.env 監控名單」是否對得上。

為什麼要有這支（2026-09-22）：`monthly_rebalance_picker.py` 的「已持倉一律保留」規則
曾因**格式 bug 從未生效**（picker 只認 `{"qty":N}`，實盤寫的是 `{sym:int}`），
若照著它輸出的「賣出（汰換）」名單去改 `.env`，**持有中的股票會被從 .env 移除**
⇒ 實盤的「孤兒清倉」（`live_trader_multi.py` 開盤那段）會在下一個交易日**把它直接賣掉**，
等於繞過策略賣訊。修好 bug 之後，仍需一個**唯讀**工具在改 `.env` 前後對帳。

它報三種東西：
1. 🚨 **孤兒持股**：`logs/holdings.json` 有股數，但 `.env` 沒有該檔 ⇒ **下一個交易日開盤會被清倉**。
2. 🗑️ **汰換候選**：`.env` 有、非 `keep_wait`、且 0 股 ⇒ 可以安全移除（不會觸發清倉）。
3. ⚪ **純監控**：在 `.env`、0 股、但也沒被本月選中（需搭配 picker 輸出判讀）。

另附三本帳一致性（`core/books.audit_books`，純比對、不連網）。

⚠️ **必須在實盤機（container）內執行**，本機的 `logs/` 是舊的：
    docker exec tw_selfselect_bot python scripts/check_holdings_vs_env.py

用法：
    docker exec tw_selfselect_bot python scripts/check_holdings_vs_env.py
    .venv/bin/python scripts/check_holdings_vs_env.py --env .env --holdings logs/holdings.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

# ⚠️ `.env` 一律以「檔案」為準（override=True）：容器用 docker-compose env_file 在**建容器時**
#   注入 process env，之後主機改 `.env` 不會更新它 ⇒ 用 docker exec 跑的工具會讀到舊值。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)

# 專案根：**不要寫死作者的家目錄**（container 內是 /app，沒有 /home/frank/...）
# 2026-09-22 修：原本 `sys.path.insert(0, "<專案根目錄>")` ＋ `os.chdir(...)`，
#   在本機能跑、在 container 內直接 ModuleNotFoundError／FileNotFoundError
#   （`docker exec tw_selfselect_bot python scripts/monthly_rebalance_picker.py` 必炸）。
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.isdir(_ROOT):
    os.chdir(_ROOT)


def read_env_portfolio(env_path: Path) -> dict:
    out = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("PC_") and "=" in s:
            sym = s[3:].split("=", 1)[0]
            val = s.split("=", 1)[1]
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            try:
                out[sym] = json.loads(val)
            except Exception:
                out[sym] = {"strategy": "?"}
    return out


def classify(env_cfg: dict, held: dict):
    """回傳 (orphans, replaceable, monitored_flat)。"""
    orphans = sorted(s for s in held if s not in env_cfg)                      # 有股數但不在 .env
    replaceable, monitored_flat = [], []
    for s, cfg in env_cfg.items():
        if cfg.get("strategy") == "keep_wait" or held.get(s, 0) > 0:
            continue
        (replaceable if cfg.get("strategy") != "?" else monitored_flat).append(s)
    return orphans, sorted(replaceable), sorted(monitored_flat)


def main():
    ap = argparse.ArgumentParser(description="唯讀：持股 vs .env 監控名單對帳")
    ap.add_argument("--env", default=os.getenv("DOTENV_PATH", ".env"))
    ap.add_argument("--holdings", default="logs/holdings.json")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    args = ap.parse_args()

    from core.live_state import held_quantities, load_json

    env_path = Path(args.env)
    env_cfg = read_env_portfolio(env_path)
    held = held_quantities(load_json(args.holdings, {}))
    orphans, replaceable, monitored_flat = classify(env_cfg, held)

    book = None
    try:
        from core.books import audit_books
        book = audit_books()
    except Exception as e:                                    # 純附加資訊，失敗不影響主結論
        book = {"ok": None, "error": f"{type(e).__name__}: {e}"}

    # 自我把關（與 picker 用同一支）：本機 logs 若是舊的／空的，結論會誤導
    try:
        from core.live_utils import holdings_context_check
        trust_ok, trust_msg, trust_detail = holdings_context_check(env_path=env_path)
    except Exception as e:
        trust_ok, trust_msg, trust_detail = True, f"(無法檢查: {type(e).__name__})", {}

    result = {
        "holdings_trustworthy": trust_ok,
        "holdings_trust_note": trust_msg,
        "env": str(env_path),
        "holdings_source": args.holdings,
        "held": held,
        "monitored": {s: c.get("strategy") for s, c in sorted(env_cfg.items())},
        "orphans_held_but_not_in_env": orphans,
        "replaceable_flat_monitored": replaceable,
        "unknown_strategy": monitored_flat,
        "books_ok": (book or {}).get("ok"),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print(f"持股 vs .env 對帳（env={env_path}｜holdings={args.holdings}）")
        print("=" * 60)
        if not trust_ok:
            print(f"⚠️⚠️ 這份 logs 不可信：{trust_msg}")
            print("     ⇒ 下面的結論只能當『格式示範』，實盤請在 container 內跑：")
            print("       docker exec tw_selfselect_bot python scripts/check_holdings_vs_env.py")
            print()
        print(f"持倉（qty>0）：{held or '（無）'}")
        print(f".env 監控：{ {s: c.get('strategy') for s, c in sorted(env_cfg.items())} }")
        print()
        if orphans:
            print(f"🚨 孤兒持股 {len(orphans)} 檔：{orphans}")
            print("   ⇒ 這些股『有股數但不在 .env』，實盤會在**下一個交易日開盤**把它們清倉（繞過策略賣訊）！")
            print("   ⇒ 處理：把它們加回 .env（strategy 依原策略，例如 auto），或確認你真的要賣。")
        else:
            print("✅ 沒有孤兒持股（所有持股都在 .env 內）")
        print()
        if replaceable:
            print(f"🗑️  汰換候選 {len(replaceable)} 檔（在 .env、非 keep_wait、0 股）：{replaceable}")
            print("   ⇒ 從 .env 移除安全（0 股不會觸發任何下單）。")
        if monitored_flat:
            print(f"⚪ 策略未定（無法判斷）{len(monitored_flat)} 檔：{monitored_flat}")
        print()
        print(f"三本帳一致性（core.books.audit_books）：{book.get('ok') if isinstance(book, dict) else book}")


if __name__ == "__main__":
    main()
