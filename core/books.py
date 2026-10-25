"""core/books.py — 三本帳一致性檢查（**唯一實作**，供實盤斷言與對帳腳本共用）

三本帳：
  1. `logs/performance.csv`          — 成交紀錄（append-only，券商回報後寫入）
  2. `logs/holdings.json`            — 目前持股（**所有賣出／孤兒清倉的唯一依據**）
  3. `logs/stock_allocation.json`    — 分帳本（成本基礎，算 avg_cost／資金上限用）

為什麼需要（2026-09-13 實案）：VM 上 2395/3665 各 36 股**只寫進 performance.csv**、
沒進 holdings.json／分帳本（成本基礎缺口 92,484）⇒ 產生兩個後果：
  * 總資產口徑 A（`core/drawdown_guard.compute_equity`）低估 91,764；
  * **這種部位永遠不會被賣掉**（賣出只認 holdings.json）。
詳見 `cairn/total-assets-reconciliation.md`。

設計原則：
- 檢查**不需要現價、不需要網路**（純比對股數與成本）→ 可以每個迴圈跑。
- 缺檔（分帳本／持股檔不存在）一律視為**不一致**，不回退成 0 靜默通過
  （2026-09-13 踩過：分帳本路徑寫錯 → cost=0 → 算出 2,055,586 的荒謬總資產）。
- `holdings` 是記憶體快照：與磁碟不同 = 別的 writer 寫過 → 我們下一次
  `save_holdings` 會把對方的成交**整份蓋掉**（lost update）→ 必須告警。
"""
import csv
import fcntl
import json
import os
import tempfile
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
PERF_FILE = os.path.join(_ROOT, "logs", "performance.csv")
HOLDINGS_FILE = os.path.join(_ROOT, "logs", "holdings.json")
ALLOC_FILE = os.path.join(_ROOT, "logs", "stock_allocation.json")
AUDIT_LOG_FILE = os.path.join(_ROOT, "logs", "books_audit.jsonl")


