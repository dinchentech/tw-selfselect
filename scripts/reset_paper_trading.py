#!/usr/bin/env python
"""從零重來：清空模擬交易狀態（情境 B：連部位都歸零、重新起算）

## 它做什麼

1. **安全檢查**（任一不過就拒絕，什麼都不改）
   ① 沒有實例在跑（`logs/trader.lock` 的 flock 拿得到）——請先 `docker stop tw_selfselect_bot`
   ② 券商持倉必須為 0（`--assume-flat` 可略過，代表你已自行確認帳戶清空）
2. **備份**：把 `logs/` 內所有狀態檔 ＋ `.env` ＋ `capital.txt` 複製到 `backups/reset_<時間>/`
3. **清空狀態**：刪掉持股／帳本／績效／換股排程／報告狀態等（清單見 `STATE_FILES`）
4. **重設資本**：`.env` 的 `TOTAL_CAPITAL`／`TOTAL_CAPITAL_ORIGINAL`／`INITIAL_CAPITAL` 改成你給的
   起始資本；`capital.txt` 追加一行 `#` 開頭的紀錄（**不會**觸發 keep_wait 自動加碼）
5. `--clear-portfolio`：額外把 `.env` 的 `PC_*` 註解掉（預設**保留** ⇒ 重啟後自動重建同一組 11 檔）

## 用法

```bash
# 1) 先看計畫（預設就是 dry-run，不會動任何檔）
.venv/bin/python scripts/reset_paper_trading.py

# 2) 真的執行（會問起始資本，最後要輸入 yes）
.venv/bin/python scripts/reset_paper_trading.py --execute

# 非互動（給測試或你自己確定時用）
.venv/bin/python scripts/reset_paper_trading.py --execute --capital 1000000 --yes --assume-flat
```

## 重要後果（執行前請讀）

- **重啟後會立刻重建倉位**：`.env` 的 `PC_*` 若保留，主程式的「已選中但未持股 ⇒ 每日嘗試建倉」規則
  會在下一個交易日 09:00 起把同樣的檔買回來（受 `MAX_DAILY_TRADES`／資金上限／大盤年線過濾約束）。
  要完全空白請加 `--clear-portfolio`，再自己跑選股（`scripts/monthly_selfselect_run.py --apply`）產生新名單。
- **績效歷史會歸零**：儀表板與已實現損益從零起算（舊資料在備份裡）。
- **必須在實盤機的 container 內跑**（`logs/` 才是 VM 上那份）；在本機 PC 跑只會清到本機的 `logs/`。
"""
import argparse
import fcntl
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 情境 B 要清的狀態檔（= 「連部位都歸零」）。刻意**不含** *.lock（不是狀態）、
# dashboard.html（會重生）、以及 cache/ 目錄。
STATE_FILES = (
    'holdings.json',
    'stock_allocation.json',
    'performance.csv',
    'equity_peak.json',
    'monthly_budget.json',
    'daily_trades.json',
    'last_trade_times.json',
    'report_state.json',
    'drawdown_hold.json',
    'selfselect_auto.json',
    'auto_resolved.json',
    'selfselect_filled.json',
    'processed_capital.json',
    'voided_trades.jsonl',
    'books_audit.jsonl',
)

ENV_KEYS = ('TOTAL_CAPITAL', 'TOTAL_CAPITAL_ORIGINAL', 'INITIAL_CAPITAL')


# ── 小工具 ─────────────────────────────────────────────────────────────
def fmt_capital(v: float) -> str:
    return f'{float(v):.0f}' if float(v).is_integer() else f'{float(v):g}'


def read_env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        k, v = s.split('=', 1)
        out[k.strip()] = v.split('#', 1)[0].strip()
    return out


def set_env_value(text: str, key: str, value: str, comment: str | None = None) -> str:
    """改 `.env` 的單一 key（保留其他行）；不存在就附加。"""
    lines = text.splitlines()
    hit = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f'{key}='):
            tail = ''
            if '#' in line:
                tail = '  ' + line[line.index('#'):].strip() if comment is None else '  ' + comment
            lines[i] = f'{key}={value}{tail}'
            hit = True
            break
    if not hit:
        lines.append(f'{key}={value}' + (f'  {comment}' if comment else ''))
    return '\n'.join(lines) + '\n'


def lock_is_free(lock_path: Path) -> bool:
    """`logs/trader.lock` 是否拿得到（拿得到＝沒有實例在跑）。"""
    if not lock_path.exists():
        return True   # 沒有鎖檔 ⇒ 不可能有實例（主程式啟動時一定會建立它；dry-run 也不該製造檔案）
    try:
        fh = open(lock_path, 'r')
    except Exception:
        return True
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh, fcntl.LOCK_UN)
        return True
    except OSError:
        return False
    finally:
        fh.close()


