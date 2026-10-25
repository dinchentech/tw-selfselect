#!/usr/bin/env python3
"""把 `logs/performance.csv` 正規化成單一 schema（7 欄）—— 一次性遷移工具。

**問題**（2026-09-13 查獲）：表頭是 6 欄，但 2026-09-01 10:15（commit `165e994`）
之後的程式寫入 **7 欄**（多一個 `exclude_daily`）⇒ 同一份檔混兩種寬度。
2026-09-17 再加一欄 `cost`（交易成本，見 `core/fees.py`）⇒ 目標寬度為 **8 欄**。
任何**按欄位序號**解析的人都會錯；`csv.DictReader` 讀 7 欄列時，多出的值會落到
key `None`（不是報錯，是靜默錯位）——比直接爆掉更危險。

**做法**（冪等，重複執行無副作用）：
1. 表頭補成 7 欄；
2. 短缺的列**依缺的位置**補對應預設值：`exclude_daily` 補 `0`（沿用舊語意「計入每日交易次數」）、
   `cost` 補**空**（未記錄，不捏造金額 —— 讀取端會用現行費率推定）；
3. **不**改動第 7 欄非 `0/1` 的列（來源不明的資料照原樣留著，只列出來提醒）；
4. 取代前**再確認檔案大小沒變**（避免蓋掉期間新增的成交）→ 變了就中止；
5. 先備份 `<檔名>.bak_schema_<時間戳>`，再原子替換（tmp → fsync → `os.replace`）。

**順帶統一的東西（會逐一報告，不默默改）**：原檔的換行也是混的
（實測 73 列是 `\r\n`＝`csv.writer` 預設、其餘是 `\n`）⇒ 統一成 LF。
所有常見解析器（`csv`、pandas）都吃 LF，欄位數與金額完全不變。

**只用標準庫** —— 所以 VM host 的 `python3` 或容器內都能跑。

用法：
    python3 scripts/migrate_performance_csv_schema.py                 # 預設 dry-run，只報告
    python3 scripts/migrate_performance_csv_schema.py --apply         # 實際遷移（先備份）
    python3 scripts/migrate_performance_csv_schema.py --file <路徑>

離開碼：0 = 已是單一 schema 或遷移成功；1 = 檔案不存在／中止／異常。
"""
import argparse
import csv
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime

DEFAULT_FILE = "logs/performance.csv"
HEADER = ["timestamp", "symbol", "signal", "price", "quantity", "action",
          "exclude_daily", "cost"]
WIDTH = len(HEADER)
# 各欄位的「補值」——依加入順序：
#   6→7：exclude_daily 補 "0"（沿用舊語意：當時確實計入每日交易次數額度）
#   7→8：cost 補 ""（**未記錄**，不捏造；讀取端用現行費率推定，見 core/fees.row_cost）
PAD_DEFAULTS = {6: "0", 7: ""}
# 只對「已知的歷史寬度」補值；其他寬度視為壞列，**不默默修**（要人工判讀）
KNOWN_WIDTHS = (6, 7, 8)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f)]
    # 去掉完全空白的列（尾端空行）
    return [r for r in rows if r and any(c.strip() for c in r)]


def normalize(rows):
    """回傳 (new_rows, stats)。不修改輸入。"""
    stats = {"header_before": None, "padded": 0, "already_ok": 0,
             "padded_exclude_daily": 0, "padded_cost": 0,
             "anomalies": [], "unusual_last_field": []}
    if not rows:
        return [list(HEADER)], stats

    body = rows[1:] if rows[0] and rows[0][0] == "timestamp" else rows
    if rows[0] and rows[0][0] == "timestamp":
        stats["header_before"] = len(rows[0])

    new_body = []
    for i, r in enumerate(body, start=1):
        if len(r) == WIDTH:
            new_body.append(list(r))
            stats["already_ok"] += 1
            if r[6] not in ("0", "1"):
                stats["unusual_last_field"].append(r)
        elif len(r) in KNOWN_WIDTHS and len(r) < WIDTH:
            # 依「缺的位置」補對應預設值（6 欄的舊列會同時補 exclude_daily="0" 與 cost=""）
            filled = list(r) + [PAD_DEFAULTS.get(j, "") for j in range(len(r), WIDTH)]
            new_body.append(filled)
            stats["padded"] += 1
            if len(r) == 6:
                stats["padded_exclude_daily"] += 1
            stats["padded_cost"] += 1
            if filled[6] not in ("0", "1"):
                stats["unusual_last_field"].append(filled)
        else:
            new_body.append(list(r))
            stats["anomalies"].append((i, len(r), r))
    return [list(HEADER)] + new_body, stats


