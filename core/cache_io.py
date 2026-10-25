"""
cache_io.py — 版本化 pickle 快取讀寫（全專案共用）

快取資料語義改變（欄位/價格調整/正規化方式）時必須遞增 CACHE_SCHEMA_VERSION，
否則舊快取會被靜默載入——2026-08 回測數字無法重現事件（價格快取混入 yfinance 還原價）的根因。

用法：
  - 可重建快取（股價/法人/選股池）→ load_cache / dump_cache；版本不符自動重建。
  - 累積資料庫（mcap_ranking / historical_shares）→ load_cache_or_raw；
    舊格式原樣讀入（不丟棄無法重建的歷史資料），下次寫入時自動升級為版本化。
"""
import os
import pickle
from pathlib import Path

CACHE_SCHEMA_VERSION = 2


def dump_cache(path, data, meta=None):
    payload = {"schema_version": CACHE_SCHEMA_VERSION, "meta": meta or {}, "data": data}
    tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
    tmp.write_bytes(pickle.dumps(payload))
    os.replace(tmp, path)


def load_cache(path, quiet: bool = False):
    """讀版本化快取 → `(data, meta)`；版本不符回 `(None, None)`。

    `quiet=True`：不印「版本不符」訊息（給 `load_cache_or_raw` 用——它馬上會改讀原檔並印一行合併訊息，
    避免同一個檔案印兩行、看起來像兩個問題）。
    """
    try:
        payload = pickle.loads(Path(path).read_bytes())
        if not isinstance(payload, dict) or payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            v = payload.get("schema_version") if isinstance(payload, dict) else "?"
            if not quiet:
                print(f"⚠️  快取版本不符（{Path(path).name}）: 快取 v{v} != 目前 v{CACHE_SCHEMA_VERSION}"
                      f"（回傳 None → 由呼叫端決定：可重建者重跑產生器，累積型者由 load_cache_or_raw 改讀原檔）")
            return None, None
        return payload.get("data"), payload.get("meta", {})
    except Exception:
        return None, None


def load_cache_or_raw(path):
    """累積型快取（`mcap_ranking`／`historical_shares`／TWSE 法人）用：版本不符時**原樣讀入**舊檔。

    為什麼不重建：這些是**累積型**資料（重建＝重新抓取，昂貴且可能被限流），丟掉就沒了。
    2026-09-22：合併成**一行**訊息（原本 `load_cache` 與這裡各印一行 ⇒ 每個舊檔看起來像兩個問題；
    實測 `VM_pick` 一次跑出 16 行，使用者問「前面那些警告有問題嗎？」）。
    """
    data, meta = load_cache(path, quiet=True)
    if data is not None:
        return data, meta
    try:
        data = pickle.loads(Path(path).read_bytes())
        print(f"⚠️  {Path(path).name} 為舊格式（無版本），原樣讀入；下次寫入時自動升級"
              f"（累積型快取，刻意不重建）")
        return data, {}
    except Exception:
        return None, None


def read_ranking_codes(path):
    """讀「市值排名」快取 → 4 碼上市代號 list（list／dict 舊 payload／v2 三種格式都吃）。

    為什麼要有這個共用讀取器（2026-09-18）：
    `mcap_ranking.pkl` 是新舊格式混用的檔案（舊＝裸 list、新＝`dump_cache` 的 v2 dict）。
    `stock_selector_grid.build_candidate_pool()` 兩種都吃，但 `core/inst_data.get_all_stock_ids()`
    與幾支回測腳本用**裸 `pickle.loads`** ⇒ 讀到 v2 dict 時會得到空池，
    然後**靜默退回「按 stock_id 排序」的假池**（＝專案最怕的那種無聲錯誤）。
    一律改用本函式讀，格式差異就只留在這一處。

    讀不到（檔案不存在／損毀）一律回 `[]`；**呼叫端要自己決定是否大聲失敗**。
    """
    data, _ = load_cache_or_raw(path)
    if isinstance(data, dict):
        for key in ("data", "ranking", "symbols"):
            if isinstance(data.get(key), (list, tuple)):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, (list, tuple)):
        return []
    out = []
    for s in data:
        s = str(s).strip()
        if s.isdigit() and len(s) == 4:
            out.append(s)
    return out
