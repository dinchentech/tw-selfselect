---
type: project_topic
status: active
summary: "總資產三個口徑（A 現金流／B 儀表板／C CSV 自洽）的代數關係、三本帳不一致的偵測與修帳工具，以及 2026-09 帳務缺口事故"
tags: [帳務, 對帳, 總資產, 三本帳, 事故]
contains: [experience, procedure, lesson, open_question]
created: "2026-10-26"
updated: "2026-10-26"
related: [environment-scope.md, backtest-data-pitfalls.md]
authoring_mode: ai_generated
---
# 總資產對帳（三本帳一致性）

## 背景

**2026-09-13 實案**：VM 上 2395、3665 各 36 股**只寫進 `logs/performance.csv`**，沒進 `logs/holdings.json` 與分帳本（成本基礎缺口 92,484）。

兩個後果：

1. 總資產口徑 A（`core/drawdown_guard.compute_equity`，股災防護用）低估 91,764。
2. **這種部位永遠不會被賣掉**——賣出與孤兒清倉只認 `holdings.json`。

同一案還有第二個坑：分帳本路徑曾被寫錯 ⇒ `cost=0` ⇒ 算出 **2,055,586** 的荒謬總資產。所以「缺檔」若回退成 0 靜默通過，錯誤比直接報錯更危險。

## 當前結論

三本帳，各有單一權威：

| 帳 | 檔案 | 角色 |
|---|---|---|
| 成交紀錄 | `logs/performance.csv` | append-only，券商回報後寫入 |
| 目前持股 | `logs/holdings.json` | **所有賣出／孤兒清倉的唯一依據** |
| 分帳本 | `logs/stock_allocation.json` | 成本基礎（算 `avg_cost`／資金上限） |

三個總資產口徑（`scripts/reconcile_total_assets.py`）：

- **A 現金流**（MDB 股災防護用）＝ `TOTAL_CAPITAL + (ΣSELL − ΣBUY) + Σ(holdings.json 股數 × 現價)`
- **B 儀表板**＝ `TOTAL_CAPITAL + FIFO已實現 + (持股市值 − 分帳本成本)`
- **C CSV 自洽**＝ `現金 + Σ(CSV FIFO 未平倉股數 × 現價)`

**A 與 B 代數恆等**：`B − A ≡ Σ未平倉成本基礎(CSV) − Σ分帳本成本基礎`（因為 `FIFO已實現 = 淨現金流 + Σ未平倉成本基礎`）。⇒ 帳務一致時 A ≡ B；兩者不同**只代表三本帳不同步**，不是公式錯。真正的價值是抓出「不同步」，部位比對由 `core/books.py` 提供（**唯一實作**，實盤斷言與對帳腳本共用）。

設計原則（`core/books.py`）：

- 檢查**不需要現價、不需要網路**（純比對股數與成本）⇒ 可以每個迴圈跑。
- 缺檔（分帳本／持股檔不存在）一律視為**不一致**，不回退成 0。
- `holdings` 是記憶體快照：與磁碟不同 ⇒ 別的 writer 寫過 ⇒ 下一次 `save_holdings` 會把對方成交**整份蓋掉**（lost update）⇒ 必須告警。

## 實踐指南

| 要做的事 | 指令 | 備註 |
|---|---|---|
| 三口徑對帳 + 三本帳檢查 | `.venv/bin/python scripts/reconcile_total_assets.py` | 離開碼 0 ＝ 一致；1 ＝ 不一致／缺檔（無現價時刻意 fail-loud）；`--prices 2395=674`、`--json`、`--perf <path>` |
| 券商庫存 vs 本機 | `docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py` | **唯讀**，離開碼 0／1（有差異）／2（查不到券商）；修帳用 `--print-fix` 人工確認後執行 |
| 作廢「只寫進 CSV 的買進」 | `python3 scripts/void_untracked_buys.py`（預設 dry-run） | `--apply` 才寫檔：先備份 `.bak_void_<時間戳>`、作廢列存 `logs/voided_trades.jsonl`、替換前 CAS、套用後自我驗證 |
| 稽核摘要 | `core.books.audit_books()` | 對帳腳本與上述工具的共用入口 |

## 教訓

- **缺口不會自己消失**：只寫進 CSV 的部位在報表上看得到、卻永遠不會被賣出。發現帳不平要當天補，不要等月底。
- **fail-loud 勝過 fail-silent**：缺檔回退成 0 會製造一個「看起來很合理」的錯誤總資產。
- **lost update 是靜默的**：兩個 writer 同時持有記憶體快照時，後寫的會整份覆蓋先寫的；`holdings` 與磁碟不一致就是這個訊號。
- **修帳要留人工關卡**：對帳工具一律唯讀，改動一律先 dry-run、先備份、留稽核軌跡。

## 開放問題

1. `core/books.py` 可以在每個迴圈跑，但目前只在實盤斷言與腳本被動用；要不要升級成排程告警（Telegram）？
2. 三本帳同時損壞時的修復順序（以哪本為真）目前只寫在工具 docstring，尚未抽成一節流程。
