---
type: project_topic
status: active
summary: "實盤下單的致命模式：重複下單（成交查不到當成 0）、收盤後送單、記帳股數用計畫值而非券商實際送單；含已落地的不變式、事故時間軸與 VM 對帳清單"
tags: [實盤, 下單, 停泊, 事故, 對帳]
contains: [lesson, procedure, open_question]
created: "2026-11-04"
updated: "2026-11-06"
related: [total-assets-reconciliation.md, deploy-pipeline.md, environment-scope.md]
authoring_mode: ai_generated
---
# 實盤下單安全：重複下單與收盤後送單

> 起點：2026-11-04 使用者貼來的 VM log（v1.1.21）。兩個症狀都追到程式缺陷，已在 v1.1.22 修掉。

## 事故長相

```
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60      ← 連續 4 筆，金額完全相同
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
✅ E.Sun 下單成功: 盤中零股 buy 0050 282 股 @ 100.60
（而且**沒有**任何 `🅿️ 閒置資金停泊` 記帳行）

... 13:45 收盤報告／睡前報告之後 ...
⚠️ E.Sun 下單失敗（000017: 非該盤別盤中或預約時間，停止收單）→ 強制重登後重試一次
❌ E.Sun 下單失敗: 000017: 非該盤別盤中或預約時間，停止收單
```

## 缺陷一：重複下單（成交「查不到」被當成「沒成交」）

`resolve_fill()` 的契約是 **`None` ＝ 查不到成交，視為全成交**（`core/live_utils.py:253-274`），
但停泊 `park_idle_if_due()` 寫成 `done = int(filled or 0)` ⇒ `None` 變 0 ⇒ `return 0.0` ⇒ **不記帳**。

於是三件事同時成立：
1. 停泊帳沒更新 ⇒ `idle_amount()` 算出同一個金額 ⇒ 下一圈再買同樣的股數（主迴圈 `sleep(60)`）。
2. 防重複的 `last_park_ts` 是**死碼**：`core/park_asset.load_state()` 只回 symbol/shares/cost/opened/updated/last_park_date，
   **沒有 `last_park_ts`** ⇒ `selfselect_trader.py` 的「5 分鐘內不重複下單」永遠拿到 `None` ⇒ 永遠通過。
3. 13:25–13:30 的窗口剛好夠跑 4~5 圈 ⇒ 實測就是 4 筆相同金額。

**修法（v1.1.22）**：`None` 一律沿用送單股數記帳（與其他 4 條買單路徑一致）；`load_state()` 補回
`last_park_ts`；送單**失敗**也寫時間戳（不再每 60 秒重試）。回歸測試 `test/test_park_no_duplicate.py` 用 AST 釘住。

## 缺陷二：收盤後送單（下單窗口沒有上限）

`close_order_window_open()` 原本只判斷 `>= 13:25`（沒有上限）⇒ **整個下午都算「可下單」**。
13:45 的「收盤報告＋睡前報告」那一輪仍在同一輪迴圈裡 ⇒ 停泊走到下單分支 ⇒ 零股單 13:45 送出 ⇒ `000017`。
`000017` 是「時間／盤別錯」，但 `esun_provider` 一律當 session 失效去 `force_relogin()` 重試 ⇒ 重試同樣在 13:45 ⇒ 再失敗
（log 的 ⚠️／❌ 成對就是這樣來的）。

**修法（v1.1.22）**：窗口改為 `[CLOSE_ORDER_FROM, CLOSE_ORDER_TO]`（預設 **13:25–13:30**，新增 `CLOSE_ORDER_TO`）；
停泊送單前再檢查一次時間；`NON_RETRYABLE_ORDER_ERRORS`（含 `000017`）不做重登重試。
原測試 `test_window_opens_at_1325_and_has_no_upper_bound` **更正**為 `test_window_is_bounded_1325_to_1330`。

## 已落地的不變式（改動時不可破壞）

1. 「成交查不到」≠「沒成交」：`resolve_fill() is None` 一律沿用送單股數，**不得** `int(x or 0)`。
2. 任何會送單的路徑都要有**上下界**的時間閘門（不是只有下限）。
3. 任何「送單後才記帳」的路徑，**無論成敗**都要先落地冷卻時間戳，否則 60 秒迴圈會重送。
4. 時間／盤別類錯誤（`000017`）**重試無用**：重登不會改變現在幾點。

