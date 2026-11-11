"""TW SelfSelect Trader 版本（單一來源，所有模組共用）

## 版號規則（2026-10-29 使用者裁定，**這是硬規則**）

1. **只要程式有修改，版號就要 +1**（`1.1.0` → `1.1.1` → `1.1.2`…），文件-only 的修改不必動版號。
2. **大升版（跳到 `1.2.0` / `2.0.0` 這種）由使用者主動通知**，不要自己決定。
3. 版號會出現在：啟動 banner、Telegram 啟動／收盤訊息、儀表板標題 ⇒ 換版後 VM 上一眼就能確認跑的是哪一版。
4. `deploy_source.sh` 一律**由使用者手動執行**，任何自動化流程（含 AI agent）不得代跑部署。

## 版本沿革

> **線上部署狀態（2026-11-11 21:10）**：VM `tw_selfselect_bot` 目前跑 **v1.1.39**（banner
> `build 2026-11-09 15:53:51／指紋 fd16a4fd`，與本機 `build_info()` 逐位一致）。**v1.1.40 尚未部署**
> （現金上限 `fit_cash()`），`deploy_source.sh` 由使用者手動執行；部署後 banner 的建置時間／指紋會一併變動，
> 可據此確認換版成功。

- `1.0.0`（2026-08）由 tw-autotrader v4.54 的自選股腿拆出後重新起版。
- `1.1.0`（2026-10-29）AI 選股模式（`SELFSELECT_AI`，D1 手動／逾期 fallback）＋ zscore 評分器（`SELFSELECT_SCORING_MODEL`，預設）
  ＋ 選股口徑 preset（`SELFSELECT_PRESET`，預設 `revenue`：池 100＋營收因子）＋實盤與回測逐位一致的驗證；
  同批把宇宙補回 62 檔已下市個股、PER 補到 672/672、月營收補到 645/672。
- 2026-10-30 更正：`1.1.4`～`1.1.8` 五個版號是為**教材變更**（`plans/ppt` W7 講稿版、解說腳本、mp4）誤升的，
  依使用者裁定「**非程式本身的變更不要動版號**」**撤回**，程式版本回到 `1.1.3`。
  教材／文件／`.env`／cache／報告 JSON 的變更一律不升版號；只有 `core/`、`scripts/`、`strategies/`、`data/`、`utils/`、
  `selfselect_trader.py` 這類執行期程式的修改才 +1。
- `1.1.40`（2026-11-09）**停泊損益與合計口徑進報告**。
  背景（VM 原文，2026-11-11 收盤）：報告寫「未實現損益 −26,620」，但那是**只有持股**；
  停泊 0050（成本 195,200、現價 103.20、市值 206,400）自己有 **+11,200（+5.74%）**，
  合計其實是 **−15,420**。停泊佔資產 20% 卻沒有自己的損益數字，看報告的人得自己按計算機。
  做法：① `core/park_asset.format_position()` 在「現價/市值」後接上「損益 +11,200（+5.74%）」
  （放在外層括號之後，避免嵌套括號；持倉報告與每日停泊狀態 TG 共用同一行）；
  ② 持倉報告尾端新增合計區塊：
  `總資產(持股+停泊): NT$1,027,420` / `合計未實現損益: -15,420（持股 -26,620｜停泊 +11,200）`
  （沒有停泊部位、或取不到停泊報價時不印，避免噪音與半截數字）。
  口徑提醒：這是**新的 D 口徑**（人眼總覽用）；`core/drawdown_guard.compute_equity()` 的 A 口徑
  與 B／C 都**不含停泊**（停泊交易不進 `performance.csv`，`compute_equity` 把停泊成本視為現金）
  ⇒ D 與 A/B/C 的差額就是停泊未實現損益。已寫進 `cairn/total-assets-reconciliation.md`。
  測試：`test_park_asset.py`（損益字串、虧損方向、禁止嵌套括號）、
  `test_telegram_markdown_escape.py`（停泊行損益、合計兩行、整則仍需通過 `md_ok`）。
- `1.1.39`（2026-11-09）**通知顯示修正**（v1.1.38 轉義後才看得出來的問題）。
  實測 Telegram 原文：`📈 監控中: 2408auto, 2615auto…`（方括號不見了）、停泊區塊
  `目標 NT$0（不足最低門檻 … 或取不到報價 @ 97.45）`（報價明明有）、`實際停泊：**無**`（星號直接露出來）。
  三件事：
  ① **方括號會被 legacy Markdown 吃掉**（`[auto]` 是連結語法）⇒ 啟動清單改用括號 `2408(auto)`；
  ② `format_plan_vs_actual()`：現金上限為 **0** 時也要印（舊版 `if cash:` 把它藏起來，只剩
     「額度 19,980 ⇒ 目標 0」要人猜）；目標 0 的原因改成依序判斷「取不到報價／低於門檻／現金已用盡／
     算不出張數」；`**無**`／`**送單未成交**` 改成 legacy 合法的 `*無*`（`**` 是 MarkdownV2，會顯示字面星號）；
     失敗原因在**這裡**轉義（`escape_md`），`*粗體*` 保留 ⇒ 呼叫端不再整行轉義（否則 `\*無\*`）。
  ③ 持倉報告：停泊代號也納入報價抓取（`0050 2,000 股 @ 均價 97.60（現價 97.45，市值 NT$194,900）`）；
     「現有資本(可買股)」在有停泊部位時註明「（含停泊部位賣出後可動用）」——它與停泊區塊的
     「可用金額」是兩個不同問題（一個是買股前會先賣停泊、一個是不能把錢再押進停泊）。
  測試：`test_telegram_markdown_escape.py` 22 支（新增：停泊行有現價/市值、現金上限 0 可見、
  `*無*` 未被二次轉義、可買股註記、啟動清單不得用方括號）；`test_park_asset.py` 新增
  「現金上限 0 要印」「目標 0 的原因要說對」「原因要轉義」三支。
- `1.1.38`（2026-11-09）**Telegram legacy Markdown 動態內容轉義**——治好「Markdown 降級為純文字」。
  背景：`send_telegram_message()` 優先送 `parse_mode="Markdown"`，訊息裡只要有一個**落單**的
  `_`／`*`／`` ` ``／`[`，Telegram 就回 400 `can't parse entities` ⇒ 降級純文字，使用者看到的是
  「格式掉了」。本專案的策略名稱就是底線（`keep_wait`／`ma_cross`），加上券商狀態 `broker_mismatch`、
  對帳 `note`、例外字串、指令 `reconcile_broker_books.py` ⇒ **每天至少一則**（`啟動持倉報告` 是常客）。
  做法：① `utils/telegram.escape_md()` 轉義**動態內容**（訊息本身的 `*粗體*` 留在外面）；
  ② 靜態字面裡的底線直接寫 `keep\_wait`（raw f-string）；③ 全庫五個發送面的動態值都套上——
  `selfselect_trader`（17 處：啟動清單、停泊、風險、對帳、未知訂單…）、`core/live_notifications`
  （持倉報告的策略標籤／停泊行／日報明細）、`core/live_capital`、`utils/telegram.send_trade_alert`、
  `data/esun_provider`（維護中告警，該處沒有降級重送 ⇒ 壞了就整則發不出去）。
  ④ `md_ok()` 送出前粗檢標記是否成對，不成對就**直接發純文字並印出肇因**（省一次 400 往返，
  也讓「哪一則壞了」有名字）。
  測試：`test/test_telegram_markdown_escape.py`（16 支：escape 規則、md_ok、送出閘門、
  `keep_wait`／`auto→ma_cross` 的持倉報告必須通過、五個發送面的原始碼守門）。
- `1.1.37`（2026-11-09）**買單加上「現金」上限（`fit_cash()`）**——補完「額度≠現金」。
  背景：2026-11-05 的缺陷四修法（`core.park_asset.cash_available()`）**只接到停泊一條路徑**；
  策略買進／資金加碼／買入補足比的是 `check_monthly_budget`（月度預算）與 `check_stock_cap`
  （單檔 `alloc × 本金`）——**兩者都是額度**。2026-11-09 當天就出現實例：停泊釋出 0050（約 NT$390,400）
  → 買 2609（NT$229,200）→ 現金見底；若同一天 2603 也給買訊，那筆 NT$250,000 的買單照樣會過額度檢查，
  卻沒有現金交割。
  做法：新增 `fit_cash(symbol, qty, px)`（`place_buy()` 旁邊），可用現金 ＝ 本金 − 分帳本持股成本，
  **停泊部位計入可動用**（`place_buy()` 下單前一定先賣掉它；`already_parked_cost=0.0`），
  再由共用的 `fit_buy_qty()` 依整股規則對齊並降張。三條買單路徑（策略／加碼／補足）在 `place_buy()` 之前一律先過它；
  被砍時印 `💰 … 買單受限於可用現金`。**估算失敗時不套用上限**（寧可照原計畫，也不要因一個估價例外讓整排買單消失）。
  停泊本身不用它（停泊的現金上限已經是 `min(額度, 現金)`）。
  測試：`test/test_cash_cap_guard.py`（9 支：現金 0 全擋、當天 1,561→1,000、4 檔 × 25 萬額度但本金 50 萬
  ⇒ 第 3 檔被現金擋下、三條路徑的下單前順序守門、「估算失敗不得回 0」守門）。
- `1.1.36`（2026-11-09）**整股（board lot）規則收斂成單一出處 `core/lots.py`，買賣單送單前一律先對齊**。
  背景（VM 事故，2026-11-09 13:25 停泊）：現金上限 NT$152,360、0050 @97.60 ⇒ 計畫 1,561 股（NT$152,354，貼齊上限），
  券商的整股規則是「餘數 ≥500 進位」⇒ 實際送出 2,000 股、實付 **NT$195,200，超支 NT$42,840（+28%）**；
  日誌只印了「記帳股數依實際送單：1561 → 2000（差 -439 股）」，沒有任何東西擋下來。
  根因：同一條規則原本只寫在 `data/esun_provider.place_order()` 裡，上層 sizing 完全不知道 ⇒
  買進方向的「進位」＝多花錢，`core/park_asset.cash_available()` 刻意保守（賣出回款不加回）的前提被打穿。
  做法：新增 `core/lots.py`（`board_lot_qty()` 規則本身、`fit_buy_qty()` 對齊後金額不得超過上限、
  `sell_lot_qty()` 對齊後不得超過持有），provider 改呼叫它（並印出**原始**股數，舊版印進位後的數字會誤導）；
  停泊買進／停泊釋出／策略買進／策略賣出／孤兒清倉五條路徑都先對齊，`check_monthly_budget`／`check_stock_cap`
  因此看到的是真正會花掉的金額。這是 2026-11-06 那次（記「帳」：`reconcile_order_qty`）的鏡像——
  那次修帳本，這次修錢；兩者互補（對齊＝預防、reconcile＝事後校正）。
  測試：`test/test_board_lot_guard.py`（18 支，含 1,561→1,000 事故回歸、「五條路徑對齊順序」與
  「provider 不得再自己實作一份規則」守門）。
- `1.1.35`（2026-11-06）**停泊帳納入每日對帳**（`core/park_asset.check_position()` ＋ 收盤區塊）。
  背景：1.1.34 修掉了「記帳股數用計畫值」的 5 條路徑，但那筆 122 股幻影之所以能存在，
  根因是**停泊帳完全沒有自動對帳**——停泊交易寫 `logs/park_trades.jsonl`、不在 `performance.csv`
  ⇒ `reconcile_broker_books`／`broker_shortfall_repair` 都看不到它。
  做法：收盤後做三重比對（**帳本** `park_position.json` × **稽核檔重播** `ΣBUY−ΣSELL`，`REPAIR` 視為覆寫 ×
  **券商庫存** `broker_holding_qty()`），四種判定 `ok`／`ledger_mismatch`（帳本≠重播＝我們自己的帳壞了）／
  `broker_mismatch`（帳本≠券商且**當日有停泊成交**）／`broker_unverified`（帳本≠券商但當日沒成交）。
  **只告警不改帳**：`ledger_mismatch`／`broker_mismatch` 發 TG，`broker_unverified` 只寫 log——
  因為 `get_inventories()` 只回「當日未交割」部位，長期持有的停泊可能整檔不出現，照它告警會天天誤報。
  每天一次（`report_state['park_recon']`）。測試：`test/test_park_reconcile.py`（17 支，含事故回歸
  「帳本 4,122／券商 4,000／當日有成交 ⇒ 必須告警」與「check_position 不得寫檔」守門）。
- `1.1.34`（2026-11-06）**記帳股數一律以「券商實際送單股數」為準**（`reconcile_order_qty`）——把 2026-09-23 只修在
  「策略訊號買進」那一條的修正，補到**其餘四條**路徑（實盤事故：停泊 0050 計畫 4,122 股、券商整股捨去只送 4,000 股，
  帳上卻記 4,122 股／NT$381,491 vs 實際 NT$370,200 ⇒ 多記 122 股、停泊市值與總權益虛胖 3.05%，
  下次釋出的「估算可動用現金」也跟著偏；`logs/park_asset.json`／`park_trades.jsonl`／TG／儀表板全部沿用錯的股數）：
  ① `park_idle_if_due()` 停泊買進 ② `park_release_all()` 停泊釋出 ③ 買入補足（DCA／top-up）
  ④ `keep_wait` 資金加碼 ⑤ `core/live_utils.sell_with_fill_check()`（孤兒清倉；賣單同樣會被整股規則捨去／進位）。
  股數被改動時一律印出「記帳股數依實際送單：X → Y 股」（先前只能靠對帳才發現；停泊帳**不在** `performance.csv`
  ⇒ `reconcile_broker_books`／`broker_shortfall_repair` 都看不到它）。
  測試：`test/test_park_lot_bookkeeping.py`（11 支：事故數字語意、三個呼叫點的 AST 守門、「不得退回計畫股數」、
  `sell_with_fill_check` 回傳對帳後股數）；`test/test_order_unknown_recovery.py` 的原始碼守門同步更新。
- `1.1.33`（2026-11-05）**ATR 口徑統一**（`strategies/indicators.py` 新增；`ma_cross`／`breakout` 共用）。
  `breakout` 的 TR 原本寫 `max(high−low, |high−close|, |low−close|)`——因收盤恆在 `[low, high]` 內，
  後兩項永遠輸給 `high−low` ⇒ 退化為「當日振幅」、**跳空不算**（ATR 低估 3%~35%）；而 `ma_cross` 另一份是含前收的正確式。
  現統一走 `indicators.true_range()`（含 `prev_close`，首根 `high−low`）＋ `indicators.atr()`
  （**Wilder 平滑** α=1/14、以前 14 根平均起種）＝TA-Lib `TA_ATR`／TradingView `ta.atr(14)` 口徑。
  兩支的舊實作都用 `rolling().mean()`（簡單移動平均），一併改掉。
  行為差異（60 檔 × 近 500 根日 K 實測）：`breakout` 買訊 1359→1371、賣訊 1856→1851（逐日不同 333 根／30000）；
  `ma_cross` 買訊 860→815、賣訊 855→831（逐日不同 71 根）。ATR 前 13 根為 NaN（不發訊號；實盤取 260 天、回測快取有前置歷史）。
  測試：`test/test_atr_caliber.py`（14 支，含「退化式不得復活」與「兩支必須拿到同一份 ATR」守門）。
  文件：`策略說明.md` §5.3／§5.4／附錄 E 已同步更正；教材（`plans/ppt` 的 pptx／mp4／解說腳本）仍寫舊口徑，待重出時一起改。
- `1.1.32`（2026-11-05）新增 **`scripts/broker_shortfall_repair.py`**：用**當天落地的券商快照**補「部分成交」的帳。
  情境：2615 送出 2,000 股賣單、券商只成交 1,000 股，帳本記成「賣 2,000、2615 = 0 股」；
  `core/broker_sync` 是為「當天發現」設計的，而模擬環境查不到歷史 ⇒ 隔天只能靠快照救。
  三本帳一起修：`performance.csv`（該日該代號該方向的 `quantity` 改成券商實際成交、`cost` 改券商實收 fee+tax）、
  `holdings.json` 與 `stock_allocation.json`（用修正後的 CSV 重算 FIFO 未平倉，只動有落差的代號）。
  安全設計：**預設 dry-run**；`--apply` 才寫且先備份（`*.bak_shortfall_<ts>`）；賣出少成交才自動修（保守方向）、
  買進少成交要 `--allow-trim`；券商回報沒有的代號一律不動；只減不增（帳本少於券商只警告）；可重複執行。
  稽核 `logs/broker_shortfall_repair.jsonl`。規則函式在 `core/broker_sync.partial_fill_plan()`／`rewrite_csv_text()`。
  測試：`test/test_broker_shortfall_repair.py`（12 支）。
- `1.1.31`（2026-11-05）券商快照補上**未交割明細**：`data/esun_provider.query_settlements()` ＋
  `scripts/snapshot_broker.py` 的 `settlements`（摘要含筆數與交割日）。
  動機：11/05 補查發現 `get_settlements()` 只回「還沒交割」的義務（例：11/05 賣出、11/09 交割 113,496），
  **交割日一到就消失** ⇒ 不每天落地就查不到，現金流也無從回溯（`get_balance` 在模擬帳全 0）。
  測試：`test/test_snapshot_broker.py` 增 4 支（含 provider helper／SDK fallback／單項失敗不讓整份快照失敗）。
- `1.1.30`（2026-11-05）對帳工具 `scripts/reconcile_broker_books.py` 的輸出補上 **`broker_symbols`（含 0 股列）**，
  文字版也印「券商回傳：2615(0 股)」。
  動機（當天實測踩到）：2615 賣掉後券商端已無未交割部位 ⇒ `--json` 的 `rows`／`consistent` 都空，
  只剩一句「券商回傳只有 1 檔」，**看不出是哪一檔、股數多少**（`consistent` 的語義是「股數 > 0 且一致」，
  0 股列不會進去）。另加一條 note「…股數為 0（＝當日已無未交割部位；不代表沒有更早的舊部位）」，
  避免 0 股被讀成「券商很乾淨」。
  測試：`test/test_broker_reconcile.py` 增 4 支（build_report 的 mapping／0 股 note／無資料／JSON＋文字輸出）。
  只改報告內容，不動下單、帳務與對帳判定（`ok` 語義不變）。
- `1.1.29`（2026-11-05）**結果檔名帶上 `strat_mode`**：`group`（輪替口徑）加 `_group`、`form`（實盤口徑）維持不加註。
  事故：比較「輪替 vs 實盤」時，兩者跑同一窗口寫出**同一個** `results/*.json`（以及 `daily_*`／`exposure_*.csv`），
  後跑的把先跑的蓋掉（當天靠「跑一組先複製到 `TMP/`」才救回；沒發現就會拿 A 組的曲線解釋 B 組的數字）。
  檔名後綴原本只記 exec／鎖定時點／停泊／評分／池大小等，漏了最會改變結果的 `STRAT_MODE`。
  規則抽成 `core.backtest_rules.caliber_tag()`（純函式，JSON 與 CSV 兩處輸出共用），
  測試：新增 `test/test_backtest_caliber_tag.py`（9 支：form 不加註、group 加 `_group`、順序、基準值不加註、
  兩者永不撞名、腳本共用同一份規則）。實盤行為不變；既有（form）檔名與文件引用不變，舊的 group 結果檔仍可讀。
  ⚠️ `results/` 不進版控；要重跑才知道哪個舊檔是哪個口徑。
- `1.1.28`（2026-11-05）回測結果 `results/*.json` 的**檔頭補上選股口徑旋鈕**：`preset`／`z_overheat`／
  `imm_overheat`／`entry_overheat`／`oh_rsi_th`／`oh_dist_win`／`oh_dist_th`／`oh_entry_mode`／
  `pick_cooldown_months`／`prerank_r63_pct`／`w_dist`／`nonmom_slots`。
  動機（當天實測踩到）：要回答「現行預設口徑 vs 輪替四策略，選股差多少」時，檔頭沒有 `Z_OVERHEAT`／
  `IMM_OVERHEAT`／`ENTRY_OVERHEAT`／`preset`（正好是最會改變名單的開關）⇒ 兩份 JSON 看起來同口徑、
  實際可能差一整組名單，只能重跑一組控制變因的實驗才敢下結論（結果：58 個選股日 57 天名單逐位相同，
  唯一差異是 2022-11 的回撤防護，那是出場結果回饋到權益曲線才產生的）。
  測試：新增 `test/test_backtest_json_caliber_knobs.py`（5 支，`ast` 解析 `out = {...}`，不 import 腳本）。
  純研究工具變更，實盤行為不變；舊的 `results/` 檔仍是舊格式（不進版控，重跑即可）。
- `1.1.27`（2026-11-05）讓**停泊看得見**（使用者：「沒看過停泊通知／要能區分應該停泊與實際停泊」）：
  ① `logs/park_plan.json` 落地每次停泊尝试的**應該停泊**（額度、現金上限、目標股數）與**實際停泊**
  （買進／送單未成交／無＋原因）；② 收盤／睡前持倉報告新增 `🅿️ 停泊（閒置資金）` 區塊（部位＋應該/實際＋差額）；
  ③ 每天一則 `🅿️ 停泊狀態` TG（成功／失敗／沒做都有，含原因）；④ **持股全清空但仍有停泊部位時仍要發報告**
  （原本 `_build_holdings_message` 會 `return None` ⇒ 錢全押在 0050 時整份報告不發）。
  純格式化 `core.park_asset.format_position()`／`skip_reason()`／`format_plan_vs_actual()`。
  測試：新增 `test/test_park_report.py`（8 支）＋`test_park_asset.py` 增 15 支 ⇒ 全套 **937 passed**。
  ~~⚠️ 線上仍是 1.1.25（`a28b9882`）；1.1.26／1.1.27 都待部署~~ → **2026-11-05 18:29 已隨 1.1.29 一次上線**。
- `1.1.26`（2026-11-05）新增 **收盤「券商成交 vs 帳本」對帳** `core/broker_sync.py`（只修帳、不下單）：
  11/05 的 2615 送出 **2 張整股賣單**、券商成交回報只有 **1,000 股**（`qty_s=2000`／`qty_sm=1000`），
  帳本卻記成全部賣出（`resolve_fill()` 在 13:27 查不到成交時走「查不到＝全成交」）⇒ 若那 1,000 股還在手上，
  明天同檔出現買訊就會**重複建倉**。既有校正只覆蓋「下單逾時的買單」，賣出部分成交沒有防護。
  ⇒ 交易日 13:45（快照之後）比對 `performance.csv` 當日成交 vs 券商 `get_transactions_by_date`，
  **方向刻意不對稱**：賣出少成交 ⇒ 預設自動補回 holdings（保守方向）；買進少成交 ⇒ 預設只告警
  （`BROKER_SYNC_TRIM=1` 才真的減）；券商回報裡完全沒有 ⇒ 不動帳（模擬環境只回當日、可能缺漏）。
  稽核寫 `logs/broker_reconcile.jsonl`，有修正或差異都發 TG。測試 `test/test_broker_sync.py`（23 支）⇒ 全套 **917 passed**。
  ~~⚠️ 線上仍是 1.1.25；本版需再部署一次~~ → **2026-11-05 18:29 已上線**。真錢上線前仍應以券商 `qty_b` 為主並人工確認。
- `1.1.25`（2026-11-05）新增 **每日券商原始快照** `scripts/snapshot_broker.py`（唯讀）＋主程式整合：
  交易日 13:45 收盤報告那一輪把 `inventories`／`transactions`／`order_results`／`balance` 的**原始回傳**
  落地成 `logs/broker_snapshot_<日期>.json`，並在 `logs/broker_snapshot_history.jsonl` 追加一筆摘要。
  動機＝當天要查「11/03 的 4 筆 0050 成交幾筆」時發現**模擬環境的查詢 API 不保留歷史**
  （`get_transactions_by_date` 對 11/03 回 0 筆、連當天確定成交的 4 檔都沒有；`get_order_results_by_date` 全空；
  `get_inventories` 只回當日未交割；`get_balance` 全 0）⇒ **「查不到」≠「沒發生」**，證據必須當天落地。
  設計：同一天重跑不覆蓋先前證據（收進 `previous`，最多 5 份）；取不到 SDK 回 2 且**不寫假快照**；
  之後可用 `scripts/reconcile_broker_books.py --from-json logs/broker_snapshot_<日期>.json` 重跑對帳。
  測試 `test/test_snapshot_broker.py`（20 支）。整套 894 passed。~~⚠️ 仍需部署一次（1.1.24／1.1.25 都還沒上線）~~ → **2026-11-05 18:29 已上線**。
- `1.1.24`（2026-11-05）修**停泊的兩個致命問題**（都比前兩版更根本）：
  ① **呼叫點不可達**——`park_idle_if_due()` 原本放在兩個「必定 `time.sleep(60); continue`」的分支之後
  （交易日 08:45–13:30 主區塊、13:31+ 收盤報告區塊）⇒ **交易日在結構上永遠執行不到停泊**。
  v1.1.22 之前之所以「看起來有作用」，是因為 `close_order_window_open()` 當時沒有上限、停泊其實是
  **收盤後（多半 14:00+）**才下單 ⇒ 那 4 筆 0050 是收盤後的單，也正是 `000017` 的來源；
  v1.1.22 補上上限後停泊就完全不會動（實測 2026-11-05 13:25–13:30：idle 30.6 萬、前置條件全成立、一筆沒送）。
  ⇒ 移到交易日主區塊內、下單窗口時呼叫（收盤後一律不送）。
  ② **停泊金額用「額度」而不是「現金」**——`idle_amount()`＝腿額度−持股市值−停泊市值，股票跌了額度會變大、
  現金不會。當天實例：idle 30.6 萬但現金只有十幾萬 ⇒ 照 idle 停泊 3,000 股（約 29 萬）會**下單超過現金**
  （真錢＝交割違約）。新增 `core.park_asset.cash_available()`（本金−持股成本−已停泊成本，**刻意保守**：
  賣出回款不加回，因為模擬帳 `get_balance()` 回 0）並以 `min(額度, 現金)` 封頂。
  測試：`test/test_park_no_duplicate.py` 增「呼叫點必須在交易日主區塊內且在 continue 之前」與「必須以現金封頂」；
  `test/test_park_asset.py` 增 `TestCashAvailable`（5 支）。全套 874 passed。
  ⚠️ v1.1.23 已部署（`2399935c`）；**本版需再部署一次**。真錢上線前應改為向券商查可用餘額。
- `1.1.23`（2026-11-05）補 **v1.1.22 的鏡像缺陷：停泊「釋出（賣出）」也把「成交查不到」當成 0**。
  `park_release_all()` 的 `int(filled or 0)` 在 `resolve_fill()` 回 `None` 時算出 0 股 ⇒
  `left = sh - 0` ⇒ 帳上仍留著已賣出的停泊股 ⇒ 下次買股前再賣一次（重複賣出／賣不存在的股數）或永遠卡住。
  改為 `None` 沿用「全部賣出」記帳，並在流水／Telegram 標註「成交未確認」。
  同一輪複查全部 `resolve_fill()` 呼叫點：另外 3 條（策略訊號／孤兒清倉／買入補足）本來就正確處理 `None`，
  只有停泊的買、賣兩條漏了。`test/test_park_no_duplicate.py` 增第 6 支（AST 同時守 buy／sell 兩條路徑）。
  ⚠️ v1.1.22 已於 2026-11-05 12:32 部署到 VM（banner `5e175f9c`）；**本版需再跑一次 `./deploy_source.sh`**。
- `1.1.22`（2026-11-04）修**兩個實盤下單缺陷**（VM 2026-11-03/04 事故：0050 282 股 @100.60 連 4 筆、
  13:45 出現 `000017: 非該盤別盤中或預約時間`）：
  ① **停泊重複下單**——`resolve_fill()` 回 `None`（＝成交查不到，不是沒成交）時，
  `park_idle_if_due()` 的 `int(filled or 0)` 當成 0 ⇒ 不記帳 ⇒ 停泊帳不變 ⇒ 下一圈（60 秒後）
  用同一個 idle 再買一次。改為 None 就沿用送單股數記帳（與 `resolve_fill` docstring 及其他 4 條買單路徑一致）。
  ② **5 分鐘冷卻失效**——`core.park_asset.load_state()` 漏回 `last_park_ts`，`st.get('last_park_ts')`
  永遠 None ⇒ 防護是死碼；補回該鍵，且送單失敗（含被券商退單）也寫時間戳，不再每圈重試。
  ③ **收盤後仍下單**——`close_order_window_open()` 只有下限 ⇒ 13:30 之後一整段都算「可下單」
  ⇒ 13:45 收盤報告那一輪照樣送單。改為 `[CLOSE_ORDER_FROM, CLOSE_ORDER_TO]`（預設 13:25–13:30），
  停泊送單前再檢查一次（避免迴圈 13:29 起算、送單時已過 13:30）。
  ④ `data/esun_provider`：`000017` 這類**時間／盤別錯不再強制重登重試**（重登不會改變現在幾點，
  VM 那對 ⚠️／❌ 就是這樣來的）；報價逾時重試改為次數＋退避可調（`NET_QUOTE_RETRIES`／`NET_QUOTE_BACKOFF_SEC`）。
  測試：新增 `test/test_park_no_duplicate.py`（5 支，AST 釘住「None≠0、失敗也記時間戳、送單前再檢查窗口」）、
  `test/test_park_asset.py` 補 `last_park_ts` roundtrip（4 支）、`test/test_esun_relogin_retry.py` 補 000017 不重登（3 支）、
  `test/test_close_window_timeout.py` 原「無上限」斷言**更正**為有上限。全套 865 passed。
  ⚠️ 需使用者手動 `./deploy_source.sh`；部署後 banner／Telegram 應顯示 **v1.1.22**。
- `1.1.21`（2026-11-03）**儀表板的策略動畫連結修好**（動畫頁已搬到 `docs/`，但連結還指向頁面根目錄）：
  `scripts/generate_dashboard.py` 的「🎬 策略動畫說明」五個連結改成 `{PAGES_BASE}/docs/<檔名>`
  （`PAGES_BASE` 預設 `https://dinchentech.github.io/tw-selfselect`，可用 `DASHBOARD_PAGES_BASE` 覆寫；
  中文檔名 `keep_wait策略說明.html` 走 `quote()` 編碼）。
  `scripts/vm/publish_dashboard.sh` 同步發佈靜態頁：從 **main 分支**取 `docs/*.html`（排除 `index.html`）
  寫進 gh-pages 的 `docs/` 再一起 commit——原本 gh-pages 只有 `index.html`＋`.nojekyll`，
  五個動畫連結在線上**全是 404**（2026-11-03 實測：`/docs/bollinger-animation.html` 也是 404）。
  ⚠️ 要重新部署（VM 換 image）＋跑一次發佈，線上才會生效。
- `1.1.20`（2026-11-03）**殘留的舊專案名稱清乾淨**（tw-autotrader → tw-selfselect；純字串，行為不變）：
  `backtest.py` 啟動 banner 與 argparse 說明（`📊 開始回測 TW SelfSelect`／`TW SelfSelect - Backtest Mode`）、
  `utils/telegram.py` 每則訊息開頭的機器人標頭（`🤖 TW SelfSelect`）、`core/config_loader.py` 檔頭與註解的
  `live_trader_multi.py` → `selfselect_trader.py`。同批教材 `python_basic/` 已全面改用本專案程式舉例。
  ⚠️ Telegram 舊訊息（部署前）仍帶舊標頭，切換是**從部署後的新訊息**開始。
- `1.1.19`（2026-11-03）**所有記帳路徑改用「實際送單價」**（對帳缺口）：
  `place_order()` 送單前會自己再取一次現價當限價，所以「上層的報價」與「券商收到的價」可能不同
  （2026-11-03 實測：孤兒清倉 6505 上層取到 99.9、實際送單 **99.60** ⇒ 帳本多記約 NT$600，
  `reconcile_broker_books.py` 會報「CSV 價 ≠ 券商價」）。策略訊號那條 2026-10-19 已改用
  `order_fill_price(order_result, px)`；這次把其餘記帳路徑接上：`sell_with_fill_check()` 多回傳
  `order_ret`（孤兒清倉用它取 `sent_price`）、`keep_wait` 加碼／買入補足／停泊釋出／停泊買進
  都經 `selfselect_trader.book_price(order_ret, 舊價, 標記)`（價格有變印 `📌`）。
  顯示同步改為兩位小數（原本 `:.0f` 會把 99.9 印成 100）。測試：`test/test_order_unknown_recovery.py` 補 4 支。
- `1.1.18`（2026-11-02）**所有買單統一走 `place_buy()`**（補上 top-up／資金加碼漏釋出停泊的缺口）：
  v1.1.17 只讓「策略訊號」那條買單先賣掉停泊部位；`mock` 路徑、資金加碼（`capital.txt`）、
  買入補足（`BUY_AMOUNT_OFFSET`）三條仍會「現金還押在 0050 就送單」⇒ 整筆失敗。
  現在 4 條路徑都經 `place_buy()`（先 `ensure_park_released_for_buy()` 再下單）；
  直接呼叫 `broker.place_order(...,'buy',...)` 只准出現在 `place_buy()` 與 `park_idle_if_due()`（買 0050＝停泊本身）。
  回歸測試新增 `test/test_place_buy_single_exit.py`（AST 掃描：3 支）。
- `1.1.17`（2026-11-02）**「選到但買不到」不再讓資金空轉**（停泊缺口）：
  買入被「過熱閘門」擋下或下單失敗時，那筆錢既不買股也不會去停泊 0050（`can_park_after_build`
  原本只認『已持有／已買過』）⇒ 資金閒置。改法：① 新增 `logs/entry_attempts.json`（`{代號: 日期}`），
  把『今天嘗試買但沒成交』記下來，`core.park_asset.is_build_attempted()` 只認**當天**的紀錄 ⇒ 停泊可接手；
  ② 被過熱閘門擋下時發**一次 Telegram**（每日每檔）——原本只印 log，沒看 log 的人不會知道沒買到；
  ③ 停泊釋出改成**下單前一刻才賣**（原本窗口一開始就全賣）：否則天天『賣 0050→沒買到→再停泊』
  會產生約 0.39%／次 的來回 churn。測試：`test/test_park_asset.py` 23 支（新增 4 支）。
- `1.1.16`（2026-11-02）**報價（`intraday/quote`）獨立的較短逾時＋逾時重試一次**：
  2026-11-02 09:00 開盤首圈實測 `api.fugle.tw` 第一筆報價 **30 秒無回應**（Read timed out）才被
  全域 `NET_TIMEOUT_SEC=30` 切掉。13:25–13:30 下單窗口是**逐檔串行**取價 ⇒ 一檔卡 30 秒等於吃掉窗口 1/10。
  改法：`selfselect_trader.request_timeout_for(url)` 依 URL 選逾時（新增 `NET_QUOTE_TIMEOUT_SEC`，預設 8 秒；
  其他呼叫仍 30 秒，且在呼叫當下讀 env ⇒ 熱重載立即生效），`EsunProvider.get_current_price` 對
  **逾時／連線錯誤**重試一次（其他錯誤不重試）。最壞一檔 8+8=16 秒，不會讓 `place_order` 外層多等。
- `1.1.15`（2026-10-31）**閒置資金停泊改為預設開啟、停泊 `0050`**（使用者裁定）：
  `.env` 不寫 `SELFSELECT_PARK_ASSET` ⇒ 停泊 0050；明確留空（`SELFSELECT_PARK_ASSET=`）⇒ 不停泊；填代號 ⇒ 停泊該檔。
  `core/park_asset.py::park_symbol()` 的語義由「未設定＝關閉」改為「未設定＝0050」，`enabled()` 同步；
  測試改為釘住三種情況（未設定＝0050／留空＝關閉／指定＝該檔）。行為邊界不變：只在 immediate 模式、
  名單建倉完成後、13:25–13:30 窗口內才動作，買股前先全部釋出。
  ⚠️ 部署後的第一個交易日，空手資金就會開始買 0050（多頭年 +25pp、空頭年放大回撤，見使用手冊 §3-0d）。
- `1.1.14`（2026-10-31）實作**實盤「閒置資金停泊」**（`SELFSELECT_PARK_ASSET`；**預設關閉**，
  使用者裁定：留空＝不停泊，填代號才啟用，慣例 0050）。規則：只在 `SELFSELECT_EXEC_MODE=immediate`、
  且**本月名單已建倉完成**後，把閒置資金買進該檔；要買股票前**先全部賣出**停泊部位。
  停泊部位記在獨立帳本 `logs/park_position.json` ＋ `logs/park_trades.jsonl`（稽核），**不進** holdings／分帳本
  ⇒ 不被 N=5 上限／已持倉保留／孤兒清倉影響。純函式 `core/park_asset.py`（`test/test_park_asset.py` 18 tests）。
  動機：回測主表有一半報酬來自停泊（停泊 +1445.2% vs 純現金 +656.9%）；代價是放大回撤（2022 −8.2% → −24.0%）。
- `1.1.13`（2026-10-31）**釐清「停泊 0050」的貢獻並修正對外說法**：回測主表數字含「閒置資金押 0050」
  （平均約 35–40% 的資金），而**實盤不會自動買 ETF**（空手期領 0%）。以預設 `revenue`、2016-04~2026-10 實測：
  停泊 +1445.2%／MDD −56.7%／夏普 1.17 → **純現金（＝實盤真實）＋656.9%／−52.8%／1.02**（差 788pp）；
  2022 起 +283.1% → **+161.1%**（差 122pp）。⇒ **實盤兩個窗口的總報酬與夏普都輸 0050**（+793.4%／1.17）。
  停泊是放大器不是穩定器（2024 +25.2pp、2023 +27.6pp，但 2022 −15.7pp）。
  `core/selection_presets.py` 的啟動警語改報「無停泊」的實盤量級；純文件＋警語文字變更，交易邏輯未動。
- `1.1.12`（2026-10-31）**預設選股口徑改回 `revenue`**（使用者裁定；`aggressive` 僅在 10-30～10-31 期間是預設）：
  池 100＋營收因子、無產業上限。實盤口徑（含 `Z_OVERHEAT`）2016-04~2026-10 **+1445.2%／年化 29.60%／MDD −56.7%／夏普 1.17**
  （`aggressive` +1306.9%／28.45%／−46.1%／1.11）；2022-01~2026-10 **+283.1%／32.23%／−33.4%／1.18**（0050 +231.4%／−28.31%…／1.21）。
  代價：**回撤 −56.7% 比 0050 深 22.7pp、夏普只打平**。`.env` 的 `SELFSELECT_POOL_N` 由 150 → **100**、
  `SELFSELECT_PRESET` 改 `revenue`；測試（default knobs 100/1/0、picker 池 100）同步。
- `1.1.11`（2026-10-31）**「選股端過熱過濾」接進 zscore 並設為預設**（使用者裁定；A 實驗）：
  回測 `Z_OVERHEAT` 與實盤 `SELFSELECT_Z_OVERHEAT`／`Z_OVERHEAT` 預設皆為 `1`，`pick_zscore()` 現在會呼叫 `is_overheated()`。
  實測（2016-04~2026-10、實盤口徑）：報酬 +1408.6% → **+1306.9%**（−102pp）、夏普 1.08 → **1.11**、MDD −45.6% → −46.1%
  （剔除 10.4% 名單）。⚠️ 同時發現：開啟後 **`revenue`（+1445.2%／夏普 1.17／MDD −56.7%）在報酬與夏普上都勝過預設 `aggressive`**，
  代價是回撤深 10.6pp —— 預設 preset 是否要換回 `revenue` 待使用者裁定。
  另修 `walk_forward.py` 快取鍵：改為包含**所有會改變結果的旋鈕生效值**（含程式碼預設），
  避免「預設值改了但快取檔名沒變」而沿用舊結果（本次實際踩到：A 設為預設後整套 WF 數字一模一樣）。
- `1.1.10`（2026-10-31）新增兩個「避免追高」的回測旋鈕（**預設全關，行為不變**）：
  `Z_OVERHEAT`（把選股端人工降溫——距 52 週高 ≤7%、YTD >100%、PER >45——接進 **zscore** 路徑；
  原本只有 legacy 路徑會用，文件寫了但程式沒接）與 `PICK_COOLDOWN_MONTHS=N`（前 N 個月曾入選就不再選）。
  實測（2016-04~2026-10、實盤口徑）：接上過濾 +1306.9%／MDD −46.1%／**夏普 1.11**（現況 1.08，報酬 −102pp）；
  冷卻 3 個月 **+415.7%／0.77（−993pp）**、冷卻 1 個月 +1190.5%、冷卻 6 個月 +586.9%（**非單調 ⇒ 路徑雜訊**）。
  ⇒ 「前 3 個月就該被選中＝最佳點已過」在 2016-2026 不成立。文件：`策略說明.md` §6.9、README 第四輪。
- `1.1.9`（2026-10-31）walk-forward 改成**實盤口徑**重跑（`STRAT_MODE=form`＋`IMM_OVERHEAT=1`，快取已分口徑）：
  OOS 逐年串接 **+416.6%** vs 0050 +206.4%（**3 勝 3 敗**，輸 2022/2024/2025），換算年化 +31.5%；
  六輪挑中**兩組**（`aggressive` 4 次、`pool150_rev` 2 次），訓練段領先第二名的夏普差距**最小只有 +0.01**
  ⇒ 比輪替口徑的結論更不利（原本「六輪都挑回同一組」）。`core/selection_presets.py` 的啟動警語同步更新。
- `1.1.8`（2026-10-31）**回測主表改用「實盤口徑」**（使用者裁定）：`STRAT_MODE=form`（＝實盤 `strategy:"auto"`
  型態路由）＋`IMM_OVERHEAT=1`（＝實盤買進前過熱閘門），2016-2025 為 **+926.5%／年化 26.23%／MDD −45.6%／夏普 1.01**
  （0050 +477.6%／−34.0%／1.06）；舊的輪替口徑 +1323.6%／1.15 降級為「上限參考」。
  同批修掉兩個會**默默算錯**的問題：
  ① 回測端 preset 優先序——`active_name()` 原本是 `SELFSELECT_PRESET` 優先，本機 `.env` 有 `SELFSELECT_PRESET=aggressive` 時
  `PRESET=current` 會被忽略並照跑 aggressive（實測跑 current 得到 +1323.6% 的 aggressive 結果）⇒ 回測端改為 `PRESET` 優先；
  ② `walk_forward.py` 快取不分口徑 ⇒ 換口徑重跑會沿用舊結果，現改為檔名帶 `{mode}_{imm}`。
  同步更新 `core/selection_presets.py` 的 preset 說明與啟動警語（改報實盤口徑，並寫明夏普全部輸 0050）。
- `1.1.7`（2026-10-31）新增**選股口徑實驗旋鈕**（回測端、預設全關 ⇒ 行為不變）：
  `IMM_OVERHEAT`（immediate 買進也套實盤的過熱閘門）、`PRERANK_R63_PCT`／`W_DIST`（降低追高）、
  `NONMOM_SLOTS`／`NONMOM_QUANTILE`／`NONMOM_REV_MIN`（低基期＋營收轉機名額）。
  純函式工具進 `core/scoring.py`（`prerank`／`nonmom_picks`／`pick_sleeves`），`test/test_scoring.py` 加 12 個測試。
  當批測出兩個重要事實：① 實測 600 筆選股 98% 站上 MA60／MA200、r63 中位 +31.5%，實盤 `auto` 路由有 84.8% 落到順勢策略；
  ② 回測主表的輪替口徑（+1323.6%／夏普 1.15）**不是實盤路徑**，實盤口徑（`STRAT_MODE=form` ＋過熱閘門）為
  +926.5%／MDD −45.6%／夏普 1.01。三個修正方向在 2016-2025 上全部使總報酬變差（12 組網格無一勝出）。
- `1.1.6`（2026-10-30）新增 `scripts/walk_forward.py`（前向驗證）：擴張式訓練窗逐年挑參數、只用次一年 OOS 驗證，
  輸出 OOS 串接報酬／逐年勝負／in-sample→OOS 退化，並附全期 16 組參數鄰居表（in-sample 穩健性）。
  純新增分析工具，**不改變實盤預設口徑與任何交易邏輯**。
- `1.1.5`（2026-10-30）**預設選股口徑改為 `aggressive`**（使用者裁定；先前 `revenue`）：池 150＋營收因子＋產業上限 2，
  2016-2025 +1323.6%／年化 30.42%／MDD −40.2%／夏普 1.15（0050 +477.6%／−34.0%／1.06）。
  `monthly_rebalance_picker.py` 與回測在**預設口徑**時也會印代價警語（`warning_text(is_default=True)`）；
  文件（README／使用手冊／策略說明／.env.example）同步，`.env` 的 `SELFSELECT_POOL_N` 由 100 改 150。
- `1.1.4`（2026-10-30）修 `scripts/vm/publish_dashboard.sh`：`git fetch --depth 1 origin <branch>` **不會**建立
  remote-tracking ref，原本 `checkout -B "$BRANCH" "origin/$BRANCH"` 在 VM 上實測失敗
  （`fatal: 'origin/gh-pages' is not a commit`）⇒ 改用 `FETCH_HEAD`。此修正**只需重跑
  `./scripts/vm/install_dashboard_publish.sh`**（腳本住在 VM 主機 `/usr/local/bin`，不必重新部署 image）。
- `1.1.3`（2026-10-29）儀表板發佈改走 **`gh-pages` 分支（Pages 分支模式）**：`publish_dashboard.sh` 改寫
  `gh-pages` 根目錄的 `index.html`，移除 `.github/workflows/pages.yml`；GitHub Pages Source 已改為
  「Deploy from a branch → `gh-pages` / (root)」並驗證線上內容一致。先前試的 `dash`＋Actions 方案作廢（見下）。
- `1.1.2`（2026-10-29）修 `scripts/ai_pick_ab.py` 的 `NameError`：`load_historical_shares()` 只在 `honest_pool()` 內 import，
  實際呼叫在 `main()` ⇒ 執行會炸；CI 的 pyflakes「undefined name」檢查抓到。
- `1.1.1`（2026-10-29）儀表板發佈改推 **`dash` 分支**（`scripts/vm/publish_dashboard.sh`）＋ `pages.yml` 觸發分支加 `dash`：
  機器人不再往 `main` 推 commit，解決「人手 push 被拒（非 fast-forward）」。GitHub Pages 設定不用改。
"""
import hashlib
from datetime import datetime
from pathlib import Path