def broker_positions_count(inventories_json: str | None = None) -> tuple[int, str]:
    """回傳 (非零部位檔數, 說明)。查不到時回 (-1, 原因) ⇒ 呼叫端要求 `--assume-flat`。"""
    raw = None
    if inventories_json:
        try:
            raw = json.loads(Path(inventories_json).read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                raw = raw.get('inventories', raw)
        except Exception as e:
            return (-1, f'讀不到 --inventories-json：{e}')
    else:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from data.esun_provider import EsunProvider  # noqa: WPS433
            import importlib
            rec = importlib.import_module('scripts.reconcile_broker_books')
            raw, _tx = rec.fetch_from_broker(EsunProvider(), datetime.now().strftime('%Y-%m-%d'))
        except Exception as e:
            return (-1, f'無法查詢券商庫存（{type(e).__name__}: {e}）')

    try:
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        n = 0
        for r in (rows or []):
            if not isinstance(r, dict):
                continue
            qty = r.get('qty') or r.get('quantity') or r.get('Inventory') or r.get('stock_qty') or 0
            try:
                if float(str(qty).replace(',', '')) > 0:
                    n += 1
            except (TypeError, ValueError):
                continue
        return (n, f'券商回傳 {len(rows or [])} 筆庫存，其中 {n} 檔有部位')
    except Exception as e:
        return (-1, f'券商回傳格式無法解析（{e}）')


def plan(logs_dir: Path, env_path: Path, capital: float | None,
         clear_portfolio: bool, inventories_json: str | None,
         assume_flat: bool = False) -> dict:
    """建立計畫（純運算，不動任何檔）。"""
    env = read_env(env_path) if env_path.exists() else {}
    existing = [f for f in STATE_FILES if (logs_dir / f).exists()]
    return {
        'logs_dir': str(logs_dir.resolve()),
        'env_path': str(env_path.resolve()),
        'capital_now': env.get('TOTAL_CAPITAL'),
        'initial_now': env.get('INITIAL_CAPITAL'),
        'capital_new': capital,
        'state_files_existing': existing,
        'state_files_missing': [f for f in STATE_FILES if f not in existing],
        'lock_free': lock_is_free(logs_dir / 'trader.lock'),
        # --assume-flat ⇒ 完全不連券商（避免測試/離線環境登入、限流）
        'broker': (('skip', '已跳過（--assume-flat）') if assume_flat
                   else broker_positions_count(inventories_json)),
        'clear_portfolio': clear_portfolio,
        'portfolio_lines': ([l for l in env_path.read_text(encoding='utf-8').splitlines()
                             if l.strip().startswith('PC_')] if env_path.exists() else []),
    }


def apply(pl: dict, logs_dir: Path, env_path: Path, capital: float,
          capital_file: Path, backup_root: Path, clear_portfolio: bool) -> dict:
    """依計畫執行（呼叫端要先通過安全檢查）。回傳執行結果摘要。"""
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    bdir = backup_root / f'reset_{ts}'
    bdir.mkdir(parents=True, exist_ok=True)

    # ① 備份：logs 全部狀態檔 + .env + capital.txt
    backed = []
    for name in pl['state_files_existing']:
        shutil.copy2(logs_dir / name, bdir / name)
        backed.append(name)
    for extra in (env_path, capital_file):
        if extra.exists():
            shutil.copy2(extra, bdir / extra.name)
            backed.append(str(extra.name))

    # ② 清空狀態檔
    removed = []
    for name in pl['state_files_existing']:
        try:
            (logs_dir / name).unlink()
            removed.append(name)
        except OSError as e:
            print(f'⚠️ 刪除 {name} 失敗：{e}')

    # ③ 重設資本
    text = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    note = f'# 2026-10-15 重置：從零起算（舊值 {pl.get("capital_now")}，備份於 {bdir.name}）'
    for key in ENV_KEYS:
        text = set_env_value(text, key, f'{capital:.0f}' if capital.is_integer() else f'{capital}',
                             comment=note if key != 'INITIAL_CAPITAL' else
                             '# 風險計算用初始資金（2026-10-15 重置為起始資本）')
    if clear_portfolio:
        # ⚠️ 只是「註解」不足以讓程式忘記這些檔：主程式用 `load_dotenv(override=True)`，
        #    它只會**覆蓋**檔案裡有的鍵、**不會移除**檔案裡沒有的鍵；而 PC_* 是容器建立時
        #    由 compose `env_file` 注入 process env 的（2026-10-17 實測：只註解 ⇒ 重啟後仍 11 檔）。
        #    ⇒ 要真正清空名單，必須**重新建立容器**（`docker compose up -d --force-recreate`），
        #      包裝腳本 `reset_paper_trading_vm.py --clear-portfolio` 會自動做。
        out = []
        for line in text.splitlines():
            out.append(f'#RESET# {line}' if line.strip().startswith('PC_') else line)
        text = '\n'.join(out) + '\n'
    env_path.write_text(text, encoding='utf-8')

    # ④ capital.txt：`#` 開頭＝純紀錄、不觸發 keep_wait 自動加碼
    line = (f'# {datetime.now().strftime("%Y/%m/%d")} 重置：起始資本 NT${capital:,.0f}'
            f'（scripts/reset_paper_trading.py；本行僅紀錄，不觸發自動加碼）\n')
    if capital_file.exists():
        with open(capital_file, 'a', encoding='utf-8') as fh:
            fh.write(line)
    else:
        capital_file.write_text('# 資金投入紀錄\n' + line, encoding='utf-8')

    # ⑤ 空狀態檔重建：帳本留 `{}`（不是刪掉）—— 下游工具（選股器、儀表板、對帳）假設它們存在；
    #    刪掉的話 `monthly_rebalance_picker --sync-holdings-from-vm` 之類會把「檔案不存在」當錯誤。
    (logs_dir / 'holdings.json').write_text('{}\n', encoding='utf-8')
    (logs_dir / 'stock_allocation.json').write_text('{}\n', encoding='utf-8')
    (logs_dir / 'processed_capital.json').write_text('[]\n', encoding='utf-8')

    return {'backup_dir': str(bdir), 'backed_up': backed, 'removed': removed,
            'capital': capital, 'portfolio_commented': bool(clear_portfolio and pl['portfolio_lines'])}


def print_plan(pl: dict, execute: bool) -> None:
    mode = 'EXECUTE（會真的動檔）' if execute else 'DRY-RUN（不會動任何檔）'
    print(f'{"="*64}\n🧨 從零重來：模擬交易狀態重置 — {mode}\n{"="*64}')
    print(f'logs 目錄        : {pl["logs_dir"]}')
    print(f'.env             : {pl["env_path"]}')
    print(f'目前 TOTAL_CAPITAL : {pl["capital_now"]}（INITIAL_CAPITAL={pl["initial_now"]}）')
    print(f'起始資本（新）    : {pl["capital_new"] if pl["capital_new"] else "（尚未指定）"}')
    print(f'\n將清空的狀態檔（{len(pl["state_files_existing"])} 個）：')
    for f in pl['state_files_existing']:
        print(f'  · {f}')
    if pl['state_files_missing']:
        print(f'（不存在、略過：{len(pl["state_files_missing"])} 個）')
    print(f'\n投資組合 PC_* 行   : {len(pl["portfolio_lines"])} 行 → '
          f'{"會被註解（--clear-portfolio）" if pl["clear_portfolio"] else "保留（重啟後自動重建同樣的檔）"}')
    print('\n安全檢查：')
    print(f'  ① 無實例在跑（trader.lock）: {"✅" if pl["lock_free"] else "❌ 請先 docker stop tw_selfselect_bot"}')
    n, why = pl['broker']
    if n == 'skip':
        mark, hint = 'ℹ️', ''
    elif n == 0:
        mark, hint = '✅', ''
    elif isinstance(n, int) and n > 0:
        mark, hint = '❌', ''
    else:   # n < 0：查不到券商庫存
        mark, hint = '⚠️', '（需 --assume-flat）'
    print(f'  ② 券商持倉為 0            : {mark} {why}{hint}')


def main(argv=None, input_fn=input) -> int:
    ap = argparse.ArgumentParser(description='從零重來：清空模擬交易狀態（情境 B）')
    ap.add_argument('--execute', action='store_true', help='真的執行（預設只印計畫）')
    ap.add_argument('--capital', type=float, default=None, help='起始資本（省略則互動詢問）')
    ap.add_argument('--yes', action='store_true', help='跳過最後的 yes 確認')
    ap.add_argument('--assume-flat', action='store_true', help='略過券商持倉檢查（你已確認帳戶清空）')
    ap.add_argument('--clear-portfolio', action='store_true', help='額外把 .env 的 PC_* 註解掉')
    ap.add_argument('--inventories-json', default=None, help='改讀券商庫存 JSON（測試/無 SDK 環境）')
    ap.add_argument('--logs-dir', default='logs')
    ap.add_argument('--env-file', default='.env')
    ap.add_argument('--capital-file', default='capital.txt')
    ap.add_argument('--backup-root', default='backups')
    args = ap.parse_args(argv)

    logs_dir = Path(args.logs_dir)
    env_path = Path(args.env_file)
    capital_file = Path(args.capital_file)
    backup_root = Path(args.backup_root)

    # 起始資本：先問（dry-run 也要知道）
    capital = args.capital
    if capital is None:
        cur = read_env(env_path).get('TOTAL_CAPITAL', '?') if env_path.exists() else '?'
        raw = input_fn(f'請輸入起始資本（目前 TOTAL_CAPITAL={cur}）： ').strip().replace(',', '')
        try:
            capital = float(raw)
        except ValueError:
            print(f'❌ 起始資本必須是數字，收到 {raw!r}')
            return 1
    if capital <= 0:
        print(f'❌ 起始資本必須為正數（收到 {capital}）')
        return 1

    pl = plan(logs_dir, env_path, capital, args.clear_portfolio, args.inventories_json,
              assume_flat=args.assume_flat)
    print_plan(pl, args.execute)

    # 安全檢查（**dry-run 只警告**，讓你能隨時先看計畫；`--execute` 才真的擋）
    blocker = None
    if not pl['lock_free']:
        blocker = ('偵測到實盤實例仍在執行（logs/trader.lock 被鎖住）'
                   '\n   請先停容器：docker stop tw_selfselect_bot')
    else:
        n, why = pl['broker']
        if n != 0 and not args.assume_flat:
            blocker = (f'券商仍有部位或查不到庫存（{why}）'
                       '\n   請先清倉，並用 scripts/reconcile_broker_books.py 對帳；'
                       '\n   若你已確認帳戶清空，可加 --assume-flat。')
    if blocker:
        if not args.execute:
            print(f'\n⚠️ 執行前必須先處理：{blocker}')
            print('\n（DRY-RUN 結束；以上只是提醒，未動任何檔）')
            return 0
        print(f'\n❌ 拒絕執行：{blocker}')
        return 2

    if not args.execute:
        print('\n（DRY-RUN 結束；要真的執行請加 --execute）')
        return 0

    if not args.yes:
        ans = input_fn(f'確定要清空 {pl["logs_dir"]} 並把資本重設為 {capital:,.0f}？'
                       f'（會先備份）輸入 yes 繼續： ').strip().lower()
        if ans != 'yes':
            print('已取消。')
            return 0

    res = apply(pl, logs_dir, env_path, capital, capital_file, backup_root, args.clear_portfolio)
    # 機器可讀的完成標記（呼叫端／包裝腳本用它確認「真的做了」，而不是只看 rc=0）
    print(f'RESET_APPLIED=1 capital={fmt_capital(res["capital"])} backup={res["backup_dir"]}')
    print(f'\n✅ 完成：備份 → {res["backup_dir"]}')
    print(f'   · 備份 {len(res["backed_up"])} 個檔、清空 {len(res["removed"])} 個狀態檔')
    print(f'   · 資本重設為 {res["capital"]:,.0f}（TOTAL_CAPITAL／TOTAL_CAPITAL_ORIGINAL／INITIAL_CAPITAL）')
    if args.clear_portfolio:
        print(f'   · PC_* 已註解（本次處理 {res["portfolio_commented"]} 行；'
              f'先前已註解的不計）⇒ 不會自動重建部位，需自行重新選股')
        print('     ⚠️ 只註解**不足以**讓執行中的程式忘記它們（env_file 注入的 os.environ 不會被移除）'
              '\n        ⇒ 必須**重新建立容器**（docker compose up -d --force-recreate）才會生效；'
              '\n        `reset_paper_trading_vm.py --clear-portfolio` 會自動 recreate。')
    else:
        print('   · PC_* 保留 ⇒ 下一個交易日 09:00 起會依原分配重建同樣的檔（受 MAX_DAILY_TRADES 等限制）')
    print('\n後續步驟：')
    print('  1) docker start tw_selfselect_bot → 啟動報告應顯示 0 持倉')
    print('  2) 用 scripts/reconcile_broker_books.py 確認券商與程式一致（都 0）')
    print('  3) 儀表板：下次 13:45 產生後才是空的；需要立即更新就手動跑 Deploy Dashboard')
    print(f'  （要回頭看舊資料：{res["backup_dir"]}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