## VM 對帳清單（發現重複下單時照這個順序查）

```bash
# 1) 停泊帳（自建的帳）——shares 是否遠小於實際成交？
docker exec selfselect_trader sh -lc 'cat /app/logs/park_position.json'
# 2) 停泊稽核流水（每次買/賣一筆 JSON）——08:xx 之後 13:25–13:30 內有幾筆 BUY 0050？
docker exec selfselect_trader sh -lc 'tail -20 /app/logs/park_trades.jsonl'
# 3) 三本帳（performance.csv / holdings.json / stock_allocation.json）
docker exec selfselect_trader sh -lc 'tail -20 /app/logs/performance.csv; cat /app/logs/holdings.json'
# 4) 帶時間戳的完整 log（才能確認「哪一輪」送的單）
docker logs -t --since 48h selfselect_trader | grep -E '下單|停泊|000017' | tail -50
# 5) 券商實際成交：以玉山 App／API 的委託與成交明細為準（本機看不到就無法定案）
#    若 (3) 與券商不一致 ⇒ 跑 scripts/reconcile_broker_books.py 產出稽核報告再決定補記或作廢
```

**判讀原則**：停泊帳 `shares` 是「我們以為買到的」，玉山成交明細是「真的買到的」。
兩者不一致時**以券商為準**，且要先確認現金是否足以支撐（4 筆 × 282 股 ≈ 11.3 萬 vs idle 2.8 萬 ⇒ 可能動用到股票部位的現金）。

## 開放問題

1. 停泊「成交未確認」時目前選擇「先依送單股數記帳」——若券商最後退單，帳上會多一筆不存在的持股。
   要不要改成「pending 佇列 + 隔日以 `get_transactions_by_date` 對帳」？（本輪選了較簡單的作法止血。）
2. 停泊買進沒有經過 `MAX_DAILY_TRADES_PER_SYMBOL`／`place_buy()` 的既有護欄（它直接呼叫 `broker.place_order`）。
   是否要讓停泊也受單日次數上限約束？
3. `NET_QUOTE_TIMEOUT_SEC=8` 在 5 分鐘窗口裡仍偏長（逐檔串行）⇒ 是否降到 5 秒？

## 模擬環境的對帳 API 限制（2026-11-05 實測，重要）

11/03 那 4 筆 0050 到底有沒有成交，**用模擬帳的 API 查不出來**。逐項實測（都在 container 內跑）：

| API | 實測結果 | 為什麼不能當證據 |
|---|---|---|
| `get_transactions_by_date('2026-11-03','2026-11-03')` | **0 筆** | 那天我們確定買了 2603／2609／2408／2615，卻也是 0 筆 ⇒ **API 不保留歷史**，11/05 才查得到當天的 2615 賣出 |
| `get_order_results_by_date(11-03 / 11-04 / 11-05)` | **全部 0 筆** | 連當天已知成交的委託也查不到 ⇒ 模擬環境不提供委託查詢歷史 |
| `get_inventories()` | **只有 1 筆**（2615，`qty_s=2000`＝當日賣出未交割） | 我們確定持有的 2603／2609／2408 都不在 ⇒ 只回「當日有異動／未交割」的部位，**不能證明沒有 0050** |
| `get_balance()` | 全 0（`available_balance: 0`） | 模擬帳不追現金餘額 ⇒ 無法用現金反推有沒有扣款 |

**結論**：這批 0050 委託的最終狀態在模擬環境**不可回溯**（模擬資金，實質損失為零）。
⇒ 教訓：**對帳必須在資料還查得到的時候落地**。建議每天 13:45 把
`inventories`／`transactions`／`order_results` 原始回傳寫成 `logs/broker_snapshot_<date>.json`，
之後任何爭議都能用 `scripts/reconcile_broker_books.py --from-json` 重跑（該工具已支援這個模式）。

**判讀紀律**：模擬環境的「查不到」≠「沒發生」。真錢上線前，這個缺口必須先補（否則無法回答「券商到底有沒有那筆」）。

