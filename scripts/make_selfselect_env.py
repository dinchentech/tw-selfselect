#!/usr/bin/env python3
"""從 tw-autotrader 的 `.env` 產生 tw-selfselect 的 `.env`（一次性遷移用）。

## 為什麼需要它

tw-autotrader 的 `.env` 有 `ROTATE_*`／`INST_MOM_*`／`MODELC_*` 這些舊腿設定，
還有 8 條 `PC_`（3 檔 keep_wait＋5 檔 auto 的混合）。
tw-selfselect 只認 `.env.example.txt` 那套（`SELFSELECT_*`），直接複製會帶著一堆
無效鍵與錯誤名單。**把 secrets 留在 VM 上轉換**，本機不需要也不應該持有這些值。

## 行為

1. 白名單＝`.env.example.txt` 的鍵 ＋ 程式**實際會讀**但範本沒列的鍵（`LIVE_EXTRA`：
   `FEE_RATE`／`MIN_FEE`／`SELL_TAX_RATE` 等，帶錯會讓損益全部偏掉）。
   輸出順序照範本。
2. 來源 `.env` 有該鍵 ⇒ **整行原樣**帶過去（保留你的註解、secrets、內嵌 `#`）。
3. `PC_*` 預設**全部不帶**（重置模式）；`--keep-portfolio` 才原樣帶。
4. 舊專案的 `MODELC_EXEC_MODE` ⇒ 映射成 `SELFSELECT_EXEC_MODE`（若來源沒有後者）。
5. 兩個「範本有預設值但**不能照抄**」的鍵特別處理：
   - `ESUN_ACCOUNT`／`ESUN_API_KEY`／`ESUN_API_SECRET`／`ESUN_CERT_PATH`／`ESUN_CONFIG_INI`
     一律**註解掉**（留空才會去讀 `esun_sdk/config.simulation.ini`，與舊 bot 同口徑）；
   - `KEYRING_CRYPTFILE_PASSWORD` 沒帶到就**隨機產生**（tw-selfselect 不提供寫死預設）。
6. 缺的 selfselect 專屬鍵補預設（`SELFSELECT_LEG_PCT` 等，見 `EXTRA_DEFAULTS`）。
7. **永不印出值**：只印鍵名統計。

## 用法（在 VM 上跑；`deploy_source.sh` 第一次部署時會自動呼叫）

```bash
python3 scripts/make_selfselect_env.py \
    --example ~/tw-selfselect/.env.example.txt \
    --source  ~/tw-autotrader/.env \
    --dest    ~/tw-selfselect/.env            # 預設 dry-run，不寫檔
python3 scripts/make_selfselect_env.py ... --write   # 真的寫（0600 權限）

# 想連同舊 PC_ 名單一起帶（不建議；那是母專案時期的舊名單）
python3 scripts/make_selfselect_env.py ... --keep-portfolio --write
```
"""
import argparse
import os
import re
import secrets
import sys
from pathlib import Path

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

# 範本沒列、但 tw-selfselect 需要（缺就補）的鍵與預設值
EXTRA_DEFAULTS = (
    ("SELFSELECT_LEG_PCT", "100"),
    ("SELFSELECT_EXEC_MODE", "immediate"),
    ("SELFSELECT_MAX_ATTEMPTS", "3"),
    ("SELFSELECT_STATE_FILE", "logs/selfselect_auto.json"),
    ("MONTHLY_PICK_FILE", "logs/monthly_pick.json"),
    ("DOTENV_PATH", ".env"),
    ("SYNC_VM_HOME", "~/tw-selfselect"),
)

# 程式實際會讀、但 `.env.example.txt` 沒列的鍵（不帶 ⇒ 用程式預設，帳務口徑會跟舊帳不同）
LIVE_EXTRA = (
    ("FEE_RATE", "0.001425"),
    ("MIN_FEE", "20"),
    ("SELL_TAX_RATE", "0.003"),
    ("CAPITAL_CONTROL_LINE", "30"),
    ("INITIAL_CAPITAL", None),      # 沒帶 ⇒ 沿用 TOTAL_CAPITAL
    ("DCA_AMOUNT", "0"),
    ("PROFIT_ROLL_MONTHS", "5"),
    ("PROFIT_ROLL_PERCENTAGE", "100"),
)

# 範本有預設值、但**照抄會弄壞登入**的鍵：沒帶到就整行註解掉
ESUN_OPTIONAL = ("ESUN_ACCOUNT", "ESUN_API_KEY", "ESUN_API_SECRET",
                 "ESUN_CERT_PATH", "ESUN_CONFIG_INI")

