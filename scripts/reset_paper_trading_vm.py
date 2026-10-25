#!/usr/bin/env python
"""從零重來（情境 B）—— **在本機執行**，用 gcloud SSH 進 VM 跑一次性容器

為什麼要這支：`scripts/reset_paper_trading.py` 必須對「VM 上那份 `logs/`」動手，但你不必
SSH 進去手打指令 —— 這支在本機問起始資本、幫你上傳腳本、停 bot、用**一次性容器**
（掛 VM 上真實的 `logs/`／`.env`／`backups/`／`capital.txt`）執行，跑完再把 bot 起回來。

## 用法（本機）

```bash
# ① 先看計畫（預設 dry-run；不會動任何檔、也不會停容器）
.venv/bin/python scripts/reset_paper_trading_vm.py

# ② 真的執行（會問起始資本 → 確認 → 停 bot → 重置 → 起 bot）
.venv/bin/python scripts/reset_paper_trading_vm.py --execute

# 常用選項
--capital 1000000       # 起始資本（省略則互動詢問）
--clear-portfolio       # 額外把 VM .env 的 PC_* 註解掉（否則重啟後會重建同樣的檔）
--assume-flat           # 略過券商持倉檢查（你已確認帳戶清空）
--start-vm              # VM 沒開就自動開（預設只提示）
--no-stop / --no-restart # 不要自動停／起 bot 容器（--no-stop 會讓重置被鎖擋下）
--print-command         # 只印出「會在 VM 上執行的指令」就結束（不連線）
```

## 兩個「本機↔VM 同步」（很重要，本腳本自動處理）

1. **`.env`**：重置在 VM 上改了 `TOTAL_CAPITAL`／`TOTAL_CAPITAL_ORIGINAL`／`INITIAL_CAPITAL`，
   本機若也有一份 `.env` 會一起同步；本專案的 `.env` 通常只存在 VM 上（第一次部署時
   `deploy_source.sh` 產生），本機沒有就只提示、不動。
2. **`capital.txt`**：`#` 開頭的紀錄行會同時追加到本機與 VM 的檔案（本機那份才會進下一次的映像）。

⚠️ 前置：`gcloud auth login` 有效、VM 可 SSH（本腳本已帶 `-F /dev/null` 繞過 WSL 的 ssh_config 權限問題）、
VM 上已有 `tw-selfselect:latest` image（先跑過部署）。
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.reset_paper_trading import ENV_KEYS, read_env, set_env_value  # noqa: E402

DEFAULT_VM = 'tw-autotrader'
DEFAULT_ZONE = 'asia-east1-b'
DEFAULT_REMOTE_DIR = '$HOME/tw-selfselect'   # 遠端由 bash 展開（不得寫死家目錄：test_no_hardcoded_home_path）
DEFAULT_IMAGE = 'tw-selfselect:latest'
DEFAULT_CONTAINER = 'tw_selfselect_bot'
REMOTE_SCRIPT = '/tmp/reset_paper_trading.py'


def _gcloud(args, run=subprocess.run, timeout=120, input_text=None):
    """跑 gcloud（SSH 一律帶 -F /dev/null：WSL 的 ssh_config 權限問題 ⇒ 不加會直接失敗）。"""
    kw = {'capture_output': True, 'text': True, 'timeout': timeout}
    if input_text is not None:
        kw['input'] = input_text
    return run(['gcloud'] + args, **kw)


def ssh_cmd(vm, zone, command):
    return ['compute', 'ssh', vm, f'--zone={zone}',
            '--ssh-flag=-F', '--ssh-flag=/dev/null', '--command=' + command]


def upload_cmd(vm, zone):
    """上傳方式＝**ssh 的 stdin**（`cat > 檔案`）。

    為什麼不用 `gcloud compute scp`：scp 不吃 `--ssh-flag`（只吃 `--scp-flag`），
    實測會直接 `unrecognized arguments: --ssh-flag=-F`；
    而 ssh 這條路本來就必須帶 `-F /dev/null`（WSL 的 ssh_config 權限問題）⇒ 統一走 ssh 最省事。
    """
    return ssh_cmd(vm, zone, f'cat > {REMOTE_SCRIPT} && chmod 600 {REMOTE_SCRIPT}')


def fmt_num(v: float) -> str:
    """1000000.0 → '1000000'（不要用 `:g`，否則會變成 1e+06 寫進 .env 與指令）。"""
    return f'{v:.0f}' if float(v).is_integer() else f'{v:g}'


def inner_args(capital, assume_flat, clear_portfolio, execute) -> str:
    parts = ['--capital', fmt_num(capital)]
    if execute:
        # ⚠️ 只加 `--yes` 會讓 VM 端跑成 DRY-RUN（什麼都沒清）⇒ 必須同時帶 `--execute`
        parts += ['--execute', '--yes']   # 真要執行；VM 端不再互動（本機已確認）
    if assume_flat:
        parts.append('--assume-flat')
    if clear_portfolio:
        parts.append('--clear-portfolio')
    return ' '.join(parts)


def build_remote_script(capital, assume_flat, clear_portfolio, execute,
                        remote_dir=DEFAULT_REMOTE_DIR, image=DEFAULT_IMAGE,
                        stop_bot=True, restart_bot=True,
                        container=DEFAULT_CONTAINER) -> str:
    """組出「在 VM 上執行的 bash」（純字串，好測試）。"""
    mounts = (f'  -v {remote_dir}/logs:/app/logs '
              f'-v {remote_dir}/.env:/app/.env '
              f'-v {remote_dir}/backups:/app/backups '
              f'-v {remote_dir}/capital.txt:/app/capital.txt '
              f'-v {REMOTE_SCRIPT}:/app/scripts/reset_paper_trading.py:ro ')
    run_line = (f'sudo docker run --rm {mounts}{image} '
                f'python scripts/reset_paper_trading.py {inner_args(capital, assume_flat, clear_portfolio, execute)}')
    lines = ['set -uo pipefail', f'cd "{remote_dir}" || exit 1',
             '[ -f capital.txt ] || touch capital.txt']
    if execute and stop_bot:
        lines += ['echo "── 停止 bot 容器（重置期間不得有實例在跑）"',
                  f'sudo docker stop {container} >/dev/null 2>&1 || true']
    lines += ['echo "── 執行重置（一次性容器；掛 VM 上的實檔）"', run_line, 'RC=$?']
    if execute and restart_bot:
        if clear_portfolio:
            # ⚠️ 「清空 PC_*」＝移除環境變數 ⇒ 只 restart 沒用（env_file 注入的值仍在 os.environ）
            #    必須重建容器讓 env_file 重新讀 .env（實測踩到）。
            lines += ['echo "── 重建 bot 容器（PC_* 已註解 ⇒ 必須 recreate 才會重新讀 .env）"',
                      f'cd "{remote_dir}" && sudo docker compose up -d --force-recreate >/dev/null 2>&1 '
                      f'|| sudo docker start {container} >/dev/null 2>&1 || true']
        else:
            lines += ['echo "── 重新啟動 bot 容器"',
                      f'sudo docker start {container} >/dev/null 2>&1 || true']
    lines.append('exit $RC')
    return '\n'.join(lines)


def sync_local(capital: float, env_path: Path, capital_file: Path,
               clear_portfolio: bool = False) -> dict:
    """把 `.env` 三個資本鍵（以及 PC_* 註解）與 `capital.txt` 同步到本機。

    為什麼要同步 PC_*：`--clear-portfolio` 是在 **VM** 的 `.env` 上把 PC_* 註解掉，
    本機若留著舊名單，下次部署（或人工同步）會把它復活。
    """
    out = {'env_updated': False, 'capital_line_added': False, 'portfolio_commented': 0}
    if env_path.exists():
        text = env_path.read_text(encoding='utf-8')
        note = '# 重置：從零起算（由 reset_paper_trading_vm.py 同步）'
        for key in ENV_KEYS:
            comment = note if key != 'INITIAL_CAPITAL' else '# 風險計算用初始資金（重置為起始資本）'
            text = set_env_value(text, key, fmt_num(capital), comment=comment)
        if clear_portfolio:
            cnt = 0
            out_lines = []
            for line in text.splitlines():
                if line.strip().startswith('PC_'):
                    out_lines.append(f'#RESET# {line}')
                    cnt += 1
                else:
                    out_lines.append(line)
            text = '\n'.join(out_lines) + '\n'
            out['portfolio_commented'] = cnt
        env_path.write_text(text, encoding='utf-8')
        out['env_updated'] = True
    line = (f'# {datetime.now().strftime("%Y/%m/%d")} 重置：起始資本 NT${capital:,.0f}'
            f'（reset_paper_trading_vm.py；本行僅紀錄，不觸發自動加碼）')
    if capital_file.exists():
        if line not in capital_file.read_text(encoding='utf-8'):
            with open(capital_file, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
            out['capital_line_added'] = True
    else:
        capital_file.write_text('# 資金投入紀錄\n' + line + '\n', encoding='utf-8')
        out['capital_line_added'] = True
    return out


def main(argv=None, input_fn=input, run=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description='從零重來（情境 B）：本機執行、SSH 進 VM 跑')
    ap.add_argument('--execute', action='store_true', help='真的執行（預設 dry-run）')
    ap.add_argument('--capital', type=float, default=None, help='起始資本（省略則詢問）')
    ap.add_argument('--yes', action='store_true', help='跳過本機確認')
    ap.add_argument('--assume-flat', action='store_true', help='略過券商持倉檢查')
    ap.add_argument('--clear-portfolio', action='store_true', help='額外把 PC_* 註解掉')
    ap.add_argument('--start-vm', action='store_true', help='VM 沒開就自動開')
    ap.add_argument('--no-stop', action='store_true', help='不要自動停 bot（重置會被鎖擋下）')
    ap.add_argument('--no-restart', action='store_true', help='重置後不要自動起 bot')
    ap.add_argument('--print-command', action='store_true', help='只印出遠端指令（不連線）')
    ap.add_argument('--vm', default=DEFAULT_VM)
    ap.add_argument('--zone', default=DEFAULT_ZONE)
    ap.add_argument('--remote-dir', default=DEFAULT_REMOTE_DIR)
    ap.add_argument('--image', default=DEFAULT_IMAGE)
    ap.add_argument('--container', default=DEFAULT_CONTAINER)
    ap.add_argument('--env-file', default='.env', help='本機 .env（若有，用來同步資本三鍵）')
    ap.add_argument('--capital-file', default='capital.txt', help='本機 capital.txt')
    args = ap.parse_args(argv)

    capital = args.capital
    if capital is None:
        cur = read_env(Path(args.env_file)).get('TOTAL_CAPITAL', '?') if Path(args.env_file).exists() else '?'
        raw = input_fn(f'請輸入起始資本（本機 .env 目前 TOTAL_CAPITAL={cur}）： ').strip().replace(',', '')
        try:
            capital = float(raw)
        except ValueError:
            print(f'❌ 起始資本必須是數字，收到 {raw!r}')
            return 1
    if capital <= 0:
        print(f'❌ 起始資本必須為正數（收到 {capital}）')
        return 1

    remote = build_remote_script(capital, args.assume_flat, args.clear_portfolio, args.execute,
                                 remote_dir=args.remote_dir, image=args.image,
                                 stop_bot=not args.no_stop, restart_bot=not args.no_restart,
                                 container=args.container)
    mode = 'EXECUTE' if args.execute else 'DRY-RUN'
    print(f'{"="*66}\n🧨 從零重來（本機 → SSH → VM 一次性容器）— {mode}｜起始資本 {capital:,.0f}\n{"="*66}')
    print('將在 VM 上執行的指令：\n' + '-'*66)
    print(remote)
    print('-'*66)

    if args.print_command:
        return 0

    # VM 狀態
    r = _gcloud(['compute', 'instances', 'describe', args.vm, f'--zone={args.zone}',
                 '--format=value(status)'], run=run)
    status = (r.stdout or '').strip().splitlines()[-1] if r.returncode == 0 and r.stdout else ''
    if status != 'RUNNING':
        if args.start_vm:
            print(f'⚙️ VM 目前是 {status or "unknown"} ⇒ 自動開機…')
            _gcloud(['compute', 'instances', 'start', args.vm, f'--zone={args.zone}'], run=run)
            for _ in range(30):
                rr = _gcloud(['compute', 'instances', 'describe', args.vm, f'--zone={args.zone}',
                              '--format=value(status)'], run=run)
                if (rr.stdout or '').strip().endswith('RUNNING'):
                    break
                import time
                time.sleep(5)
        else:
            print(f'❌ VM 目前是 {status or "unknown"}（需要 RUNNING）。'
                  f'\n   先開機：gcloud compute instances start {args.vm} --zone={args.zone}'
                  f'\n   或加 --start-vm 讓本腳本自動開。')
            return 1

    # 需要時才上傳腳本（dry-run 也要上傳：遠端要跑同一支程式）
    if args.execute and not args.yes:
        if input_fn(f'確定要在 VM 上清空 logs/ 並把資本重設為 {capital:,.0f}？輸入 yes 繼續： '
                    ).strip().lower() != 'yes':
            print('已取消。')
            return 0

    script_text = (_ROOT / 'scripts' / 'reset_paper_trading.py').read_text(encoding='utf-8')
    up = _gcloud(upload_cmd(args.vm, args.zone), run=run, input_text=script_text)
    if up.returncode != 0:
        print('❌ 上傳 reset_paper_trading.py 到 VM 失敗：\n' + (up.stderr or up.stdout or '')[-800:])
        print('   常見原因：① `gcloud auth login` 過期；② 本機 `~/.config/gcloud` 不可寫'
              '（可設 `CLOUDSDK_CONFIG=$(mktemp -d)` 並複製憑證）')
        return 1

    print('\n▶ 連線執行中…（會停 bot → 重置 → 起 bot；請勿中途關閉）\n')
    res = _gcloud(ssh_cmd(args.vm, args.zone, remote), run=run, timeout=900)
    print(res.stdout or '')
    if res.stderr:
        print('[stderr] ' + res.stderr[-800:])

    if not args.execute:
        print('（DRY-RUN 結束：VM 上只印計畫、未動任何檔）')
        return 0 if res.returncode == 0 else 1

    if res.returncode != 0:
        print(f'❌ VM 端執行失敗（rc={res.returncode}）—— 未同步本機 .env／capital.txt')
        return 1

    # ② **確認遠端真的執行了重置**（不能只看 rc=0；dry-run 也會回 0）
    if 'RESET_APPLIED=1' not in (res.stdout or ''):
        print('❌ VM 端沒有回報 RESET_APPLIED=1（可能仍是 dry-run 或中途失敗）'
              '—— 未同步本機 .env／capital.txt')
        return 1
    # ③ 再直接驗證 VM 上的 .env 資本已改成新值（雙重確認）
    chk = _gcloud(ssh_cmd(args.vm, args.zone,
                          f'cd "{args.remote_dir}" && grep -E "^{ENV_KEYS[0]}=" .env'),
                  run=run, timeout=120)
    want = f'{ENV_KEYS[0]}={fmt_num(capital)}'
    if want not in (chk.stdout or ''):
        print(f'❌ VM 上 .env 未更新為 {want}（實際：{(chk.stdout or "").strip()[:80]}）'
              '—— 未同步本機')
        return 1

    sync = sync_local(capital, Path(args.env_file), Path(args.capital_file),
                      clear_portfolio=args.clear_portfolio)
    extra = (f'／PC_* 已註解 {sync["portfolio_commented"]} 行'
             if sync['portfolio_commented'] else '')
    print('✅ 完成。本機同步：'
          f'.env {"已更新" if sync["env_updated"] else "（本機沒有 .env，略過）"}{extra}／'
          f'capital.txt {"已追加紀錄" if sync["capital_line_added"] else "（已存在，略過）"}')
    print('   ① 確認啟動報告顯示 0 持倉；② 模擬券商帳戶另外清（reconcile_broker_books.py 對帳）；'
          '\n   ③ 儀表板下次 13:45 產生後才是空的。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