## 缺陷三：停泊的呼叫點**不可達**（2026-11-05 修，v1.1.24）

`park_idle_if_due()` 原本寫在 `main()` 主迴圈、**兩個「必定 `time.sleep(60); continue`」的分支之後**：

| 位置 | 條件 | 結果 |
|---|---|---|
| 交易日主區塊（`selfselect_trader.py:796`） | 08:45–13:30 | 跑完 → `continue` |
| 收盤報告區塊（`:1262`） | 13:31 以後 | 跑完 → `continue` |
| 停泊（舊位置，`:1307`） | 其餘時段 | **交易日永遠到不了** |

⇒ v1.1.22 之前停泊「看起來有作用」，其實是**收盤後**才下單（`close_order_window_open()` 當時沒有上限）：
那 4 筆 0050 是 13:30 之後的單，也正是 `000017` 的由來。
v1.1.22 補上窗口上限後，停泊就**完全不會執行**（實測 2026-11-05 13:25–13:30：idle 30.6 萬、
所有前置條件（immediate／0050／can_park=True／無冷卻）全成立，卻一筆都沒送）。
**修法**：把呼叫移到交易日主區塊內、`continue` 之前 → 13:25–13:30 正常執行、收盤後不送。
**不變式**：停泊呼叫點必須（a）只有一個、（b）在交易日主區塊內、（c）在該區塊 `continue` 之前
（`test/test_park_no_duplicate.py::TestParkCallIsReachable` 用 AST 釘住）。

## 缺陷四：停泊金額用「額度」而不是「現金」（2026-11-05 修，v1.1.24）

`idle_amount()` ＝ 腿額度 − 持股市值 − 停泊市值，那是**額度**：股票跌了額度會變大，但現金不會變多。
當天實例：腿額度 100 萬、持股市值 69.4 萬 ⇒ idle **30.6 萬**，但實際現金只有十幾萬
（11/03 買 98.6 萬、賣回 11.3 萬）⇒ 照 idle 停泊 3,000 股（約 29 萬）＝ **下單超過現金**，真錢就是交割違約。

**修法**：新增 `core.park_asset.cash_available()` ＝ 本金 − 持股成本（`logs/stock_allocation.json` 的
`ledger_cost`）− 已停泊成本，停泊金額取 `min(額度, 現金)`。**刻意保守**：賣出回款不加回，
因為模擬帳 `get_balance()` 一律回 0（見上一節），寧可少停泊也不要下單超過現金。
**真錢上線前**應改成向券商查可用餘額。

## 補救機制：每日券商原始快照（v1.1.25）

因為模擬環境不保留歷史，**證據必須當天落地**。`scripts/snapshot_broker.py`（唯讀）：

```bash
# 主程式會在交易日 13:45 收盤報告那一輪自動跑一次（同日已成功就跳過）
docker exec tw_selfselect_bot python scripts/snapshot_broker.py --date 2026-11-05   # 手動補跑
```

- 產出 `logs/broker_snapshot_<日期>.json`（`inventories`／`transactions`／`order_results`／`balance` 原始回傳
  ＋ `summary` ＋ `errors`），同日重跑會把上一次收進 `previous`（保留 5 份），**不覆蓋先前證據**。
- 另追加 `logs/broker_snapshot_history.jsonl`（每次執行一筆摘要，只追加）。
- 取不到 SDK ⇒ 離開碼 `2` 且**不寫檔**（不留假的空快照）。
- 事後重跑對帳：`python scripts/reconcile_broker_books.py --from-json logs/broker_snapshot_<日期>.json`
- 真錢上線前要改用券商**可用餘額**（`get_balance()` 在正式環境應有值；模擬環境一律 0，
  所以 `cash_available()` 目前用「本金 − 持股成本」保守估計）。

## 缺陷五：賣出「部分成交」沒有防護（2026-11-05 修，v1.1.26）

11/05 實例：2615 送出 **2 張（2,000 股）整股賣單**，券商成交回報只有 **1,000 股**
（`qty_s=2000`／`qty_sm=1000`／`1 筆 mat_dat 1000 股`），但帳本記成「賣出 2,000 股」⇒ `holdings.json` 變 0。
若那 1,000 股其實還在手上，明天同檔出現買訊就會**重複建倉**（再買一整個 25 萬部位）。

既有的校正關卡（`broker_holding_qty`）只覆蓋「下單逾時（unknown）的**買單**」；賣出方向沒有防護，
而 `resolve_fill()` 的契約在「查不到成交」時回 `None`，各呼叫端一律「視為全成交」⇒ 部分成交無從得知。

**修法（v1.1.26）**：交易日 13:45（快照之後）跑 `core.broker_sync.run_daily()`，比對
`performance.csv` 當日成交 vs 券商 `get_transactions_by_date`：

| 情況 | 處置 | 理由 |
|---|---|---|
| 賣出少成交 | **預設自動補回 holdings** | 保守方向；最壞只是少買一次 |
| 買進少成交 | **預設只告警**（`BROKER_SYNC_TRIM=1` 才減） | 減錯會造成重複建倉 |
| 券商回報沒有這筆 | 不動帳、只告警 | 模擬環境只回當日、「查不到」≠「沒發生」 |

稽核：`logs/broker_reconcile.jsonl`（每次一筆 plan/changed/errors）；有修正或差異都發 TG。
**不變式**：`core/broker_sync.py` 只修帳、**不得**呼叫 `place_order`／`cancel_order`（`test/test_broker_sync.py` 釘住）。

## 缺陷六：停泊「成功才有聲音」（2026-11-05 修，v1.1.27）

使用者問「沒看過停泊 0050 的通知，停泊的話 TG 會通知嗎？」——查證後發現三件事：

1. TG 只在**停泊成交那一刻**發（`selfselect_trader.py` 的買進／釋出），而停泊因前述缺陷從未真正成交。
2. **收盤／睡前報告完全沒有停泊欄位**，而且 `_build_holdings_message()` 在 `holdings.json` 空的時候直接
   `return None` ⇒ **錢全押在 0050 時整份報告不發**。
3. 「沒停泊」與「停泊失敗」幾乎全靜默（只有 print）⇒ 壞了四天沒人發現。

**修法（v1.1.27）**：把停泊變成「每天都有一句話」，並**區分「應該停泊」與「實際停泊」**：

```
🅿️ 停泊（閒置資金）
   0050 1,000 股 @ 均價 97.15（現價 98.00，市值 NT$98,000）
   應該停泊：額度 NT$305,689｜現金上限 NT$12,823 ⇒ 目標 NT$12,823（約 131 股 @ 97.15）
   實際停泊：**無**（可用現金 NT$12,823 不足）
   差額：少停泊 131 股（約 NT$12,728）
```

- 資料來源：每次嘗試由 `park_idle_if_due()` 落地 `logs/park_plan.json`（`idle`／`cash`／`cap`／`price`／
  `target_shares`／`actual_shares`／`status`／`reason`／`unknown`），報告與 TG 共用同一份。
- 收盤／睡前報告新增停泊區塊；**持股全清空但仍有停泊部位時仍會發報告**。
- 每天一則 `🅿️ 停泊狀態` TG（成功／失敗／沒做都有；以 `report_state['park_status']` 去重）。
- **不變式**：任何「應該做但沒做」的動作都要留下理由，否則故障會再次靜默（`test/test_park_report.py` 釘住）。

## 缺陷七：記帳股數用「計畫股數」而不是「券商實際送單股數」（2026-11-06 修，v1.1.34）

VM 實測（v1.1.33 上線首日 13:25，三行日誌連著看就露出來）：

```
↻  0050 4122 股餘數 <500，捨去為 4 張               ← 券商整股規則只送 4,000 股
✅ E.Sun 下單成功: 整股 buy 0050 4000 股 @ 92.55     ← 真正送出去 4,000 股
🅿️ 閒置資金停泊：買進 0050 4122 股 @ 92.55（NT$381,491）   ← 帳上記 4,122 股 ❌
```

券商快照（`logs/broker_snapshot_2026-11-06.json`）確認：`qty_b=4000`、`price_avg=92.55`、
`price_qty_sum=370200`、`fee=527`（實付 370,727）⇒ 帳面多記 **122 股／NT$11,291（3.05%）**。

### 根因

13:25 送整股單時 `resolve_fill()` 查不到成交（整股 13:30 才撮合）⇒ 回 `None` ⇒ 走「成交未確認，
先依送單股數記帳」分支；但這裡的「送單股數」不是真的送單股數——`data/esun_provider.place_order`
的整股規則會把數量四捨五入到「張」（餘數 ≥500 進位、<500 捨去）。2026-09-23 修過同一類 bug，
但只修在「策略訊號買進」那一條；稽核後共 **5 條路徑**有缺陷：

| # | 路徑 | 位置 |
|---|---|---|
| 1 | 停泊買進 | `selfselect_trader.py` `park_idle_if_due()` |
| 2 | 停泊釋出（賣） | `park_release_all()` |
| 3 | 買入補足（DCA／top-up） | 主迴圈補足區塊 |
| 4 | `keep_wait` 資金加碼 | 入金加碼區塊 |
| 5 | 孤兒清倉 | `core/live_utils.sell_with_fill_check()` |

### 修法與新不變式

- 五條路徑一律 `reconcile_order_qty(requested, order_ret)`（provider 回 `sent_qty` 就用它）；
  股數被改動時印 `⚠️ … 記帳股數依實際送單：X → Y 股`。
- **不變式（新增，改動時不可破壞）**：任何「成交查不到 ⇒ 先記帳」的分支，股數都必須先過
  `reconcile_order_qty()`；**賣出方向同樣適用**（賣 1,584 股可能只送 1,000 股）。
- 測試：`test/test_park_lot_bookkeeping.py`（11 支：事故數字語意、三個呼叫點 AST 守門、
  「不得退回計畫股數」、`sell_with_fill_check` 回傳對帳後股數、資金加碼守門）。

### 為什麼對帳沒抓到（盲點，尚未修）

停泊交易寫 `logs/park_trades.jsonl`，**不在** `performance.csv` ⇒ `scripts/reconcile_broker_books.py`
與 `scripts/broker_shortfall_repair.py` 都看不到停泊帳；當天「成交比對 1 筆」只比到 2609 的賣單。
⇒ 停泊股數目前**沒有任何自動對帳**，只能靠快照人工比對。

### 修帳陷阱：`logs/` 的狀態檔是 root 擁有的

容器以 root 身分（`python:3.11-slim`、無 `USER`、`WORKDIR /app`）寫入 bind mount `./logs` ⇒
主機使用者對這些檔案**只能讀**：`cat`／`cp` 會成功（`logs/` 目錄本身可寫，所以備份建得起來），
但 `open(path, 'w')` 直接 `PermissionError: [Errno 13]`（2026-11-06 實際踩到）。改這類檔案二選一：

```bash
# A. 用容器身分寫（root、CWD=/app）
docker exec -i tw_selfselect_bot python - <<'EOF'
... /app/logs/park_position.json ...
EOF

# B. 主機端「暫存檔 + os.replace」（靠目錄權限覆蓋，不需 sudo）
open(p + '.tmp', 'w').write(...); os.replace(p + '.tmp', p)
```

⚠️ `park_trades.jsonl` 也一樣：不能用 `>>` 追加（那會寫原檔），要走 B 的 read+append+replace 或 A。

### 本次修帳處置（2026-11-06）

依券商快照把 `logs/park_position.json` 由 4,122 股／381,491 元改為 **4,000 股／370,200 元**
（成本口徑＝股數 × 均價、**不含手續費**；實付 370,727 含手續費 527 屬現金流，不進停泊成本），
舊檔備份 `park_position.json.bak_parkfix_*`，並在 `park_trades.jsonl` 追加一筆 `REPAIR`（不靜默覆蓋）。

### 已補的防護：停泊帳納入每日對帳（v1.1.35）

`core/park_asset.check_position()` ＋ 收盤區塊（13:31+，每天一次 `report_state['park_recon']`）做三重比對：

| 比對 | 來源 | 抓什麼 |
|---|---|---|
| 帳本 × 稽核檔重播 | `park_position.json` vs `ΣBUY−ΣSELL`（`REPAIR` 視為覆寫絕對值） | **我們自己的帳壞了**（人工改過、寫檔中斷） |
| 帳本 × 券商庫存 | vs `broker_holding_qty()` | 成交當天就對不上（＝2026-11-06 這種） |
| 當日是否有停泊成交 | `park_trades.jsonl` 的 `ts` | 決定券商那一側可不可信 |

