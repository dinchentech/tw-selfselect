#!/usr/bin/env python3
"""scripts/snapshot_broker.py — 每日把**券商原始回傳**落地成快照（唯讀，2026-11-05）

## 為什麼需要（血的教訓）

2026-11-05 要查「11/03 那 4 筆 0050 到底成交幾筆」，結果**模擬帳的 API 全部查不到歷史**：

| API | 實測 |
|---|---|
| `get_transactions_by_date('2026-11-03','2026-11-03')` | **0 筆**（連當天確定成交的 4 檔股票都沒有）|
| `get_order_results_by_date(...)` | 全空（連當天已知成交的委託也查不到）|
| `get_inventories()` | 只回「當日未交割」部位（長期持有的都不在）|
| `get_balance()` | 全 0（模擬帳不追現金）|

⇒ **「查不到」不是「沒發生」**。對帳資料必須在還查得到的時候落地，之後任何爭議都能重跑
（`scripts/reconcile_broker_books.py --from-json logs/broker_snapshot_<日期>.json`）。

## 用法

```bash
docker exec tw_selfselect_bot python scripts/snapshot_broker.py            # 今天
docker exec tw_selfselect_bot python scripts/snapshot_broker.py --date 2026-11-05
docker exec tw_selfselect_bot python scripts/snapshot_broker.py --out-dir logs --quiet
```

- 輸出：`logs/broker_snapshot_<日期>.json`（同一天重跑會把上一次收進 `previous`，最多留 5 份）
  ＋ 每次執行在 `logs/broker_snapshot_history.jsonl` 加一筆摘要（只追加）。
- 離開碼：`0` 成功（含部分 API 失敗但有寫檔）；`2` 取不到券商資料（SDK 不可用）——**不刪舊檔**。
- 本工具**只讀**：不呼叫 `place_order`／`cancel_order`，也不改任何帳本。

## 主程式整合

交易日 13:45 收盤報告那一輪自動跑一次（`selfselect_trader.py` 的收盤報告區塊）。
當天已成功寫過就跳過（避免多開券商 session）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_f = globals().get("__file__", "")
_ROOT = (Path(_f).resolve().parent.parent if _f and not str(_f).startswith("<") else Path.cwd())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_OUT_DIR = "logs"
KEEP_PREVIOUS = 5


def to_jsonable(obj, _depth: int = 0):
    """把 SDK 回傳（可能是物件／namedtuple／巢狀 list）轉成可 JSON 化的結構。

    未知型別 → `str(obj)`（**絕不丟棄**：寧可留下一行字串，也不要讓快照靜默缺欄位）。
    """
    if _depth > 8:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v, _depth + 1) for v in obj]
    fields = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if callable(val):
            continue
        fields[name] = to_jsonable(val, _depth + 1)
    return fields or str(obj)


def summarize(inventories, transactions, order_results, settlements=None) -> dict:
    """快照摘要（人也看得懂；寫進 history 與 stdout）。

    2026-11-05 補 `settlements`（未交割明細）：它會隨交割日消失 ⇒ 摘要至少留下「有幾筆、哪些交割日」。
    """
    inv = to_jsonable(inventories) or []
    tx = to_jsonable(transactions) or []
    od = to_jsonable(order_results) or []
    se = to_jsonable(settlements) or []
    inv_syms = sorted({str(x.get("stk_no")) for x in inv if isinstance(x, dict) and x.get("stk_no")})
    tx_syms = sorted({str(x.get("stk_no")) for x in tx if isinstance(x, dict) and x.get("stk_no")})
    se_dates = sorted({str(x.get("c_date")) for x in se if isinstance(x, dict) and x.get("c_date")})
    return {"inventories": len(inv), "inventory_symbols": inv_syms,
            "transactions": len(tx), "transaction_symbols": tx_syms,
            "order_results": len(od),
            "settlements": len(se), "settlement_dates": se_dates}


def merge_previous(new_payload: dict, old: dict | None, keep: int = KEEP_PREVIOUS) -> dict:
    """同一天重跑：把舊內容塞進 `previous`（保留最近 `keep` 份），不丟掉先前的證據。"""
    if not old:
        return new_payload
    prev = list(old.get("previous") or [])
    snap = {k: v for k, v in old.items() if k != "previous"}
    prev.append(snap)
    new_payload["previous"] = prev[-keep:]
    return new_payload


def already_done(date_str: str, out_dir: str | Path = DEFAULT_OUT_DIR) -> bool:
    """當天是否已經成功寫過快照（主程式用它避免重複開券商 session）。"""
    p = Path(out_dir) / f"broker_snapshot_{date_str}.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not d.get("ok"):
        return False
    # 「全部空白」視為**沒抓到**（例如行情／交易 API 當下全掛）⇒ 允許當天再試一次。
    # 注意：`balance` 即使是 0 也代表「有回應」，所以用 `is not None` 而不是真值判斷。
    has_content = any(
        (d.get(k) not in (None, [], {})) for k in ("inventories", "transactions", "order_results",
                                                   "balance", "settlements")
    )
    return bool(has_content)


def fetch(prov, date_str: str) -> tuple[dict, dict]:
    """向券商取原始資料 → `(payload 各部分, 各項錯誤)`。任何一項失敗都不讓整體失敗。"""
    data, errors = {}, {}
    sdk = getattr(prov, "_trade_sdk", None)
    if sdk is None:
        try:
            prov.login()
        except Exception as e:
            errors["login"] = str(e)
        sdk = getattr(prov, "_trade_sdk", None)
    if sdk is None:
        return data, {**errors, "sdk": "trade SDK 不可用"}

    def _call(key, fn, *a):
        try:
            data[key] = to_jsonable(fn(*a))
        except Exception as e:
            errors[key] = f"{type(e).__name__}: {e}"

    if hasattr(prov, "query_inventories"):
        _call("inventories", prov.query_inventories)
    else:
        _call("inventories", sdk.get_inventories)
    if hasattr(prov, "query_transactions"):
        _call("transactions", prov.query_transactions, date_str, date_str)
    else:
        _call("transactions", sdk.get_transactions_by_date, date_str, date_str)
    _call("order_results", sdk.get_order_results_by_date, date_str, date_str)
    _call("balance", sdk.get_balance)
    # 未交割明細（2026-11-05）：交割日一到就消失 ⇒ 每天落地才看得到現金流。
    if hasattr(prov, "query_settlements"):
        _call("settlements", prov.query_settlements)
    else:
        _call("settlements", sdk.get_settlements)
    return data, errors


def build_payload(date_str: str, data: dict, errors: dict, version: str = "") -> dict:
    payload = {
        "date": date_str,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "version": version,
        "source": "scripts/snapshot_broker.py",
        "note": "券商原始回傳快照；模擬環境不保留歷史，這份是本機唯一的回溯依據",
        "inventories": data.get("inventories"),
        "transactions": data.get("transactions"),
        "order_results": data.get("order_results"),
        "balance": data.get("balance"),
        "settlements": data.get("settlements"),
        "errors": errors,
        "summary": summarize(data.get("inventories"), data.get("transactions"),
                             data.get("order_results"), data.get("settlements")),
    }
    payload["ok"] = not errors.get("sdk")
    return payload


def save(payload: dict, out_dir: str | Path = DEFAULT_OUT_DIR) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"broker_snapshot_{payload['date']}.json"
    old = None
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = None
    payload = merge_previous(payload, old)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        with (out / "broker_snapshot_history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": payload["generated_at"], "date": payload["date"],
                                "ok": payload["ok"], "summary": payload["summary"],
                                "errors": sorted(payload["errors"])},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把券商原始回傳落地成每日快照（唯讀）")
    ap.add_argument("--date", default=None, help="快照日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-dotenv", action="store_true",
                    help="不要 load_dotenv（主程式內呼叫時用：避免在長時間執行的行程裡改寫環境變數）")
    args = ap.parse_args(argv)

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    try:
        from data.esun_provider import EsunProvider
    except Exception as e:
        print(f"❌ 取不到 EsunProvider（{e}）；不寫檔、不刪舊檔", file=sys.stderr)
        return 2
    if (Path(".env")).exists() and not args.no_dotenv:
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)          # 與其他 docker exec 工具一致
        except Exception:
            pass
    try:
        from core.version import APP_VERSION
        ver = APP_VERSION
    except Exception:
        ver = ""

    data, errors = fetch(EsunProvider(), date_str)
    payload = build_payload(date_str, data, errors, ver)
    path = save(payload, args.out_dir)
    if not args.quiet:
        s = payload["summary"]
        print(f"📸 券商快照 {payload['date']} → {path}")
        print(f"   庫存 {s['inventories']} 筆 {s['inventory_symbols']}｜"
              f"成交 {s['transactions']} 筆 {s['transaction_symbols']}｜"
              f"委託 {s['order_results']} 筆｜未交割 {s.get('settlements', 0)} 筆 {s.get('settlement_dates', [])}")
        if errors:
            print("   ⚠️ 部分項目失敗：" + "；".join(f"{k}={v}" for k, v in errors.items()))
    return 2 if errors.get("sdk") else 0


if __name__ == "__main__":
    sys.exit(main())
