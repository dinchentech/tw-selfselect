"""core/ai_pick.py — 「AI 選股」的可稽核外殼（2026-10-28 建立）

## 這個模組是什麼／不是什麼

**不是**：把選股交給 LLM 然後相信它的績效。
**是**：把「LLM 若要參與選股，最低限度該有的紀律」做成程式碼——
①只餵**時間戳 ≤ 選股日**的資料（point-in-time pack）；
②輸出必須是**可解析的 JSON**，且每一檔都要引用封包內的資料編號；
③輸入／輸出的 hash 與模型名稱全部落地成稽核檔；
④提供「AI 排序 vs 純規則」的 A/B 介面。

## 為什麼要這麼麻煩（先見之明）

LLM 的訓練資料包含選股日之後發生的事。你叫它「只依當時資訊挑」，它仍可能答出「後來會漲的那檔」，
而且**沒有任何方法能從外部證明**它沒用到未來資訊。所以本模組的定位是：
**AI 選出的是「假設」，不是「證據」**。任何要當績效數字的 AI 選股，都必須：
  - 有完整的輸入快照（可以被人重跑、被人檢查有沒有夾帶未來資料）；
  - 與純規則在同一天、同一池、同一規則下並排比較（A/B）；
  - 明確標示「無先見之明」在技術上無法證明，只能降低風險。

## 資料來源（全部只用既有快取／不需新 API）

| 欄位 | 來源 | 說明 |
|---|---|---|
| 價格與技術摘要 | `cache/selector_prices/<sid>.pkl` | 只用 ≤ as_of 的列 |
| 法人買賣超（近 15 日） | `cache/inst_momentum`（`ssg.load_twse_inst_merged()`） | 只有近期有資料，缺就標 `null` |
| PER | `cache/stock_per/per_<sid>.pkl` | 只有 ≤ as_of 的最近一筆 |
| 月營收／新聞 | **目前沒有可用快取** | 一律寫 `"unavailable": true`，**不得憑空生成** |

## 用法

    from core.ai_pick import build_pack, build_prompt, parse_selection, write_audit

    pack = build_pack(sid, as_of, data=..., inst=...)      # 單檔
    prompt = build_prompt([pack, ...], top_n=5)            # 一次給多檔
    text = llm_call(prompt)                                # ← 由呼叫端注入（本模組不打任何 API）
    picks = parse_selection(text, pool=[...], top_n=5)      # schema + 引用檢查
    write_audit("logs/ai_pick", as_of, packs, prompt, text, model="...")

CLI 見 `scripts/ai_pick_preview.py`（預設只產生封包與 prompt，不呼叫模型）。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Iterable

SCHEMA_VERSION = 1

#: 選股輸出必須符合的 JSON 結構（給 LLM 的指示與驗證共用）
PICKS_SCHEMA = {
    "type": "object",
    "required": ["as_of", "picks"],
    "properties": {
        "as_of": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["sid", "reasons", "citations"],
                "properties": {
                    "sid": {"type": "string"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "risk": {"type": "string"},
                },
            },
        },
    },
}


class PackError(ValueError):
    """封包內容不合法（含夾帶未來資料）。"""


class SelectionError(ValueError):
    """模型輸出不符合 schema／引用不實。"""


# ── point-in-time 封包 ────────────────────────────────────────────
def _fmt_date(d) -> str:
    return str(d)[:10]


def build_pack(sid: str, as_of, price_df=None, inst_series=None,
               per_series=None, extra: dict | None = None,
               revenue_rows=None, news_provider: str | None = None) -> dict:
    """單檔的 point-in-time 封包（只含 ≤ as_of 的資料；缺的就標 `null`／`unavailable`）。

    `inst_series`：`{date_str: net_buy_shares}`（≤ as_of 的部分會被用來算近 15 日累計）。
    `per_series`：`{date_str: PER}`。
    """
    import pandas as pd

    as_of_ts = pd.Timestamp(as_of)
    pack: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sid": str(sid),
        "as_of": _fmt_date(as_of_ts),
        "provenance": {},          # 每個欄位「資料到哪一天」
        "price": None, "per": None, "inst_net_15d": None,
        "month_revenue": {"unavailable": True, "reason": "本專案沒有月營收快取"},
        "news": {"unavailable": True, "reason": "本專案沒有新聞來源"},
    }

    if price_df is not None and len(price_df):
        win = price_df[price_df.index <= as_of_ts]
        if len(win):
            row = win.iloc[-1]
            close = float(row["close"])
            close_20 = float(win["close"].iloc[-21]) if len(win) >= 21 else None
            close_63 = float(win["close"].iloc[-64]) if len(win) >= 64 else None
            hi = float(win["high"].iloc[-252:].max())
            pack["price"] = {
                "close": round(close, 2),
                "ret_20d": round(close / close_20 - 1, 4) if close_20 else None,
                "ret_63d": round(close / close_63 - 1, 4) if close_63 else None,
                "dist_from_252d_high": round(close / hi - 1, 4) if hi > 0 else None,
                "px_days": int(len(win)),
            }
            pack["provenance"]["price"] = _fmt_date(win.index[-1])

    if inst_series:
        import pandas as pd  # noqa: F811
        items = [(d, v) for d, v in inst_series.items() if pd.Timestamp(d) <= as_of_ts]
        if items:
            items.sort()
            last15 = items[-15:]
            pack["inst_net_15d"] = float(sum(v for _d, v in last15))
            pack["provenance"]["inst_net_15d"] = last15[-1][0]

    if per_series:
        import pandas as pd  # noqa: F811
        items = [(d, v) for d, v in per_series.items()
                 if pd.Timestamp(d) <= as_of_ts and v is not None]
        if items:
            items.sort()
            pack["per"] = {"value": round(float(items[-1][1]), 2), "date": items[-1][0]}
            pack["provenance"]["per"] = items[-1][0]

    # 月營收（FinMind；用「公告可得日」過濾，見 core/pit_data）與新聞（預設明確留空）
    try:
        from core.pit_data import revenue_pack, news_pack
        if revenue_rows is not None:
            rev = revenue_pack(revenue_rows, as_of)
            pack["month_revenue"] = rev
            if rev.get("available"):
                pack["provenance"]["month_revenue"] = rev["provenance"]
        news = news_pack(sid, as_of, news_provider)
        pack["news"] = news
        if news.get("available"):
            pack["provenance"]["news"] = news["provenance"]
    except Exception as e:      # 資料源壞掉 → 留空，不讓選股流程失敗
        pack["month_revenue"] = {"unavailable": True, "reason": f"載入失敗：{e}"}

    for k, v in (extra or {}).items():
        pack[k] = v
    return pack


def assert_no_lookahead(pack: dict, as_of) -> None:
    """任何 provenance 日期 > as_of 都代表「夾帶未來資料」→ 直接丟錯（拒用這個封包）。"""
    import pandas as pd

    limit = pd.Timestamp(as_of)
    for field, d in (pack.get("provenance") or {}).items():
        if d is None:
            continue
        if pd.Timestamp(d) > limit:
            raise PackError(f"{pack.get('sid')}: 欄位 {field} 的資料日 {d} 晚於選股日 {_fmt_date(as_of)}")
    per = pack.get("per") or {}
    if per.get("date") and __import__("pandas").Timestamp(per["date"]) > limit:
        raise PackError(f"{pack.get('sid')}: PER 日期 {per['date']} 晚於選股日")


# ── prompt ───────────────────────────────────────────────────────
PROMPT_RULES = """你是台股量化選股助手。你只能使用下面「本次資料」裡的內容，
不得引用任何資料之外的記憶、事件或未來已知的結果。若資料不足以判斷，就明說不足。