- `ledger_mismatch`／`broker_mismatch` → 發 TG 告警；`broker_unverified`（帳本≠券商但當日沒成交）→ **只寫 log**。
  理由：`get_inventories()` 只回「當日未交割」部位，長期持有的停泊可能整檔不出現，照它告警會天天誤報。
- **不變式**：這支只判定、**不改帳**（`test/test_park_reconcile.py` 用 `inspect.getsource` 釘住「不得寫檔」）。
- 回歸測試含事故劇本：帳本 4,122／券商 4,000／當日有成交 ⇒ 必須 `broker_mismatch`。


## 缺陷八：買單「整股進位」讓實付金額超過現金／額度上限（2026-11-09 修，v1.1.36）

VM 日誌（2026-11-09 13:25 停泊，四行連著看）：

```
🅿️ 停泊額度 213,152 受限於可用現金 152,360（額度≠現金）       ← 現金上限 152,360
↻  0050 2000 股餘數 ≥500，進位至 2 張                         ← 計畫 1,561 股被進位成 2,000 股
🅿️ 閒置資金停泊：買進 0050 2000 股 @ 97.60（NT$195,200）       ← 實付 195,200 ❌
⚠️ 停泊 0050 記帳股數依實際送單：1561 → 2000 股（差 -439 股）   ← 知道多買 439 股，卻沒擋
```

計畫 1,561 × 97.60 ＝ **NT$152,354**（貼齊上限，正確）；券商整股規則把 1,561 進位成 2,000 股
⇒ 實付 **NT$195,200**，**超支 NT$42,840（+439 股、+28%）**，還沒算手續費。
下一圈的 `停泊額度 19,980 受限於可用現金 0` 就是被這一筆吃乾的結果。

### 根因

同一條整股規則（餘數 ≥500 進位、<500 捨去）只寫在 `data/esun_provider.place_order()` 裡，
**上層 sizing 完全不知道**：

- `core/park_asset.park_shares()` 取整到「**股**」（`int(idle // price)`）；
- `data/esun_provider` 取整到「**張**」（四捨五入）⇒ **買進方向的進位就是多花錢**；
- `check_monthly_budget`／`check_stock_cap`／`cash_available()` 檢查的都是「計畫股數 × 價格」
  ⇒ 進位後的實付金額從來沒有被檢查過。

這是缺陷七的**鏡像**：缺陷七是「帳」（記帳股數），這裡是「**錢**」（實付金額）。
2026-11-05 的「額度≠現金」修正（缺陷四）刻意保守（賣出回款不加回），但保守前提在下游被進位打穿。

另外 `cash_available()` 用 `max(0.0, …)` 夾住負數 ⇒ 超支在日誌上只剩「可用現金 0」，**看不出已透支**。

### 修法（v1.1.36）

- 新增 `core/lots.py`：`board_lot_qty()`（規則本身，回傳「股」）、`fit_buy_qty()`（對齊後金額
  **不得超過上限**，超過降一張、不降成零股）、`sell_lot_qty()`（對齊後**不得超過持有**）。
- `data/esun_provider.place_order()` 改呼叫 `board_lot_qty()`，**不再自己寫第二份規則**；
  並修掉誤導的日誌——舊版印出的是進位**後**的股數（`2000 股餘數 ≥500`），原始 1,561 股完全看不到。
- 五條路徑送單前先對齊：**停泊買進**（`fit_buy_qty(n, px, idle)`）、**停泊釋出**（`sell_lot_qty(sh, sh)`）、
  **孤兒清倉**（`sell_lot_qty(old_shares, old_shares)`，2026-11-09 一併補上，缺陷七的第 5 條路徑）、
  **策略買進**（`fit_buy_qty(planned, px)`，所以 `check_monthly_budget`／`check_stock_cap` 看到的是實付金額）、
  **策略賣出**（`sell_lot_qty(planned, held)`——賣出方向的進位會送出**超過庫存**的委託，
  2026-11-05 實例：持有 1,000 股卻送 2 張 ⇒ 只成交 1,000 股）。
- **不變式（新增）**：任何買單在**檢查金額上限之前**必須先 `fit_buy_qty()`；任何賣單在送單前必須先
  `sell_lot_qty()` 且不得超過持有。對齊＝預防，`reconcile_order_qty()`＝事後校正，**兩者都要有**。
- 測試：`test/test_board_lot_guard.py`（18 支：規則表、1,561→1,000 事故回歸、
  「對齊後金額 ≤ 上限」性質測試、五條路徑的原始碼順序守門、provider 單一出處守門）。

### 行為改變（要知道）

- 買單可能因此**變小**：計畫 1,584 股 @45.45（NT$71,993）現在會送 1,000 股（NT$45,450），
  而不是進位成 2,000 股（NT$90,900）。這是刻意的——進位本來就超支了 26%。
- 停泊金額剛好卡在半張邊界時（例如上限只夠 1,561 股）會**少停泊約半張**（NT$48.8K 閒置），
  比超支好；停泊的目的是吃掉閒置額度，不是精準到股。
- 賣出清倉若持有非整張股數（例：1,584 股），現在會先賣 1,000 股、留 584 股走零股，
  而不是送一張會被退單／部分成交的 2,000 股委託。

## 缺陷九：買單只檢查「額度」不檢查「現金」（2026-11-09 修，v1.1.37）

**缺陷四**（2026-11-05 額度≠現金）的修法 `core.park_asset.cash_available()` **只接到停泊一條路徑**。
策略買進／資金加碼／買入補足比的是：

- `check_monthly_budget()`：當月這檔花掉多少 ≤ `monthly_budget`（額度）；
- `check_stock_cap()`：`total_buy_cost + cost ≤ get_stock_capital(symbol)`（`alloc × 本金`，也是額度）。

**兩個都不是現金。** 2026-11-09 的帳上實況就足以讓它爆：

| 時序 | 金額 |
|---|---|
| 停泊釋出 0050 4,000 股 @97.60 | +NT$390,400（估值） |
| 買 2609 4,000 股 @57.30 | −NT$229,200 |
| 停泊回買 0050 2,000 股 | −NT$195,200 ⇒ 模型現金 0（實際超支 NT$42,840，見缺陷八） |

如果同一天 2603 也給買訊，那筆 NT$250,000 的買單會**通過**額度檢查（該檔這月還沒花錢、離 `alloc` 上限還滿遠），
但帳戶現金是 0 ⇒ 交割風險（模擬環境只是帳面失真，切 real 就是違約）。

### 修法

`fit_cash(symbol, qty, px)`（`selfselect_trader.py`，`place_buy()` 旁）：

```
可用現金 ＝ cash_available(本金, Σ分帳本 total_buy_cost, already_parked_cost=0)
qty' ＝ fit_buy_qty(qty, px, 可用現金)      # 共用整股對齊，超過就降一張
```

三條買單路徑在 `place_buy()` **之前**一律先過它：策略訊號買進、`keep_wait` 資金加碼、買入補足。
被砍時印 `💰 … 買單受限於可用現金 NT$X：A → B 股（額度檢查已通過，但現金不夠交割）`。

### 兩個設計判斷（改動時要想清楚）

1. **停泊部位計入可動用**（`already_parked_cost=0.0`）：`place_buy()` 下單前一定先
   `ensure_park_released_for_buy()` 把它賣掉，所以停泊對買單是**準現金**。若照停泊那條的口徑把它扣掉，
   有停泊部位的日子會變成「明明有錢卻買不了」。
2. **停泊本身不用 `fit_cash`**：`park_idle_if_due()` 的 `idle` 已經是 `min(額度, 現金)`，再加一層會重複扣除。
3. **估算失敗不套用上限**：任何例外都 `return int(qty)`，寧可照原計畫送單——一個估價錯誤不該讓整排買單消失
   （`test/test_cash_cap_guard.py` 用原始碼守門釘住這條）。

### 已知限制

`cash_available()` 的口徑仍是「本金 − 持股成本」，**賣出回款不加回**（刻意保守）⇒ 賣出後騰出的額度
要等分帳本成本被調降才算得出來。真錢上線前應改成向券商查可用餘額（`get_balance()` 在正式環境應有值，
模擬環境回 0）。
