# Telegram 通知（格式、轉義、不變式）

> 一句話：**所有動態內容都要過 `escape_md()`；訊息本身的 `*粗體*` 留在外面。** 違反這條，
> 使用者看到的就是「格式掉了」，而日誌只留一行「（Markdown 降級為純文字）」。

## 現況（2026-11-09，v1.1.38）

- 發送面共 5 個：
  | 位置 | 角色 |
  |---|---|
  | `utils/telegram.send_telegram_message()` | **唯一出口**（429 重試、Markdown→純文字降級、`md_ok()` 前置檢查） |
  | `core/live_notifications.notify_all()` | 日報／收盤／睡前／啟動報告（TG + LINE 共用） |
  | `core/live_capital` | 資金變動、`keep_wait` 加碼 |
  | `selfselect_trader.py` | 交易、停泊、風控、對帳、未知訂單等即時通知 |
  | `data/esun_provider.py` | 玉山 API 維護中告警（**自己送、沒有降級重送** ⇒ 壞了就整則發不出去） |
- `parse_mode` 用的是 **legacy `Markdown`**（不是 `MarkdownV2`，也不是 HTML）。

## 為什麼會壞（缺陷：動態內容未轉義）

legacy Markdown 把 `_`／`*`／`` ` ``／`[` 當標記。只要**落單**一個，Telegram 就回
`400 Bad Request: can't parse entities`，`send_telegram_message()` 接著降級成純文字——
訊息有送到，但粗體／排版全掉。

本專案特別容易踩，因為策略名稱本身就是底線：

| 類型 | 實例 | 來源 |
|---|---|---|
| 策略名稱 | `keep_wait`、`ma_cross`、`auto→ma_cross` | `_strategy_label()`（持倉報告） |
| 券商／對帳狀態 | `broker_mismatch`、`ledger_mismatch`、`note` | `core/park_asset.check_position()`、`core/broker_sync` |
| 例外字串 | `invalid literal for int() with base 10:` 這類 | 各 `except` 分支 |
| 指令與路徑 | `tw_selfselect_bot`、`reconcile_broker_books.py`、`logs/broker_reconcile.jsonl` | 告警內文 |

VM 實測（2026-11-09）：每天至少一則降級，`啟動持倉報告` 幾乎天天中；加上 `md_ok()` 之後
同一則的肇因（`keep_wait`）才會被印出來。

## 修法與用法

```python
from utils.telegram import send_telegram_message, escape_md

# 動態值一律包起來；靜態粗體留在外面
send_telegram_message(f'🅿️ *停泊釋出*\n{escape_md(sym)} 賣出 {done} 股 @ {px:.2f}\n'
                      f'原因：{escape_md(reason)}')

# 靜態字面裡的底線：寫成 raw f-string + 反斜線
send_telegram_message(rf'📥 *{escape_md(symbol)}* keep\_wait 加碼 {buy_shares} 股')
```

`utils/telegram.py` 提供：

| 函式 | 作用 |
|---|---|
| `escape_md(text)` | 轉義 `_ * ` `` ` `` `[`（`]` 不必）；`None` → 空字串；數字自動 `str()` |
| `md_ok(text)` | 粗檢標記是否成對（`*`／`_`／`` ` `` 偶數、`[`=`]`）；送出前若失敗就**直接發純文字並印出肇因**，省一次 400 往返 |

## 不變式（改動時不可破壞）

1. 任何**動態**值（股名、策略名、原因、券商回報、例外、對帳 note）進入 Markdown 訊息前必須
   `escape_md()`；`test/test_telegram_markdown_escape.py` 對 5 個發送面都有原始碼守門。
2. 訊息字面裡的**靜態底線**必須寫成 `\_`（並用 raw f-string，避免 Python 噴 invalid escape）。
3. 新加的訊息若要 `*粗體*`，兩個星號必須成對；不確定就用 `md_ok()` 自查。
4. **不要**用 `escape_md()` 包整則訊息（會把粗體一起廢掉）——只包動態那一段。
5. **粗體只有 `*x*`**：`**x**` 是 MarkdownV2，在 legacy 模式下會原樣顯示星號（`實際停泊：**無**` 就是這樣露出來的）。
6. **不要用方括號做裝飾**：legacy Markdown 的 `[文字]` 是連結語法，Telegram 會把括號吃掉
   （2026-11-09 實測：`2408[auto]` → `2408auto`）。要顯示清單請用 `()` 或 `｜`。
7. 若某個格式化函式（例：`format_plan_vs_actual()`）**自己**轉義了動態內容並保留粗體，
   呼叫端就**不可再整行 `escape_md()`**（否則是二次轉義，`*無*` 變 `\*無\*`）。

## 已知限制（尚未處理）

- **單則 4096 字元上限**：持倉報告目前 4 檔約 700 字，還很遠；但沒有長度守門，
  標的一多（或停泊說明變長）會 400。要處理就切成多則或限制欄位。
- 仍是 legacy `Markdown`：`MarkdownV2` 要轉義的字元更多（`. - ( ) ! # + = | { }` 等），
  本專案刻意留在 legacy，用「只轉義動態內容」的低成本路線。
- LINE Notify 不解析 Markdown（同一則字串照發，`*` 會直接顯示），這是既有行為。

## 測試指標

`test/test_telegram_markdown_escape.py`（16 支）：`escape_md`／`md_ok` 規則、送出閘門
（不成對 ⇒ 一次純文字、不先送 Markdown）、`send_trade_alert` 轉義 `MA_CROSS`、
持倉報告在 `keep_wait` 與 `auto→ma_cross` 下必須通過 `md_ok`、五個發送面的原始碼守門。