硬規則：
1. 只能從候選清單挑選，不得新增、不得替換代號。
2. 每一檔必須給 2~3 條理由，且每條理由都要標註引用的資料編號（例如 [S3] 或 [R3]）。
3. 不得使用任何 2022 之後的事件知識（例如某人某檔後來大漲/大跌）。
4. 只輸出 JSON，不要任何其他文字，格式：
   {"as_of": "<日期>", "picks": [{"sid": "...", "reasons": ["... [R1]"], "citations": ["R1"], "risk": "..."}]}"""


def build_prompt(packs: Iterable[dict], top_n: int = 5) -> str:
    """把封包組成一份 prompt（每檔一段、附資料編號 R1..Rn 與 S1..Sn 供引用）。"""
    import pandas as pd

    lines = [PROMPT_RULES, ""]
    packs = list(packs)
    if packs:
        lines.append(f"選股日：{packs[0].get('as_of')}")
        lines.append("")
    lines.append("【本次資料】")
    for i, p in enumerate(packs, 1):
        sid = p.get("sid")
        price = p.get("price") or {}
        fields = []
        if price:
            fields.append(f"收盤 {price.get('close')}｜20日報酬 {price.get('ret_20d')}｜"
                          f"63日報酬 {price.get('ret_63d')}｜距52週高 {price.get('dist_from_252d_high')}")
        if p.get("per"):
            fields.append(f"PER {p['per'].get('value')}（{p['per'].get('date')}）")
        if p.get("inst_net_15d") is not None:
            fields.append(f"近15日法人淨買超 {p['inst_net_15d']:,.0f} 股")
        rev = p.get("month_revenue") or {}
        if rev.get("available"):
            it = rev["items"][-1]
            fields.append(f"月營收 {it['revenue']/1e8:.1f} 億（{it['year']}/{it['month']}，"
                          f"YoY {it['yoy'] if it['yoy'] is None else format(it['yoy'], '+.1%')}，"
                          f"MoM {it['mom'] if it['mom'] is None else format(it['mom'], '+.1%')}）")
        news = p.get("news") or {}
        if news.get("available"):
            fields.append("新聞：" + "；".join(n.get("title", "")[:40] for n in news["items"][-3:]))
        if not fields:
            fields.append("（無可用資料）")
        lines.append(f"[R{i}] {sid}：" + "；".join(fields))
        rev = p.get("month_revenue") or {}
        if rev.get("unavailable"):
            lines.append(f"    （注意：[R{i}] 沒有月營收資料，不得臆測）")
        if (p.get("news") or {}).get("unavailable"):
            lines.append(f"    （注意：[R{i}] 沒有新聞資料，不得臆測）")
    lines += ["", f"請從上列 {len(packs)} 檔中選出 {top_n} 檔，並依規定格式輸出 JSON。"]
    return "\n".join(lines)


# ── 輸出解析與稽核 ────────────────────────────────────────────────
def parse_selection(text: str, pool: Iterable[str], top_n: int = 5) -> dict:
    """驗證模型輸出：合法 JSON、picks 數量正確、每檔都在池內、citations 全部存在於封包。"""
    try:
        obj = json.loads(text)
    except Exception as e:
        raise SelectionError(f"不是合法 JSON：{e}") from e
    picks = obj.get("picks")
    if not isinstance(picks, list):
        raise SelectionError("缺少 picks 陣列")
    if len(picks) != top_n:
        raise SelectionError(f"picks 數量 {len(picks)} != 要求 {top_n}")
    pool = {str(s) for s in pool}
    seen = set()
    for p in picks:
        sid = str(p.get("sid", ""))
        if sid not in pool:
            raise SelectionError(f"{sid} 不在候選池內（不得自行新增標的）")
        if sid in seen:
            raise SelectionError(f"{sid} 重複")
        seen.add(sid)
        if not p.get("reasons") or not p.get("citations"):
            raise SelectionError(f"{sid} 缺少 reasons 或 citations")
        for c in p["citations"]:
            if not str(c).startswith("R"):
                raise SelectionError(f"{sid} 的引用 {c} 不是資料編號（R1..Rn）")
    return obj


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_audit(out_dir: str, as_of, packs: list, prompt: str, response: str | None,
                model: str = "(未呼叫)", extra: dict | None = None) -> dict:
    """把「輸入快照＋prompt＋輸出＋hash」落地 → 之後任何人可以重跑與比對。"""
    import pandas as pd

    day = _fmt_date(as_of)
    d = os.path.join(out_dir, day)
    os.makedirs(d, exist_ok=True)
    pack_doc = {"schema_version": SCHEMA_VERSION, "as_of": day, "model": model,
                "packs": packs, "extra": extra or {}}
    pack_hash = _sha(pack_doc)
    with open(os.path.join(d, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(pack_doc, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)
    meta = {"as_of": day, "model": model, "pack_sha256": pack_hash,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "response_sha256": hashlib.sha256((response or "").encode()).hexdigest(),
            "n_packs": len(packs)}
    if response is not None:
        with open(os.path.join(d, "response.json"), "w", encoding="utf-8") as f:
            f.write(response)
    with open(os.path.join(d, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta
