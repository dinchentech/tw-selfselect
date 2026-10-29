---
type: project_topic
status: active
summary: "AI 參與選股的紀律與實測：point-in-time 封包＋DSH 兩步流程已上線；A/B 顯示『AI 明顯較好』主要來自規則組常選不滿 N 檔，規則組補滿後優勢只剩 1 個月邊際"
tags: [選股, AI, 回測, 先見之明, A/B]
contains: [experience, procedure, lesson, open_question]
created: "2026-10-28"
updated: "2026-10-29"
related: [backtest-data-pitfalls.md]
authoring_mode: ai_generated
---
# AI 選股（LLM 參與選股）的紀律

## 背景

使用者問：「母專案那種『每年換股時讓 AI 自己上網收集資料重新挑』，我們要不要也這樣做？」
並且下了一個明確的指示：**AI 挑股票不能有事後的先見之明**（不能用「後來會漲」的知識去挑當時最好的股票）。

起點（2026-10-28）：本專案的選股**完全是固定規則**（誠實池 → `ssg.score_stock()` 量化評分 → 法人確認 →
過熱剔除 → 取前 N），`catalyst_score()` 也是公式不是 AI。AI 是後來才做成**可選模式**（見 §已實作 E）。

## 當前結論

1. **「無先見之明」在 LLM 上無法被證明，只能被降低**。模型的訓練語料包含選股日之後的事件；
   即使 prompt 要求「只用我給的資料」，它仍可能答出「後來大漲的那檔」，而且外部無法驗證它是推論還是記憶。
   ⇒ AI 選股的績效必須當成**假設**，不能當成證據來宣稱「策略有效」。
2. **「可稽核」的五件事都已實作**：
   ① 只餵 **時間戳 ≤ 選股日** 的資料（point-in-time 封包，逐欄記錄資料日）；
   ② 任何欄位資料日 > 選股日 → **直接丟錯**（不得靜默放行）；
   ③ 輸出必須是 JSON，且**每檔都要引用封包內的資料編號 `[R#]`**，不得自行新增標的；
   ④ 封包／prompt／回應／模型名稱／sha256 全部落地（`logs/ai_pick/<as-of>/`），任何人可重跑比對；
   ⑤ **A/B harness**：同一天、同一池、同一 top_n，AI 排序 vs 純規則排序，比較 1/3/6/12 個月後報酬。
3. **資料不足時必須留空，不得臆測**：月營收與新聞的 point-in-time 來源**都已接上**（FinMind，
   見 §已實作 B）；缺資料仍一律留空或 `null`（法人快取目前只涵蓋近期 ⇒ 歷史封包多為 `null`）。
4. **母專案那個「AI 逐年挑 +195.5%」不能當證據**：它的名單是人工事前挑的 8 檔（45% 是指數 ETF）、
   檢討規則未公開、腳本不在任何備份裡。用 2026 年的模型回頭挑 2022 年的股票，本身就先見之明（見
   `backtest-data-pitfalls.md` 與 `results/backtest_multiwindow_2016_2026.md` 的重現實驗）。
5. **實測結論（最重要，2026-10-28～29）：AI 的優勢基本上被「規則組常常選不滿 N 檔」解釋掉了。**
   48 個選股日裡有 **28 個月規則組選不到 5 檔**（2022-09／2024-07／2025-02 甚至 0 檔）⇒
   非嚴格比較時「AI 滿倉 5 檔」對上「規則組大半時間在現金」，看起來 AI 大勝；
   一旦要求兩邊都剛好選滿 5 檔（`--require-full`），優勢就消失；再把規則組改成補滿（`topup`），
   **只剩 1 個月那點邊際**（t≈2），12 個月完全打平。數字見 §A/B 實測。
   ⇒ 這個專題真正該修的是**規則組的空手問題**，不是「AI 比較會挑」。

## 更正（2026-10-29，健檢時修正本文舊敘述）

- 舊版本寫「⑤ A/B harness（未做）」：**已於 2026-10-28 實作**（`core/ai_pick_ab.py`＋`scripts/ai_pick_ab.py`）。
- 舊版本寫「新聞來源：目前只有介面」與「本專案目前沒有月營收與新聞的快取/來源」：**兩者都已接上**（§已實作 B）。
- 舊版本寫「`--require-full`（未做）」：**已實作**，且正是它推翻了先前的「AI 顯著較好」。
- 舊版本沒有 A/B 實測數字（當時只有假模型的流程驗證）：已補 §A/B 實測。

## 實踐指南

| 想做的事 | 怎麼做 |
|---|---|
| 產生某日的 point-in-time 封包與 prompt（不呼叫模型） | `.venv/bin/python scripts/ai_pick_preview.py --as-of 2022-01-03 --show` |
| 用 DSH 目前模型選股（貼日期那條路徑） | `scripts/ai_pick_dsh.py --as-of <日期> --emit prompt` → 把模型回的 JSON 交回 `--picks '<json>' --model dsh:<模型>` |
| 選股後直接寫進 `.env`（含同步 VM） | `scripts/ai_pick_dsh.py --apply-env [--sync-env-to-vm]`（走既有寫入流程的安全檢查） |
| 接上其他模型 | `scripts/llm_cli.py --provider openai`／`ollama`／`echo`（金鑰只放環境變數，本專案不存） |
| 事後稽核某次 AI 選股 | 看 `logs/ai_pick/<as-of>/`：`pack.json`／`prompt.txt`／`response.json`／`audit.json`（hash） |
| 驗證沒有夾帶未來資料 | `core.ai_pick.assert_no_lookahead(pack, as_of)`（CLI 內已自動呼叫） |
| 比較 AI vs 純規則 | `scripts/ai_pick_ab.py`（可 `--reuse` 沿用既有稽核檔、`--require-full` 嚴格等量、`--rules-fill topup` 規則組補滿） |
| 實盤啟用 AI 選股 | `.env`：`SELFSELECT_AI=1`、`SELFSELECT_AI_DEADLINE=13:50`（D1 未完成 ⇒ 自動 fallback 回規則選股） |
| 規則組選不滿 N 檔時怎麼辦 | `.env` 的 `SELFSELECT_FILL_MODE`（實盤）／回測 `FILL_MODE`：`proportional`（預設）或 `topup` |

## 已實作

**A. 封包與稽核（2026-10-28）**
- `core/ai_pick.py`：`build_pack()`（point-in-time 封包）／`assert_no_lookahead()`／`build_prompt()`（含硬規則）／
  `parse_selection()`（schema＋引用檢查）／`write_audit()`（hash 落地）。
- `scripts/ai_pick_preview.py`：依 `--as-of` 重建**當時**的誠實池（`build_quarterly_pool`）→ 逐檔封包 → prompt
  →（可選）呼叫模型 → 稽核落地。預設不呼叫任何 API。
- `test/test_ai_pick_pack.py`（14 個）：不夾帶未來資料（把未來價格改成天價，封包不變）、缺資料留空、
  輸出驗證（不得新增標的／數量要對／引用必須是 `R#`）、稽核 hash 可重現。

**B. point-in-time 資料源（2026-10-28）**
- 月營收：`core/pit_data.py`（FinMind `TaiwanStockMonthRevenue`，免費層可用）→ 快取 `cache/stock_revenue/rev_<sid>.pkl`。
  **關鍵**：營收 `date` 是「所屬月份」不是「公布日」；`available_from = create_time（實測多為空）否則＝次月 10 日（法定公告期限）`
  ⇒ 1/2 選股看不到 2021/12 的營收，有測試守住。計算 YoY／MoM，只取 as_of 當時已公布的最近 N 個月。
- 新聞：`core/pit_news.py`（FinMind `TaiwanStockNews`，`NEWS_PROVIDER=finmind`／`--news`）。每筆到秒時間戳＋標題＋來源＋連結；
  **cutoff 13:30**（決策在收盤後）⇒ 當天 13:30 之後發布的新聞一律排除（有測試）。成本**一檔一天一次呼叫**，
  故預設關、`--news-lookback` 預設 14 天、抓過就落地 `cache/news/news_<sid>_<day>.pkl`、抓不到留空計 `misses`。
- 順手修：A/B 的封包原本沒帶 PER／法人 → 已補；`pick_dates` 在 `--start` 不是月初時會靜默 0 個選股日 → 已修＋3 個測試。

**C. A/B harness（2026-10-28）**
- 純函式 `core/ai_pick_ab.py`：`forward_return()`（還原價、對齊交易日）、`basket_return()`（等權）、
  `summarize()`（平均差、勝率、配對 t；樣本 <10 直接標「勿下結論」）、`eligible_for_compare()`（`--require-full` 的判定）。
- `scripts/ai_pick_ab.py`：逐選股日重建當時誠實池 → 封包 → 規則組（`ssg.score_stock`＋過熱剔除，與 `pick_normal` 同精神）
  與 AI 組（`--llm-cmd`／`--reuse`）→ 1/3/6/12 個月後等權報酬 → 配對彙總 → JSON；不符合條件的選股日記進 `skipped` 並印原因。

**D. DSH 兩步流程（2026-10-28）：「貼日期就用 DSH 目前的模型選股」**
- `scripts/ai_pick_dsh.py`：① `--as-of <日期> --emit prompt` 重建當時池＋封包 → 落地 `pack.json`＋`prompt.txt`（含 sha256）；
  ② `--picks '<模型回的 JSON>' --model dsh:<模型名>` 驗證（不得新增池外標的／檔數要對／引用必須 `R#`）→ 落地 `response.json`＋`audit.json`；
  ③ `--apply-env [--sync-env-to-vm]` 一步完成寫 `.env`。
- `scripts/llm_cli.py`：`--provider openai`／`ollama`／`echo`，`extract_json()` 清掉 ```json 圍欄，抽不到就 exit 2。
- 文件：`docs/AI選股-DSH操作.md`（使用者端）；測試：`test/test_ai_pick_dsh.py`＋`test/test_llm_cli.py`。
- 踩到的坑：**AI 名單必須用「同一個池」產生**——示範用池 50、A/B 用池 20 ⇒ 代號不在池內會被 `parse_selection` 擋掉。

**E. 實盤可選模式（2026-10-28）**
- `SELFSELECT_AI=1`（預設 0）＋`SELFSELECT_AI_DEADLINE=13:50`：D1 13:36 起不自動選股；期限前使用者完成 AI 選股
  （`logs/selfselect_auto.json` 的 `ai_applied=<年月>`）就不動作；**期限後仍未完成 ⇒ fallback 跑原本的規則選股**
  （label 標 `（AI 未完成 → fallback）`）。`mark_applied()` 放在**寫檔成功之後**。
- `monthly_selfselect_run.py` 新增 `--picks`／`--picks-file`／`--ai`；既有安全檢查完全不變（備份 `.env`、絕不刪已持倉、
  絕不動 keep_wait、`--sync-env-to-vm` 前 md5 比對）。文件：`使用手冊.md` §5-2b；測試：`TestAiMode`（6 個）。

**F. 「選不滿 N 檔」的兩個選項（2026-10-29）**
- 回測 `FILL_MODE`／實盤 `SELFSELECT_FILL_MODE`，預設 `proportional`＝現況（只買過濾網的股票，資金平均分給選出的檔數）；
  `topup`＝先補被過熱／法人擋掉的，仍不足再依 `_fallback_rank()`（同池 63 日動能）補到 N 檔。
- 真正的原因不是濾網太嚴：`ssg.score_stock()` 在「跌破 MA20」或流動性不足時**回傳 None** ⇒ 有些月份整個池打不出分數。
- 介面已納入 `ENV_OVERRIDE_KEYS`（否則 `.env` 會蓋掉明示值）。

## A/B 實測（2026-10-28～29，池 20、TOP5、等權、未計交易成本）

| 版本 | 樣本 | 1M | 3M | 6M | 12M |
|---|---|---|---|---|---|
| 非嚴格（規則組選不滿也照比） | n=44 | **+1.69%（t=2.18）** | +3.13%（1.79） | +2.76%（0.87） | +3.10%（0.55） |
| **嚴格等量 `--require-full`** | n=21 | +0.90%（1.03） | +2.44%（1.05） | +1.77%（0.48） | **−2.81%（−0.40）** |
| 規則組補滿 `topup` | n=47 | +0.99%（t=1.99） | +1.96%（1.69） | +1.85%（0.92） | **+0.31%（0.08）** |

- 2022 單年（n=11，空頭年）：1M +0.31%（t=0.36）、3M +1.28%（1.03）、6M −1.74%（−1.05）⇒ 全部無顯著差異。
- 逐年（12M）：2023 AI 明顯較好（+29.6% vs +8.1%、t=2.69）、2024 小幅（+17.4% vs +9.2%、t=1.09）、
  **2025 反而較差（+83.3% vs +102.0%）**、2022 混合（−1.9% vs +0.5%）。
- **誠實限制**：AI 組是混合口徑（2022 用模型判斷／2023-2025 用子代理固定公式）；2023-2025 封包含月營收、2022 沒有；
  每月選股＋12 個月持有＝窗口重疊（有效 n 遠小於 44，t 偏樂觀）；未計成本；池只有 20 檔。
- 產出：`results/ai_ab_2022_2025_report.md`、`results/ai_ab_2022_2025.json`、`results/ai_ab_2022_2025_strict.json`、
  `results/ai_ab_2225_rulestopup_n47.json`、`TMP/gen_packs_bulk.py`、`TMP/rules_topup_ab.py`。

## 還沒做

1. **統計可信度**：窗口重疊、混合口徑、未計交易成本 ⇒ n=47 的 t=1.99 仍不足以宣稱「AI 有優勢」；要 ≥30 個**互不重疊**的選股日才算話。
2. **池大小**：以上都在池 20 跑；實盤候選池是 50（`SELFSELECT_POOL_N`）⇒ 池 50 的 A/B 未做。
3. **盲測保留期**：AI 選股不能拿來回頭調 prompt（那是過度擬合），要保留一段沒看過的期間。
4. **與實盤接軌**：若真要讓 AI 參與，建議只當「最後一層重排」，並先並行記錄一段時間再決定。
5. **補滿 vs 寧缺勿濫的決策未定**：`topup` 換到固定持股數與較高利用率，但 2016-2021 長窗口報酬較差
   （正常 +20.9%→+17.2%、高風險 +55.6%→+47.8%）；目前預設仍是 `proportional`。

## 開放問題

1. A/B 顯示嚴格等量下 AI 沒有優勢 ⇒ AI 名單要不要仍允許在 `.env` 的 `PC_` 名單上覆寫？
   目前傾向：**只當「參考名單」由人確認**，不自動覆寫。
2. 新聞來源的授權與成本：已接 FinMind `TaiwanStockNews`，但「一檔一天一次呼叫」的等級與授權範圍要不要長期用？
3. 模型換版（同一個 prompt 不同模型）要不要重跑歷史 A/B？版本差異可能大於策略差異。