# ── 檔案鎖／原子寫入 ────────────────────────────────────────────────
class file_lock:
    """跨行程排他鎖（flock）。用法：`with file_lock(path): ...`。

    鎖檔為 `<path>.lock`（不鎖資料檔本身，避免與讀取端互卡）。
    同一行程內重入需要各自開新 fd，這裡不做重入保護（實盤無此需求）。
    """

    def __init__(self, path):
        self.lock_path = path + ".lock"
        self._fh = None

    def __enter__(self):
        d = os.path.dirname(self.lock_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._fh = open(self.lock_path, "a+")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
        return False


def atomic_write_json(path, obj, indent=4):
    """原子寫 JSON：寫暫存檔 → fsync → `os.replace`（同目錄內 rename 為原子操作）。

    避免「寫到一半被砍」留下半截 JSON（VM 的 cron 曾在盤中關機）。
    寫入全程持有 `file_lock(path)`，序列化並行 writer。

    ⚠️ **權限必須保留**：`tempfile.mkstemp` 建出的是 `0600`，若直接 `os.replace`
    會把原本 `0644` 的狀態檔變成只有 root 能讀（2026-09-13 實測踩到：
    `logs/processed_capital.json` 被改寫後變 `-rw-------`）。
    新檔則沿用舊版 `open(..., "w")` 的結果（`0666 & ~umask` ＝ 一般 `0644`）。
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with file_lock(path):
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            mode = 0o644
        fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=indent, ensure_ascii=False)
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


# ── 三本帳讀取 ──────────────────────────────────────────────────────
def read_trades(path=None):
    """讀 performance.csv；欄位 timestamp,symbol,signal,price,quantity,action。"""
    path = path or PERF_FILE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("symbol") and r.get("action")]


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_holdings(path=None):
    """持股數量 `{代號: 股數}`（>0）——格式正規化共用 `core.live_state.held_quantities`。

    2026-09-22：原本這裡自己寫一份 `int(v)`，而 picker 另寫一份只吃 `{"qty": N}` 的版本
    ⇒ 兩個呼叫端對「已持倉」的認知不一致（picker 那側永遠是空的、把持倉股誤列為汰換）。
    統一走同一支函式後，格式差異只留在 `held_quantities` 一處。
    """
    from core.live_state import held_quantities
    return held_quantities(load_json(path or HOLDINGS_FILE, {}) or {})


def load_ledger(path=None):
    return load_json(path or ALLOC_FILE, {}) or {}


def fifo_open_positions(trades):
    """FIFO 推算未平倉部位 → `({sym: (股數, 成本)}, 已實現損益, 賣出無對應買進 {sym: 股數})`。

    **2026-09-17 起含交易成本**：買進手續費計入該批成本基礎、賣出（手續費＋證交稅）
    從已實現損益扣除 ⇒ 回傳的成本與損益都是**淨額**。費用取 CSV 的 `cost` 欄，
    舊列沒有則以現行費率推定（`core/fees.row_cost`）。
    """
    from core import fees as _fees
    lots, realized, unmatched = {}, 0.0, {}
    for r in trades:
        sym = str(r["symbol"])
        try:
            px, qty = float(r["price"]), int(r["quantity"])
        except (TypeError, ValueError):
            continue
        _cost = _fees.row_cost(r)
        if str(r["action"]).strip().upper() == "BUY":
            # 成本基礎含買進手續費（每股單價）
            unit = ((px * qty) + _cost) / qty if qty > 0 else px
            lots.setdefault(sym, []).append([qty, unit])
            continue
        left = qty
        while left > 0 and lots.get(sym):
            sh, cpx = lots[sym][0]
            take = min(sh, left)
            # 賣出成本（手續費＋證交稅）按成交股數比例分攤到被配對的股數
            realized += take * (px - cpx) - (_cost * take / qty if qty > 0 else 0.0)
            sh -= take
            left -= take
            if sh == 0:
                lots[sym].pop(0)
            else:
                lots[sym][0][0] = sh
        if left > 0:
            unmatched[sym] = unmatched.get(sym, 0) + left
    open_lots = {s: (sum(l[0] for l in ls), sum(l[0] * l[1] for l in ls))
                 for s, ls in lots.items() if sum(l[0] for l in ls) > 0}
    return open_lots, realized, unmatched


def ledger_cost(alloc):
    return sum(float(v.get("total_buy_cost", 0) or 0)
               for v in (alloc or {}).values() if isinstance(v, dict))


def ledger_shares(alloc):
    out = {}
    for sym, v in (alloc or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            sh = int(v.get("total_buy_shares", 0) or 0)
        except (TypeError, ValueError):
            continue
        if sh > 0:
            out[str(sym)] = sh
    return out


# ── 對帳 ────────────────────────────────────────────────────────────
def csv_schema(path=None):
    """檢查 performance.csv 的欄位寬度是否一致（表頭 vs 每一列）。

    為什麼要查：表頭曾是 6 欄，2026-09-01 之後程式改寫 7 欄（多 `exclude_daily`）
    ⇒ 檔案混兩種寬度。**按欄位序號解析會錯位**，`DictReader` 則會把多出的值塞到
    key `None`（靜默錯位，比爆掉更危險）。遷移工具：
    `scripts/migrate_performance_csv_schema.py`（補欄 + 修表頭 + 備份）。
    """
    path = path or PERF_FILE
    out = {"header_cols": None, "width_counts": {}, "drift_rows": 0,
           "unusual_last_field": 0, "ok": True}
    if not os.path.exists(path):
        return out
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f) if r and any(c.strip() for c in r)]
    except Exception:
        out["ok"] = False
        return out
    if not rows:
        return out
    header, body = rows[0], rows[1:]
    out["header_cols"] = len(header)
    out["width_counts"] = dict(Counter(len(r) for r in body))
    out["drift_rows"] = sum(1 for r in body if len(r) != len(header))
    out["unusual_last_field"] = sum(
        1 for r in body if len(r) == len(header) and len(r) >= 7 and r[-1] not in ("0", "1", ""))
    out["ok"] = out["drift_rows"] == 0
    return out


def audit_books(perf_csv=None, holdings=None, alloc=None,
                holdings_on_disk=None, holdings_path=None):
    """比對三本帳，回傳結構化結果（**不需要現價、無網路**）。

    參數 `holdings` 為記憶體快照；`holdings_on_disk`/`holdings_path` 有給時
    額外偵測「記憶體 vs 磁碟」落差（＝lost update 前兆）。

    回傳 dict：
      ok            三本帳一致、記憶體未漂移、且 CSV schema 正常
      phantom       CSV 有、holdings 沒有的部位 {sym: 股數}（**永遠不會被賣出**）
      ghost         holdings 有、CSV FIFO 沒有的部位
      unmatched     賣出找不到對應買進
      memory_drift  記憶體 holdings 與磁碟不同 {sym: [mem, disk]}
      csv_schema    CSV 欄寬檢查（`drift_rows > 0` ⇒ 混 schema，見 `csv_schema()`）
      ledger_gap    分帳本成本基礎缺口（Σcost_open(CSV FIFO) − Σcost_ledger）
                    ⚠️ **僅供參考、不列入 `ok`**：分帳本是「加權平均成本按比例扣減」
                    （`core/live_utils.sell_stock_allocation`），CSV 這邊是 FIFO ——
                    買價不同又部分賣出時兩者**本來就會合法地不同**，當成錯誤會誤報。
                    （2026-09-13 實測：VM 上 5 檔真實部位成本與分帳本**逐檔分毫不差**，
                    差額 92,484 全來自幽靈部位 ⇒ 該案例中兩者恰好一致。）
      missing       缺少的檔案路徑清單
      summary       人類可讀摘要
      signature     不一致指紋（用來「同一種不一致只通知一次」）
    """
    perf_csv = perf_csv or PERF_FILE
    missing = []
    if not os.path.exists(perf_csv):
        missing.append(perf_csv)
    schema = csv_schema(perf_csv) if not missing else {"ok": True, "drift_rows": 0}
    if holdings is None:
        holdings_path = holdings_path or HOLDINGS_FILE
        if not os.path.exists(holdings_path):
            missing.append(holdings_path)
        holdings = load_holdings(holdings_path)
    if alloc is None:
        if not os.path.exists(ALLOC_FILE):
            missing.append(ALLOC_FILE)
        alloc = load_ledger()

    trades = read_trades(perf_csv)
    open_lots, realized, unmatched = fifo_open_positions(trades) if trades else ({}, 0.0, {})
    csv_shares = {s: v[0] for s, v in open_lots.items()}
    cost_open_csv = sum(v[1] for v in open_lots.values())
    cost_ledger = ledger_cost(alloc)

    holdings = {str(k): int(v) for k, v in (holdings or {}).items() if int(v) > 0}
    phantom = {s: csv_shares[s] - holdings.get(s, 0)
               for s in sorted(csv_shares) if csv_shares[s] > holdings.get(s, 0)}
    ghost = {s: holdings[s] - csv_shares.get(s, 0)
             for s in sorted(holdings) if holdings[s] > csv_shares.get(s, 0)}

    memory_drift = {}
    if holdings_on_disk is None and holdings_path:
        holdings_on_disk = load_holdings(holdings_path)
    if holdings_on_disk is not None:
        for s in sorted(set(holdings) | set(holdings_on_disk)):
            mem, dsk = holdings.get(s, 0), holdings_on_disk.get(s, 0)
            if mem != dsk:
                memory_drift[s] = [mem, dsk]

    ledger_gap = cost_open_csv - cost_ledger if open_lots else 0.0

    bits = []
    if missing:
        bits.append(f"缺檔 {len(missing)} 個：{', '.join(os.path.basename(p) for p in missing)}")
    if phantom:
        bits.append("幽靈部位（CSV 有、holdings 沒有，永遠不會被賣出）："
                    + ", ".join(f"{s}×{n}" for s, n in phantom.items()))
    if ghost:
        bits.append("holdings 有、CSV 找不到買進："
                    + ", ".join(f"{s}×{n}" for s, n in ghost.items()))
    if unmatched:
        bits.append("賣出無對應買進：" + ", ".join(f"{s}×{n}" for s, n in unmatched.items()))
    if memory_drift:
        bits.append("記憶體/磁碟漂移（下一筆 save_holdings 會蓋掉對方）："
                    + ", ".join(f"{s} mem={v[0]} disk={v[1]}" for s, v in memory_drift.items()))
    if not schema.get("ok", True):
        bits.append(f"performance.csv 混 schema（表頭 {schema.get('header_cols')} 欄、"
                    f"{schema.get('drift_rows')} 列寬度不符）→ 跑 "
                    f"scripts/migrate_performance_csv_schema.py --apply")
    ok = not (missing or phantom or ghost or unmatched or memory_drift
              or not schema.get("ok", True))
    _parts = [
        ("M" + ",".join(sorted(os.path.basename(p) for p in missing))) if missing else "",
        ("P" + ",".join(f"{s}:{n}" for s, n in phantom.items())) if phantom else "",
        ("G" + ",".join(f"{s}:{n}" for s, n in ghost.items())) if ghost else "",
        ("U" + ",".join(f"{s}:{n}" for s, n in unmatched.items())) if unmatched else "",
        ("D" + ",".join(f"{s}:{v[0]}/{v[1]}" for s, v in memory_drift.items())) if memory_drift else "",
        (f"X{schema.get('header_cols')}x{schema.get('drift_rows')}")
        if not schema.get("ok", True) else "",
    ]
    signature = "|".join(p for p in _parts if p) or "clean"
    return {
        "ok": ok, "phantom": phantom, "ghost": ghost, "unmatched": unmatched,
        "memory_drift": memory_drift, "ledger_gap": ledger_gap,
        "csv_schema": schema,
        "cost_open_csv": cost_open_csv, "cost_ledger": cost_ledger,
        "csv_shares": csv_shares, "holdings": holdings,
        "fifo_realized": realized, "missing": missing,
        "summary": "；".join(bits) if bits else "三本帳一致",
        "signature": signature,
    }


def append_audit_log(record, extra=None, path=None):
    """把稽核結果 append 到 `logs/books_audit.jsonl`（每行一筆，供事後追查）。"""
    path = path or AUDIT_LOG_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    row = {k: v for k, v in record.items()
           if k in ("ok", "phantom", "ghost", "unmatched", "memory_drift",
                    "ledger_gap", "cost_open_csv", "cost_ledger", "summary",
                    "signature", "missing", "csv_schema")}
    if extra:
        row.update(extra)
    from datetime import datetime
    row["ts"] = datetime.now().isoformat(timespec="seconds")
    with file_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