# 舊專案專用、要統計但不放進新 .env 的鍵前綴（白名單機制自然會排除，這裡只為了回報）
LEGACY_PREFIXES = ("ROTATE_", "ROTATION_", "INST_MOM_", "INST_CONFIRM", "MODELC_")

REQUIRED_KEYS = ("TOTAL_CAPITAL", "FINMIND_API_TOKEN", "BROKER")


def parse_env(path: Path):
    """回傳 (key→整行原文)。重複鍵以最後一筆為準（dotenv 語義）。"""
    pairs = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        sys.exit(f"❌ 找不到來源檔：{path}")
    for line in lines:
        m = KEY_RE.match(line.lstrip())
        if not m:
            continue
        pairs[m.group(1)] = line
    return pairs


def value_of(line: str) -> str:
    """取 KEY= 之後、去掉行內註解的值（只給轉換用，不輸出）。"""
    raw = line.split("=", 1)[1] if "=" in line else ""
    return raw.split("#", 1)[0].strip()


def default_value_line(line: str) -> str:
    """把範本預設行的**行內註解**搬到上一行，值保持乾淨。

    為什麼：docker compose 的 `env_file` 對「值為空＋行內註解」的寫法
    （`LINE_NOTIFY_TOKEN=   # 說明`）會把整段註解當成值 ⇒ 實測容器內變成
    `# LINE Notify（…）`，bot 每次啟動都去連 LINE（VM 無 DNS ⇒ 噴錯＋多等 5 秒）。
    """
    s = line.strip()
    if '=' not in s:
        return line
    key, val = s.split('=', 1)
    if '#' in val:
        value, comment = val.split('#', 1)
        value, comment = value.strip(), comment.strip()
    else:
        value, comment = val.strip(), ''
    out = f'{key}={value}'
    return f'# {comment}\n{out}' if comment else out


def template_keys(example: Path):
    """依範本順序回傳 [(key, 範本原文行)]；只取「KEY=」行。"""
    out, seen = [], set()
    for line in example.read_text(encoding="utf-8").splitlines():
        m = KEY_RE.match(line.lstrip())
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), line))
    return out


def build(source_pairs, example_lines, keep_portfolio):
    out = {}          # key -> 整行（可能是註解行）
    emitted, order = set(), []
    copied, defaulted, commented, extra = [], [], [], []

    def put(key, line, bucket, emitted_now=True):
        out[key] = line
        order.append(key)
        bucket.append(key)
        if emitted_now:
            emitted.add(key)

    # 舊專案的執行模式 → 新專案的 SELFSELECT_EXEC_MODE
    if "SELFSELECT_EXEC_MODE" not in source_pairs and "MODELC_EXEC_MODE" in source_pairs:
        mode = value_of(source_pairs["MODELC_EXEC_MODE"]) or "immediate"
        put("SELFSELECT_EXEC_MODE",
            f"SELFSELECT_EXEC_MODE={mode}   # 由舊專案 MODELC_EXEC_MODE 轉換",
            copied)

    # 1) 範本順序（PC_ 跳過；ESUN 選項鍵、KEYRING 特別處理）
    for key, tpl_line in example_lines:
        if key.startswith("PC_") or key in emitted:
            continue
        if key in source_pairs:
            # 來源行原樣帶過去；唯一例外：值為空又有行內註解（env_file 會把註解吃成值）
            src_line = source_pairs[key]
            put(key, default_value_line(src_line) if (not value_of(src_line) and '#' in src_line) else src_line, copied)
        elif key == "KEYRING_CRYPTFILE_PASSWORD":
            put(key,
                "# 自動產生（金鑰庫解鎖密碼，只在容器內用；換掉它容器重啟後重設即可）\n"
                "KEYRING_CRYPTFILE_PASSWORD=" + secrets.token_hex(16),
                defaulted)
        elif key in ESUN_OPTIONAL:
            put(key,
                f"# {tpl_line.strip()}   # 注釋掉＝沿用 esun_sdk/config.simulation.ini（與舊 bot 同口徑）",
                commented)
        else:
            put(key, default_value_line(tpl_line), defaulted)

    # 2) 程式實際會讀、範本沒列的鍵
    for key, default in LIVE_EXTRA:
        if key in emitted:
            continue
        if key in source_pairs:
            put(key, source_pairs[key], copied)
        elif key == "INITIAL_CAPITAL":
            base = value_of(source_pairs.get("TOTAL_CAPITAL", "=500000"))
            put(key, f"INITIAL_CAPITAL={base}   # 舊 .env 沒有 ⇒ 沿用 TOTAL_CAPITAL", defaulted)
        else:
            put(key, f"# {key}={default}   # 程式預設值（舊 .env 沒設；要改就取消註解）", commented)

    # 3) selfselect 專屬鍵
    for key, default in EXTRA_DEFAULTS:
        if key not in emitted:
            put(key, f"{key}={default}", extra)

    # 4) TOTAL_CAPITAL_ORIGINAL 缺了就沿用 TOTAL_CAPITAL
    if "TOTAL_CAPITAL_ORIGINAL" not in emitted:
        base = value_of(source_pairs.get("TOTAL_CAPITAL", "=500000"))
        put("TOTAL_CAPITAL_ORIGINAL", f"TOTAL_CAPITAL_ORIGINAL={base}", extra)

    body = [out[k] for k in order]

    portfolio = ["", "# ── 9. 個股名單（唯一真相＝PC_<代號>）──────────────────────────────────"]
    if keep_portfolio:
        pc_lines = [source_pairs[k] for k in source_pairs if k.startswith("PC_")]
        portfolio.append(f"# 由舊專案原樣帶入 {len(pc_lines)} 檔（--keep-portfolio）")
        portfolio += pc_lines
    else:
        portfolio += [
            "# 重置模式：名單刻意清空。D1 自動選股（SELFSELECT_AUTO=1）會自動寫入；",
            "# 想立刻產生名單就手動跑：",
            "#   .venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5 --apply",
            "# 手動指定（範例）：",
            '# PC_2330={"strategy":"auto","alloc":20}',
            '# PC_2317={"strategy":"auto","alloc":20}',
        ]

    header = [
        "# ══════════════════════════════════════════════════════════════════════════",
        "# tw-selfselect 的 .env（由 scripts/make_selfselect_env.py 從 tw-autotrader 轉換）",
        "# · 白名單＝.env.example.txt ＋ 程式實際會讀的鍵；舊腿設定（ROTATE_*／INST_MOM_*）一律不帶",
        f"# · PC_ 名單：{'原樣保留' if keep_portfolio else '已清空（重置模式）'}",
        "# · 權限 0600：本檔含 secrets",
        "# ══════════════════════════════════════════════════════════════════════════",
    ]
    return header + body + portfolio, copied, defaulted, commented, extra


