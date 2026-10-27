---
type: project_topic
status: active
summary: "模擬／真錢環境隔離、切 real 前的六項檢查清單、玉山庫存查詢與送單股數的單位陷阱，以及 docker 與 .env 的時序陷阱"
tags: [環境, 玉山, 實盤, 對帳, 事故]
contains: [背景, 當前結論, 實踐指南, 教訓, 開放問題]
created: "2026-10-26"
updated: "2026-10-26"
related: [total-assets-reconciliation.md]
authoring_mode: ai_generated
---
# 執行環境範圍與真錢上線

## 背景

本專案預設 `ESUN_ENVIRONMENT=simulation`（模擬帳戶）。「環境範圍」的核心規則是：**真錢上線前必須用券商庫存對帳**——這條規則早就寫在程式註解裡（`data/esun_provider.py`、`scripts/reconcile_broker_books.py`、`scripts/void_untracked_buys.py` 都指向本文件），但 repo 內長期沒有對應工具。

**2026-09-23 實盤事故**（缺這個工具的代價）：

```
↻ 2884 2000 股餘數 ≥500，進位至 2 張   ✅ 下單成功: 整股 buy 2884 2000 股   📝 記錄: BUY 2884 (1584 股)
↻ 5876 1461 股餘數 <500，捨去為 1 張   ✅ 下單成功: 整股 buy 5876 1000 股   📝 記錄: BUY 5876 (1461 股)
```

| 股票 | 券商 `qty_b` | 成交價 | 本機 `holdings.json` | 本機 CSV |
|---|---|---|---|---|
| 2884 玉山金 | **2000** | 45.45 | 1584 ❌ | 1584 ❌ |
| 5876 上海商銀 | **1000** | **49.90** | 1461 ❌ | 1461 @49.25 ❌ |
| 2881 富邦金 | 470 | 153.00 | 470 ✅ | 470 ✅ |

根因：券商端整股進位／捨去會**改動實際成交股數**，帳本若沿用「計畫股數」就必然與券商庫存不一致。程式面已修：送單回傳值帶 `sent_qty`／`sent_price`，上層必須用 `core/live_utils.reconcile_order_qty()` 讀它，不要用計畫股數。

## 當前結論

1. **環境是資料隔離，不只是旗標**：模擬帳的持股不能帶進真錢帳戶。切 `real` 當天必須清空 `logs/` 狀態檔（`holdings.json`、`stock_allocation.json`、`performance.csv`、`last_trade_times.json`、`daily_trades.json`），否則會拿模擬帳持股對真錢帳戶下單——**會賣出不存在的股票**。`scripts/reset_paper_trading_vm.py` 可協助（本機執行：自動停 bot → 一次性容器執行 → 重建／起回 bot；`--clear-portfolio` 會把 VM `.env` 的 `PC_*` 全部註解），但仍需人工確認。
2. **`.env` 一律以檔案為準**（`load_dotenv(override=True)`）。原因（2026-10-01 實測）：docker-compose 的 `env_file` 在**建立容器時**把變數注入 process env，之後在主機改 `.env` 不會更新既有的 process env；而 python-dotenv 預設 `override=False` ⇒ 用 `docker exec` 跑的工具（picker／selector／報表…）會讀到**容器啟動當時**的舊值。主程式 `live_trader_multi.py` 也是 `override=True`（V4.36 熱重載），必須一致。

   本專案的三層補救（缺一就會出現「改了 `.env` 卻沒生效」）：① `docker-compose.yml` 同時宣告 `env_file: .env` **與** bind mount `./.env:/app/.env:rw`（容器內看得到檔案）；② 啟動時 `load_dotenv(override=True)` 讓檔案勝過 `env_file` 注入的舊值；③ `env_fingerprint()` 指紋比對，主迴圈與**休眠期間**都會偵測檔案變更並中斷休眠立刻套用（V4.36／V4.38）。

   ⚠️ 驗證時別只看 `docker exec printenv`——那是 `env_file` 在**建立容器當下**的值，不等於 bot 實際在用的值。要看的是 `/app/.env` 與 `printenv` 兩者是否一致、以及 log 有沒有 `📥 偵測到 .env 內容變更`。

   （V4.38 修的坑：`_env_fp_seen` 原本寫在 `while True:` 裡面，每圈被重新初始化 ⇒ 比對永遠 False ⇒ 即時生效從來沒觸發過。狀態必須活在迴圈外。）
3. **玉山庫存查詢有單位陷阱**（`data/esun_provider.py:query_inventories`，2026-09-23 實測）：
   - 整股列（`ap_code` 為空）：`qty_b`／`cost_sum` 是「股／元」（2884 → `qty_b=2000`、`price_avg=45.45`、`cost_sum=-91029`）。
   - 盤中零股列（`ap_code='5'`）：`stk_dats` 是**以 1 股為單位**（2881 → `qty=1`、`pay_n=-154`），總股數要看 `qty_b`（470）。
   - ⇒ **取股數一律用 `qty_b`**，不要拿 `stk_dats[].qty` 當總數。

## 實踐指南

切 `real` 前的六項檢查（`使用手冊.md` §8，每一項都要做過）：

1. **券商庫存對帳**：`scripts/reconcile_broker_books.py` 與 `logs/holdings.json` 一致。⚠️ 不在 `holdings.json` 的部位**永遠不會被賣出**。
2. **手續費率**：`.env` 改成你帳戶實際折數（預設牌告 `0.001425`，比實際折扣保守）。
3. **憑證與密碼**：`ESUN_CERT_PATH`／`ESUN_CERT_PASSWORD`／`ESUN_ACCOUNT_PASSWORD` 就位；headless 建議 keyring（`PYTHON_KEYRING_BACKEND=…`），否則登入卡在互動輸入。
4. **資金口徑**：`TOTAL_CAPITAL`、`capital.txt`、券商實際可用餘額三者一致。
5. **清空 `logs/` 狀態檔**（見上）。
6. **小額試跑**：1 檔、小額 `alloc`，觀察一整週。

工具執行環境限制：對帳工具**必須在實盤機的 container 內跑**（需要玉山 SDK 與憑證），例如 `docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py`。

## 教訓

- **規則寫在註解裡等於沒寫**：「真錢上線前必須用券商庫存對帳」被引用 3 次、卻 6 個月沒有工具，事故照樣發生。規則要配可執行的檢查。
- **「送出 2000 股」不等於「成交 2000 股」**：整股進位／捨去是券商端行為，帳本只能信回報值。
- **容器環境變數有時間差**：`docker exec` 進去的工具與主程式看到的 `.env` 可能不是同一份。
- **同一個回傳欄位可能有兩種單位**：混用會讓對帳永遠對不平，且症狀看起來像「券商資料錯」。

## 開放問題

1. 切 `real` 的狀態檔清空目前靠人工確認 + 腳本輔助，要不要在啟動時加一道「偵測到 `ESUN_ENVIRONMENT` 變更但 `logs/` 非空 ⇒ 拒絕啟動」的硬閘門？
2. `reset_paper_trading_vm.py` 的 `--clear-portfolio` 會註解 VM `.env` 的 `PC_*`；註解後的復原流程（重新選股注入）尚未寫成 runbook。