def render(rows):
    """序列化成 CSV 文字（統一 LF，欄位含逗號時自動加引號）。"""
    out = []
    for r in rows:
        buf = []
        for c in r:
            c = "" if c is None else str(c)
            if any(ch in c for ch in ',"\n\r'):
                c = '"' + c.replace('"', '""') + '"'
            buf.append(c)
        out.append(",".join(buf))
    return "\n".join(out) + "\n"


def atomic_replace(path, text):
    d = os.path.dirname(os.path.abspath(path))
    try:
        mode = os.stat(path).st_mode & 0o777   # mkstemp 是 0600 → 必須保留原權限
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_perf_", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser(description="performance.csv schema 正規化（6 欄 → 7 欄）")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設只做 dry-run 報告）")
    args = ap.parse_args()

    path = args.file
    if not os.path.exists(path):
        print(f"❌ 找不到檔案：{path}")
        return 1

    size_before = os.path.getsize(path)
    with open(path, "rb") as f:
        raw = f.read()
    cr_rows = raw.count(b"\r")
    rows = read_rows(path)
    new_rows, st = normalize(rows)
    text = render(new_rows)
    widths = Counter(len(r) for r in rows[1:]) if len(rows) > 1 else Counter()

    print(f"檔案：{path}（{size_before:,} bytes，{len(rows)} 列）")
    print(f"表頭：{st['header_before']} 欄 → {WIDTH} 欄")
    print(f"資料列寬度分佈：{dict(sorted(widths.items()))}")
    print(f"需補欄：{st['padded']} 列"
          f"（exclude_daily 補 `0` 共 {st['padded_exclude_daily']} 列＝沿用舊語意「計入每日交易次數」；"
          f"cost 補空共 {st['padded_cost']} 列＝未記錄，讀取端以費率推定）")
    print(f"已正確：{st['already_ok']} 列")
    if cr_rows:
        print(f"換行：{cr_rows} 列是 CRLF、其餘 LF（混用）→ 統一成 LF")
    if st["unusual_last_field"]:
        print(f"⚠️ exclude_daily 欄非 0/1 的列（**保持原樣、不猜測語意**）："
              f"{len(st['unusual_last_field'])} 列")
        for r in st["unusual_last_field"][:5]:
            # 注意：不能寫 r[WIDTH-1]（那是 cost 欄）—— 要的是 exclude_daily（索引 6）
            print(f"   {r[0]} {r[1]} → exclude_daily={r[6]!r}")
    if st["anomalies"]:
        print(f"❌ 寬度異常的列（非 6/7 欄，需人工判讀）：{len(st['anomalies'])} 列")
        for i, w, r in st["anomalies"][:5]:
            print(f"   第 {i} 列（{w} 欄）：{r}")

    changed = (st["padded"] > 0 or st["header_before"] != WIDTH
               or len(rows) != len(new_rows))
    if not changed:
        print("\n✅ 已是單一 schema（7 欄），無事可做")
        return 1 if st["anomalies"] else 0

    if not args.apply:
        print("\n🔎 dry-run：未寫入。確認無誤後加 `--apply` 執行（會先備份）。")
        return 0

    # CAS：確認期間沒有新成交被 append（否則我們的副本已過期）
    if os.path.getsize(path) != size_before:
        print("\n❌ 中止：檔案在讀取後被修改（可能有新成交寫入）→ 請重跑一次")
        return 1

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.bak_schema_{ts}"
    with open(path, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    atomic_replace(path, text)

    after = read_rows(path)
    ok = all(len(r) == WIDTH for r in after)
    print(f"\n✅ 已遷移：{len(after)} 列全部 {WIDTH} 欄（驗證{'通過' if ok else '失敗'}）")
    print(f"   備份：{backup}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