APP_VERSION = "1.1.40"

# ── 建置標記 ─────────────────────────────────────────────────────────────
# ⚠️ 這裡**不是**「程式啟動時間」。原本 banner 用 `datetime.now()` 當 BUILD_DATE，
# 結果「建置日期」永遠等於啟動時間（VM 實證 2026-09-14 18:57 啟動顯示 18:57），
# 無法回答「容器裡跑的是不是剛 deploy 的那版程式」（2026-09-15 修）。
# 建置時間 = 執行期原始碼檔的最新 mtime（容器內≈映像 COPY 進去的時間）；
# 指紋 = 檔案內容 sha1（與 mtime 無關）→ 內容一改就一定看得出來。
BUILD_PATHS = ('selfselect_trader.py', 'core', 'utils', 'strategies', 'config', 'data', 'scripts')


def _iter_source_files(root, paths):
  for rel in paths:
    p = Path(root) / rel
    if p.is_file():
      yield p
    elif p.is_dir():
      for f in sorted(p.rglob('*.py')):
        if '__pycache__' in f.parts:
          continue
        yield f


def build_info(root=None, paths=BUILD_PATHS):
  """回傳 (建置時間字串, 原始碼指紋 8 碼)。找不到任何來源檔時回 ('unknown', 'unknown')。"""
  try:
    files = sorted(_iter_source_files(root or Path(__file__).resolve().parent.parent, paths))
    if not files:
      return ('unknown', 'unknown')
    ts = max(f.stat().st_mtime for f in files)
    h = hashlib.sha1()
    for f in files:
      h.update(f.name.encode('utf-8'))
      h.update(f.read_bytes())
    return (datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'), h.hexdigest()[:8])
  except Exception:
    return ('unknown', 'unknown')