def main(argv=None):
    ap = argparse.ArgumentParser(description="tw-autotrader .env → tw-selfselect .env（一次性遷移）")
    ap.add_argument("--example", required=True, type=Path, help="tw-selfselect/.env.example.txt")
    ap.add_argument("--source", required=True, type=Path, help="tw-autotrader/.env")
    ap.add_argument("--dest", required=True, type=Path, help="輸出檔（例如 ~/tw-selfselect/.env）")
    ap.add_argument("--keep-portfolio", action="store_true",
                    help="保留來源的 PC_ 名單（預設清空＝重置模式）")
    ap.add_argument("--write", action="store_true", help="真的寫檔（預設 dry-run）")
    args = ap.parse_args(argv)

    if not args.example.exists():
        sys.exit(f"❌ 找不到範本：{args.example}")
    source_pairs = parse_env(args.source)
    example_lines = template_keys(args.example)
    content, copied, defaulted, commented, extra = build(
        source_pairs, example_lines, args.keep_portfolio)

    missing = [k for k in REQUIRED_KEYS if k not in source_pairs]
    legacy = [k for k in source_pairs if k.startswith(LEGACY_PREFIXES)]
    pc_n = len([k for k in source_pairs if k.startswith("PC_")])
    print(f"來源鍵數：{len(source_pairs)}｜帶進新檔：{len(copied)}｜範本預設：{len(defaulted)}"
          f"｜註解掉：{len(commented)}｜補 selfselect 鍵：{len(set(extra))}")
    print(f"略過的舊腿鍵：{len(legacy)}"
          f"（例：{', '.join(sorted(legacy)[:6])}{'…' if len(legacy) > 6 else ''}）")
    print(f"PC_ 名單：{('原樣帶入 ' + str(pc_n) + ' 檔') if args.keep_portfolio else '清空（重置模式）'}")
    if missing:
        print(f"⚠️  來源 .env 缺必填鍵：{', '.join(missing)}（產生檔會用預設值或留空）")
    print("必填鍵：" + "、".join(f"{k}{'✓' if k in source_pairs else '✗'}" for k in REQUIRED_KEYS))

    if not args.write:
        print("（dry-run：沒有寫任何檔案；加 --write 才會寫）")
        return 0

    args.dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(args.dest), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(content) + "\n")
    os.chmod(args.dest, 0o600)
    print(f"✅ 已寫入 {args.dest}（{len(content)} 行，權限 0600）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
