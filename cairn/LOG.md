# Project Cairn Log

本檔以倒序記錄實質推進（最新在最上面，緊接這行之下）。每則保持精簡——只寫摘要與指標，結論沉澱到 `cairn/<主題>.md`。

## 2026-10-30 · W7 定稿：一句話總結加上「自 2026-10-30 起實測、持續改進、以 Git 專案為準」

- 使用者指定的一句話總結定稿為：**「預設從 legacy 換成 zscore，並多了『AI 當選股員』這個選項；但兩者都還沒站穩」**，
  後面接專案狀態：**自 2026-10-30 起開始實測、持續改進，最新更新請上 Git 專案**（`github.com/dinchentech/tw-selfselect`）。
- 落點：S2（四個問題頁）加一行狀態並同步講稿；S18（總結頁）加 📌 一行並在講稿說明「講義數字是當天版本、以 repo 為準」。
  順手修掉「• 1.」編號項目符號重複。`W7-解說腳本.md` 已用 `notes_to_script.py --force` 重出（18 頁／約 40 分 30 秒）。
- 版號 `1.1.4 → 1.1.5`（教材內容修改，執行行為不變）。

## 2026-10-30 · 新增 W7 講稿版：v1.1 之後的 zscore（預設）＋ AI 選股

- 交付 `plans/ppt/TW-SELFSELECT台股買賣自動化系統-W7-講稿版.pptx`（**18 頁**、備註合計約 5,400 字／估 40 分 30 秒）
  與 `W7-解說腳本.md`（由 `notes_to_script.py` 從備註反推）。產生器 `plans/ppt/make_w7.py`（沿用 W6 母版，刪光範例頁後重畫）。
- 四段主軸：①zscore（預設）＋AI 選股與回測結果 ②zscore 重要參數速查 ③AI 選股怎麼用（D1 五步＋逾期 fallback）
  ④可能的改進方式（依槓桿排序）＋版本／部署紀律一頁。
- 數字口徑一致：2016-2025、正常組、含成本、`PROFILE=default`；preset current +411.1%／revenue +762.4%／aggressive +1323.6%，
  0050 +477.6%；並如實寫出「回撤 −53.7%、夏普 0.95、樣本內挑選、資料快照 515→645 檔差 253pp、下市價偏樂觀」。
- 版號 `1.1.3 → 1.1.4`（新增 `plans/ppt/make_w7.py`）。`plans/` 不在 `BUILD_PATHS`，但 `core/version.py` 在 ⇒ 指紋仍會變（只是版號字串）。
  執行行為不變；不趕著為此重新部署，下次有真正的程式改動時一起上。
- 未做配音版／MP4（需 `plans/generate_narration.sh build` 跑 TTS，本次未執行）。

## 2026-10-29 · v1.1.3：儀表板改走 `gh-pages` 分支模式（`dash`＋Actions 方案作廢）

- `dash` 方案**實測失敗**：把發佈改推專用 `dash` 分支、並在 `pages.yml` 觸發分支加入 `dash` 之後，
  推 `dash` **完全沒有觸發 workflow**（`gh run list`／API 都 empty）⇒ GitHub 對非預設分支的 push
  不會執行「只存在於該分支」的 workflow。dash 分支已刪。
- 最終做法（已生效並驗證）：**GitHub Pages 分支模式**——Source = `Deploy from a branch` → `gh-pages` / `(root)`；
  `publish_dashboard.sh` 的 `BRANCH` 預設改 `gh-pages`，改寫**根目錄** `index.html`（＋`.nojekyll`），
  舊工作區的 sparse 設定自動關掉；`.github/workflows/pages.yml` 移除。
- 驗證：切換來源後 `curl` 公開頁 **HTTP 200**、內容 sha1 與 `docs/index.html` **完全相同** ⇒ 零停機；`gh api .../pages` 顯示
  `build_type=legacy, source={branch: gh-pages, path: /}`。
- 版號 `1.1.2 → 1.1.3`（依「改程式就 +1」）。部署仍待使用者手動 `./deploy_source.sh`。
- 備註：`main` 上的 `docs/index.html` 保留當「人看的來源快照」，不再自動更新；實際發佈看 `gh-pages`。

## 2026-10-29 · 修 CI 紅燈：`ai_pick_ab.py` 的 `NameError`（v1.1.1 → v1.1.2）

- GitHub Actions 的 `tests` 從 v1.1.0 那次就紅：靜態檢查（pyflakes，只把 undefined name 當錯）
  抓到 `scripts/ai_pick_ab.py:202 undefined name 'load_historical_shares'`——`load_historical_shares()` 只在
  `honest_pool()` 裡 import，真正呼叫在 `main()` ⇒ **A/B 工具一跑就 NameError**，本機測試沒覆蓋到這條路徑。
- 修法：`honest_pool()` 移除用不到的 import、`main()` 補上 `from core.candidate_pool import load_historical_shares`。
- 版號 `1.1.1 → 1.1.2`（依「改程式就 +1」）。本地用與 CI 相同條件跑過 pyflakes：**全 repo 無 undefined name**。
- 教訓：CI 的 static check 是「本機 pytest 看不到的執行期錯誤」守門員；改完 import 結構要順手跑一次
  `pyflakes selfselect_trader.py core scripts strategies data utils | grep -i "undefined name"`。

## 2026-10-29 · v1.1.1：儀表板發佈改推 `dash` 分支（解決「人手 push 被拒」）

- 問題：`publish_dashboard.sh` 的發佈工作區（VM 上的 sparse clone）每天 13:50 直接推 `main`
  ⇒ 遠端 `main` 多一個機器人 commit（`5f8d7e7 儀表板：自動發佈 2026-10-29 資料`），使用者本機 commit 後 push 被拒（非 fast-forward）。
- 修法（結構解，GitHub 網頁端**不用改任何設定**）：`BRANCH` 預設 `main` → **`dash`**；`.github/workflows/pages.yml` 觸發分支加 `dash`；
  發佈工作區改用 `checkout -B "$BRANCH" origin/$BRANCH`（舊工作區本地分支是 main 也能直接切換）。
  已建立遠端 `dash` 分支（起點＝當時的 `docs/index.html`），Pages 仍由 Actions 建置。
- 版號 `1.1.0 → 1.1.1`（依「改程式就 +1」規則）。部署仍待使用者手動 `./deploy_source.sh`；
  部署後 13:50 的發佈會改推 `dash`，`main` 從此只由人推。
- 本機另設 `git config pull.rebase true` / `rebase.autoStash true`（雙保險；這次 push 被拒就是用 `pull --rebase` 解的）。
- 附帶更正：先前把「Pages 來源」講成「Deploy from a branch → gh-pages」是**錯的建議**——本 repo 的 Pages 是
  `build_type=workflow`（GitHub Actions 從 `docs/` 建置），純分支模式反而要停用 `pages.yml`。已改走 `dash` 分支方案。

## 2026-10-29 · VM 已升上 **v1.1.0**（指紋 132bdb86）並實測新口徑可用

- 使用者重跑 `deploy_source.sh` 後成功：banner `🚀 TW SelfSelect v1.1.0 (build 2026-10-29 22:42:12 / 132bdb86)`、啟動 23:26:51，
  個股設定 5 檔（1802／4938／6505／1301／1101）、Telegram 已發送、watchdog 啟動、休眠至 10/30 09:00。
- agent 唯讀驗證（不動 .env、不寫檔）：
  - `.env` 第 95/96 行 `SELFSELECT_POOL_N=100`／`SELFSELECT_PRESET=revenue` 被 deploy 保留下來（deploy 不覆蓋既有 .env）。
  - 容器內 preset 解析：`revenue → POOL_N=100、FACTOR_REVENUE=1、MAX_PER_SECTOR=0`。
  - 容器內實跑 zscore 選股路徑（基準日 2026-10-23、季池 2026-08、池 100）：`有 PER 100／有營收 100`、可排序 66、選出 2615/2603/2347/2884/4938
    ⇒ 新程式、PER 快取、月營收快取三者在 VM 上都真的生效。
- 待觀察：11/2（11 月第一個交易日）D1 13:36 自動選股會第一次用 `revenue` 口徑；屆時要看 log 的 `🎚️`／`🔢`／名單三行。
  VM 價格快取當時最新只到 2026-10-23，但 D1 流程的步驟 0 會先補價，不需手動處理。
- 提醒：目前 5 檔持倉仍是舊名單，**下次換股才會套新口徑**；`revenue` 的歷史回撤 −53.7%（0050 −34%），要有心理準備。

## 2026-10-29 · VM 升級前置：補 .env 池/preset、推 PER 與月營收快取；**發現部署其實沒生效（VM 仍 v1.0.0）**

- 使用者已自行跑 `deploy_source.sh`，但實測 **VM 仍是 v1.0.0**：容器指紋 `c90ebbc6`、image `tw-selfselect:latest` 建於 2026-10-27 11:43
  （本機 image 同樣是 10-27 ⇒ `docker build` 根本沒跑）；容器內 `core.pit_data` 不存在。⇒ 換版仍待使用者重跑部署（依規則不由 agent 代跑）。
- 已完成（agent 代處理，皆已驗證）：
  - VM `.env` 明示 `SELFSELECT_POOL_N=100` 與 `SELFSELECT_PRESET=revenue`（原本兩者都未明示、靠程式預設）。備份 `.env.bak_before_pool100_*`。
  - 推 `cache/stock_per`（**672 檔／37MB**）＋`cache/stock_revenue`（**645 檔／7MB**）＋`cache/stock_industry.pkl` 到 VM，容器內看得到（672/645）。
  - bot 偵測 `.env` 變更後熱重載、回報「目前監控 5 檔」；持倉 5 檔、近 10 分鐘 0 錯誤、磁碟 9.0G 可用。當下為 22:5x（收盤後）⇒ 無交易風險。
- **踩到的坑（已修）**：VM `.env` 最後一行沒有換行符，直接 `>>` 追加會把新內容**黏在最後一行 `PC_1802=…`** 上
  （等於弄壞該檔的 PC_ 設定）。已從備份還原並改用「先 `printf "\n"` 再追加」，並用 json 解析驗過 5 筆 `PC_` 全部正常。
  ⇒ 之後對任何 `.env` 追加都要先確認結尾換行；已記進 `cairn/deploy-pipeline.md`。
- 待辦：使用者重跑 `./deploy_source.sh` → agent 驗證 banner／指紋 `132bdb86`、`v1.1.0`，以及 D1 picker 的 `🎚️ preset: revenue｜池 100｜營收因子 開`。

## 2026-10-29 · 版號 1.0.0 → **1.1.0**，並立下「改程式就 +1、部署只能手動」兩條硬規則

- 版號：`core/version.py` `APP_VERSION` **1.0.0 → 1.1.0**（含 AI 選股模式、zscore 評分器、選股 preset、宇宙/PIT 資料修復），
  檔頭新增「版號規則＋版本沿革」，指紋 `132bdb86`。版號出現在啟動 banner／Telegram 啟動收盤／儀表板標題。
- **規則①（使用者裁定）**：只要程式有修改，`APP_VERSION` 就要 +1（`1.1.0`→`1.1.1`…）；純文件不動版號；**大升版由使用者主動通知**，不自作主張。
- **規則②（使用者裁定）**：`deploy_source.sh` **一律由使用者手動執行**——AI agent／自動化流程不得代跑部署、不得 SSH 重啟 VM 容器；
  換版時只準備程式＋版號並提醒使用者。已寫進 `AGENTS.md`（59 行，仍在 60 行上限內）、`cairn/deploy-pipeline.md`、
  `使用手冊.md`、`deploy_source.sh` 檔頭註記。
- 同時把今天整批改動 commit（原本 80 個檔案未提交）——之後每次改程式都要在 commit 前確認版號已 +1。
- 未執行 `deploy_source.sh`（依規則②）；VM 仍是舊版，換版請使用者自行處理。

## 2026-10-29 · 使用者裁定：預設選股口徑改成 `revenue`（池 100＋營收因子）

- 裁定：`core/selection_presets.DEFAULT_PRESET` 由 `current` 改為 **`revenue`**（回測 `PRESET` 與實盤 `SELFSELECT_PRESET` 同步），
  `.env` 的 `SELFSELECT_POOL_N` 也由 50 改 **100**（否則 preset 的池會被 env 蓋掉，picker 會一直警告不一致）。
  `.env` 已備份為 `.env.bak_before_preset_<時間戳>`。
- 實測（正常組、2016-2025、`PROFILE=default`、含成本）：`revenue` **+762.4%／年化 24.05%／MDD −53.7%／夏普 0.95**
  vs 0050 +477.6%／−34.0%／1.06；`current` +411.1%／−52.4%／0.75；`aggressive` +1323.6%／−40.2%／1.15。
- 誠實告知（程式每次執行都會印）：**報酬首次贏 0050，但回撤 −53.7% 是三個 preset 裡最深的、夏普 0.95 仍低於 1.06**；
  `revenue` 與 `aggressive` 同屬「同一段歷史挑出來的結果」，未 walk-forward、對資料覆蓋率敏感。
- 實機驗證：`monthly_rebalance_picker.py` 預設即為 `revenue`（池 100、營收因子開、產業上限無），
  印出代價摘要；名單與回測相同口徑 9/9 一致。
- 文件：使用手冊 §3-0b（改列預設口徑與「PROFILE＝資金口徑 vs PRESET＝選股口徑」的區別）與 §3-0c（preset 表，
  `revenue` 標為預設）；README「選股口徑 preset」表同步；`.env.example.txt`（`SELFSELECT_PRESET=revenue`）；策略說明；
  `results/backtest_delisted_universe.md`。

## 2026-10-29 · 選股口徑做成使用者可選 preset（`PRESET`／`SELFSELECT_PRESET`）＋實盤補上營收因子／產業上限

- 起因：使用者裁定「總報酬超過 0050 的口徑要交給我用參數決定，但**不能替使用者決定全部**，後果要誠實告知」。
- 新增 `core/selection_presets.py`（單一真相）：`current`（池100、無營收因子＝**預設，行為不變**）／`revenue`（池100＋營收因子）／
  `aggressive`（池150＋營收因子＋上限2）。規則：**明示的環境變數一律優先**（`SCORING_MODEL`／`FACTOR_REVENUE`／`MAX_PER_SECTOR`／
  `UNIVERSE_DELISTED` 已補進 `ENV_OVERRIDE_KEYS`，否則 profile／preset 會反過來蓋掉使用者）。
- 實測（正常組、2016-2025、`PROFILE=default`、含成本；0050 +477.6%／−34.0%／1.06）：
  `current` **+411.1%／−52.4%／0.75**、`revenue` **+762.4%／−53.7%／0.95**、`aggressive` **+1323.6%／−40.2%／1.15**
  ⇒ 前兩者仍輸 0050；`aggressive` 首次報酬＋夏普都贏，但回撤仍比 0050 深，且是 16 組裡事後挑出的最好一組。
- 實盤補齊：`monthly_rebalance_picker.py` 的 zscore 現在支援營收因子與產業上限；**PER 改成磁碟快取優先**
  （舊版只在「價量過熱命中」才抓 PER ⇒ 多數候選股 `per=None` 被 `0<PER<=40` 資格默默剔除）。
  **一致性驗證：3 preset × 3 日期 = 9/9 與回測逐位相同**（`TMP/parity_pick.py`）。
- **更正上一則的兩個判斷**：①「倖存者偏差讓寬池高報酬」講得太重——補下市股對十年總報酬的影響是**方向不一致、量級 ±100pp**
  （池150＋營收＋上限2：只存活 +1289.0%、含下市 +1323.6%），真正被它藏起來的是尾部風險；
  ②「營收因子窄池負貢獻」是快取不足的假象，PER／營收補齊後**同池大小開因子一律變好**。
- **新教訓（已寫進 pitfalls）**：結果對資料覆蓋率極敏感——月營收快取 515→645 檔讓同一格從 +1070.5% 變 +1323.6%（+253pp）
  ⇒ 比較參數前必須先把資料補滿並**記錄快照**（`TMP/build_revenue_missing.py` 補 123 檔，另 27 檔 FinMind 無資料）。
- 兩個實作細節（都是踩過的）：①實盤只認 `SELFSELECT_` 前綴的明示值——`POOL_N`／`FACTOR_REVENUE` 這些**回測旋鈕**
  若躺在同一份 `.env` 就會偷偷改實盤行為，已改成不理它們並加測試；②`.env` 的 `SELFSELECT_POOL_N`（目前 50）優先於 preset，
  只切 preset 池不會變 ⇒ picker 會印警告並提示怎麼改（避免拿池 150 的回測數字套在池 50 上）。
- 文件：README 新增「選股口徑 preset」決策表＋五條後果；使用手冊 §3-0c；`.env.example`（`SELFSELECT_PRESET`，
  並把 `FACTOR_REVENUE` 改回註解避免誤開）；`策略說明.md`；`results/backtest_delisted_universe.md` 同步。
- 測試：`test/test_selection_presets.py`（20 個：預設不變／明示優先／後果文字必須含回撤夏普 walk-forward／實盤 reload 開關／
  orchestrator 池大小）⇒ 全套 **770 passed**。

## 2026-10-29 · 補回 62 檔已下市個股＋PER 補齊 672 檔 ⇒ 重跑矩陣：倖存者偏差確認、營收因子翻正

- 資料修復（`TMP/build_delisted.py`、`TMP/build_per_missing.py`）：TWSE 2016-2025 下市 74 筆 → 篩 4 碼非 TDR **62 檔**
  補進宇宙（價格＝FinMind 原始價＋現金股利**自建還原**，因 Yahoo 無下市股、`TaiwanStockPriceAdj` 對下市股回 400；股本 2,818 筆 →
  `historical_shares_delisted.pkl`）。另發現 **PER 快取只有 267/672 檔**，而 zscore 資格是 `0 < PER <= 40` ⇒ 6 成候選股被默默剔除，已補到 672/672。
- 程式：`core/candidate_pool.load_historical_shares()`（`UNIVERSE_DELISTED=1` 預設併入下市股、剔 91xx TDR）＋
  `build_quarterly_pool(max_stale_days=45)` 新鮮度閘門（季點前 45 天無價 ⇒ 視為買不到，下市股不會滲進實盤池）；六個呼叫端改用它。
- 池成員變化：44 季累計「下市股進池」池20 **95 次**（2.2/季）、池50 270、池100 378、池150 **474（10.8/季）**；2016-01 前 5 名全是後來下市／被併
  （6452 康友-KY、2325 矽品、1704 榮化、3474 華亞科、2311 日月光）。
- 結果（正常組、2016-2025、zscore＋停泊0050、0050 +477.6%；`results/backtest_delisted_universe.md`）：
  含下市 vs 只存活 → 池20 +395.1% vs +369.4%、池50 +291.1% vs +269.6%、池100(營收) +709.6% vs +686.1%、
  池150(營收+產業2) **+1070.5% vs +1188.9%（−118pp）**、池150 無營收 +541.7% vs +661.4%（−120pp）。
  ⇒ 偏誤**池越大越明顯**，但**方向不一致**（小池反而略升，因補進的 62 檔同時含地雷與被溢價併購）。
- **更正上一則的兩個判斷**：①「營收因子窄池負貢獻、寬池正貢獻」是**快取不足造成的假象**——PER 補齊後各池大小都是正貢獻
  （池20 +395.1→+407.1%、池50 +291.1→+446.0%、池100 +411.1→**+709.6%**、池150 +541.7→+704.7%）；
  ②「所有組合都輸 0050」不再成立：**開營收因子**的池100／池150 組合總報酬超過 0050，但 MDD −40~−56%（0050 −34%）、夏普最多打平（1.06）。
- 預設口徑（`FACTOR_REVENUE=1` 本來就是程式預設）重跑：池20 zscore＋停泊 = **+407.1%／年化 17.63%／MDD −35.6%／夏普 0.95**
  （舊 +369.4%／0.89）；六種組合、profile 表、`.env.example` 已同步改。`FILL_MODE=topup` 在池20 已**完全沒作用**（每月都選得滿 5 檔）。
- **實盤缺口（下一步第一優先）**：`monthly_rebalance_picker.py` 的 zscore **沒有營收因子也沒有產業上限**，等於停在表上偏弱的 +411.1% 那一欄。
- 測試：新增 `test/test_delisted_universe.py`（6 個：併入下市、可關閉、缺檔不致命、下市股活著時進池／死後退出、閘門可關、新鮮股保留）⇒ 全套 **750 passed**。

## 2026-10-29 · 第一輪改進實驗：營收因子／產業上限／池大小 —— 兩個沒效、一個不可信

- 依上一則的「改進空間」做了兩件可驗證的改動：①月營收 YoY 加進 z 分數（`FACTOR_REVENUE`，權重 r63 0.25／r20 0.25／dist 0.20／per 0.15／rev 0.15）
  ②產業分散上限（`MAX_PER_SECTOR`，用 `cache/stock_industry.pkl` 2,554 檔的產業對照）＋③池大小 20/50/100/150 掃描。
- 先把月營收快取補齊（**39 → 515 檔**，`TMP/backfill_revenue.py`，FinMind 逐檔抓、遇到 5 次失敗自動停）。
- 結果（正常組、2016-2025、zscore＋停泊0050、含成本；0050 +477.6%）：
  基準（池20、無因子、無上限）**+369.4%（年化 16.73%、MDD −34.6%、夏普 0.89）**；
  池20＋營收 +369.7%（幾乎無效，當時快取不足）；池20＋產業上限 +363.9%（−5.5pp）；池20＋兩者 +316.1%（**更差**）；
  池50 +373.5%（MDD −50.7%）；池100 +630.3%；池150＋營收 **+1289.5%（年化 30.11%、MDD −44.3%、夏普 1.13）**、池150 無營收 +510.6%。
- **判定**：營收因子在窄池是負貢獻、在寬池是大正貢獻（矛盾 ⇒ 不能採用）；產業上限讓報酬變差；池放大是最強槓桿但**最不可信**。
- **關鍵發現（擋下結論）**：股票宇宙 612 檔**不含已下市個股**——實測 `3662 樂陞`(2016 下市)、`3519 綠能`(2019)、`3514 昱晶`(2018 合併) 都不在宇宙內
  ⇒ 寬池（100/150）的報酬被**倖存者偏差**系統性高估。所以下一步不是調參數，而是**重建含下市股的宇宙**再重跑同一組實驗。
- 在那之前：**預設維持池 20、`FACTOR_REVENUE=0`、`MAX_PER_SECTOR=0`**（已寫進 `.env.example.txt`、`使用手冊.md`、README 新段「第一輪改進實驗」）。
- 測試：`TestRevenueFactorAndSectorCap`（5 個：營收因子改變排序、缺營收不踢除、權重總和 1.0、產業上限補位、未知產業歸同類）⇒ 全套 **744 passed**。

## 2026-10-29 · 更正對外說法：預設組合仍輸 0050 ⇒「選股／AI 選股／策略都還有很大改進空間」

- 使用者指正：不該把 `default`（+369.4%）說成「風險調整後最好」就收尾，應該明講**我們仍輸給 0050（+477.6%）、三大面向都還有很大改進空間**。
- 文件已改寫（不再用「預設不錯」的框架）：
  - README：預設口徑段加 ⚠️ 說明；新增 **「改進空間（誠實清單）」** 段（8 項缺口：池太窄／因子只有動能＋評價／法人與新聞資料缺口／
    出場機制單薄／成本未計滑價／驗證樣本不足與窗口重疊／AI 選股未證明價值／策略組合未最佳化，逐項附現況、影響、下一步）。
  - `使用手冊.md` §3-0b、`策略說明.md` §9-9：改成「預設是測過最好的，但仍輸 0050 ⇒ 三大面向都還有改進空間」，並指向 README 清單。
- 事實依據（2016-2025、正常組、池 20、含成本）：程式 legacy +57.0%／zscore +106.9%／AI 公平版 +110.0%（停泊後 +203.5%／+369.4%／+349.4%），
  **全部 < 0050 +477.6%**；AI 判斷與 z 分數公式在 2024 的配對檢定也全部不顯著。

## 2026-10-29 · `PROFILE=default`（zscore＋停泊0050）＋口徑並排比較表

- `core/backtest_profiles.py` 重整為 6 個具名口徑，每個都含 `SCORING_MODEL`：
  `default`（zscore＋停泊0050＋年線）／`conservative`（zscore＋全現金）／`fair`（legacy＋停泊0050）／
  `legacy`（舊預設：legacy＋全現金）／`levered`（zscore＋融資放大）／`raw`（legacy＋無年線）。
- `scripts/backtest_profile_compare.py`：預設比較 `default,conservative,fair,legacy`，新增 `--groups-only`（只跑指定組別，快 4 倍）；
  修掉「JSON 只有一組時 KeyError」的 bug（改成只迭代結果裡存在的組別）。
- 2016-2025、正常組、池 20、TOP5、含成本並排結果（`results/profile_compare_2016_2025.md`）：
  **default +369.4%（年化 16.73%、MDD −34.6%、夏普 0.89）** ＞ fair +203.5%（11.74%、−36.0%、0.68）
  ＞ conservative +106.9%（7.54%、−31.9%、0.59）＞ legacy +57.0%（4.62%、−25.7%、0.41）；0050 +477.6%。
  ⇒ 「停泊 0050」＋「zscore 評分」兩個改動是相乘的：57.0% → 106.9%（換評分）→ 203.5%（換停泊）→ 369.4%（兩者一起）。
- 文件：README 新增「口徑 profile」段（含對照表與一行指令）、`使用手冊.md` §3-0b 補 profile、`策略說明.md` §9-9 補 profile。
- 測試：profile 測試新增 2 個（default＝zscore＋0050、legacy 還原舊行為），全套 **739 passed**。

## 2026-10-29 · 預設組合改為「zscore 評分 ＋ 閒置停泊 0050」＋實盤評分器接上共用實作

- 使用者裁定：**預設選「zscore·停泊0050」**，並更新使用手冊／策略說明。
- 程式：`SCORING_MODEL` 預設由 `legacy` 改為 **`zscore`**、`IDLE_CASH_ASSET` 預設由空改為 **`0050`**；
  算式抽到 `core/scoring.py`（純函式，`score_rows()`／`picks_from_rows()`），**回測與實盤共用同一份**；
  實盤 `monthly_rebalance_picker.py` 新增 `SELFSELECT_SCORING_MODEL`（預設 zscore）與 `pick_zscore()`。
- 驗證：不改任何參數跑 2016-2025（正常組、池 20、TOP5、年線開、100 萬）→ **+369.45%／年化 16.73%／MDD −34.62%／夏普 0.89**
  ＝與先前 `zscore·停泊0050` 完全一致；實盤 `--as-of 2024-11-29` 以 zscore 選出 **2891／2885／2886／2412／3008**（5 檔、每檔 20%）。
- 文件：`使用手冊.md` 新增 **§3-0b 預設組合**（含「改回舊行為」對照表）＋參數速查改 `zscore`；
  `策略說明.md` 新增 **§9-9 預設口徑**＋§J.1 標註預設；`.env.example.txt` 改預設；README 六組合段前加「預設口徑」說明。
- 測試：新增 `test/test_scoring.py`（8 個：PER 門檻、四個方向、缺值不空、同分可重現、空輸入），
  `TestScoringModel` 改為驗證「預設＝zscore＋停泊0050」⇒ 全套 **740 passed**。

## 2026-10-29 · 把「AI 代理公式」做成本專案的評分選項（`SCORING_MODEL`）＋ LLM 親自判斷的對照

- 使用者問「AI 代理那套（+110% vs 程式 +57%）為何不套用到程式自選？」⇒ 有道理，已做成選項。
- `SCORING_MODEL`（回測）／`SELFSELECT_SCORING_MODEL`（實盤語意，實盤 picker 尚未串接）：
  `legacy`（預設，`ssg.score_stock` 綜合分）／`zscore`（先篩 0<PER≤40，再 0.40·z(63日)+0.25·z(20日)+0.20·z(距52週高)+0.15·z(−PER)）。
- 2016-2025 實測（正常組、池 20、TOP5、年線開、含成本）：**legacy·閒置 +57.0%（年化 4.62%、MDD −25.7%、夏普 0.41）
  → zscore·閒置 +106.9%（7.54%、−31.9%、0.59）**；停泊 0050 後 **+203.5% → +369.4%**（11.74%→16.73%、夏普 0.68→0.89）。
  ⇒ 「AI 比較好」有很大一部分其實是**評分方式**差異，不是模型的神秘能力；而且兩者都仍輸 0050（+477.6%）。
- LLM 親自判斷（2024 年 12 個選股日、只用 PIT 封包、不用公式）：平均報酬 legacy 1.75%／zscore 2.81%／子代理公式 2.64%／
  **LLM 3.26%**（1 個月）；6 個月 6.02%／8.55%／9.05%／**9.92%**；12 個月 18.28%／17.78%／18.80%／**19.47%**。
  配對檢定：LLM−legacy 1M **+1.51%（t=1.96）**、3M +2.83%（1.78）、6M +3.90%（1.61）、12M +1.19%（0.31）；
  LLM−zscore／子代理 **全部不顯著**（+0.45%~+1.68%）⇒ **LLM 的判斷與 z 分數公式打平**，樣本太小不能推廣。
- 產出：`results/hist_windows/way_zscore_{cash,park}.json`、`results/compare_models_2024.json`、`TMP/llm_picks_2024.json`、
  `TMP/compare_models_2024.py`；文件同步 README（新增「評分模型」「LLM 親自判斷」兩段）、`.env.example.txt`、`使用手冊.md`、`策略說明.md` §J.1。
- 測試：`TestScoringModel`（3 個）⇒ 全套 **729 passed**。

## 2026-10-29 · 消除 AI 的「一天領先」偏差：重建 117 份無領先封包重跑 → AI 仍勝程式但輸 0050

- 問題（上一則自記的偏差）：舊封包的 `as_of` 是「當月第 1 個交易日收盤」（＝AI 自己的進場價），
  而引擎在「前一個交易日」選股 ⇒ AI 比程式多一天資訊，AI 那兩列（+226.0%／+651.7%）只是上界。
- 修正：`TMP/gen_packs_pit.py` 用**引擎真正的 sel_date**（`FULLCAL` 上前一個交易日）重建 117 份封包
  （`TMP/ai_packs_pit/`＋`logs/ai_pick_pit/`），再由四個子代理各負責 30／30／29／28 個日期重新選股
  （固定公式：PER 篩選＋63日／20日／距52週高／PER 的 z 分數；105→117 全部 5 檔、全數驗證通過）。
  名單：`results/ai_picks_pit_2016_2025.json`（117 日期，key＝sel_date，因此可直接對上引擎）。
- 公平口徑結果（正常組、2016-2025、100 萬、池 20、TOP5、年線開、含成本；0050 +477.6%／年化 19.17%／夏普 1.06）：
  - 程式·不補·閒置 **+57.0%**、停泊 **+203.5%**；程式·補滿·閒置 +51.8%、停泊 **+219.1%**
  - **AI·閒置 +110.0%**（年化 7.70%、MDD −31.9%、夏普 0.59）、**AI·停泊 +349.4%**（年化 16.22%、MDD −33.6%、夏普 0.87）
  - ⇒ 消除一天領先後，AI 仍勝程式（+110% vs +57%、+349% vs +204%），但**兩者都輸 0050（+477.6%）**；
    先前「AI·停泊 +651.7% 贏 0050」的結論**作廢**。
- README「六種組合」段已改成這版（含偏差說明、無領先口徑、重跑指令）；舊版數字只在 LOG 留痕。
- 產出：`results/hist_windows/way_aipit_{cash,park}.json`、`results/ai_picks_pit_2016_2025.json`、
  `TMP/gen_packs_pit.py`、`TMP/run_way_ai_pit.sh`、`TMP/aipickpit_*.json`（117）。

## 2026-10-29 · 2016-2025 六組合分析寫進 README（正常組：AI/程式 × 不補/補滿 × 閒置/停泊）

- 需求：「只用正常組跑 2015-2025：AI/程式自選 × 不補/補滿 × 閒置/補 ETF，結果放 README」。
  實務限制：個股價格快取從 **2016-01-04** 起（2015 只有 0050 與加權指數）⇒ 實際窗口 2016-2025。
- 為了讓 AI 也能進回測，新增 `AI_PICKS_FILE`（JSON：`{date: [sids]}`，**只有正常組**採用；沒有對應日期照程式規則）。
  封包的 `as_of` 是「當月第 1 個交易日」，而引擎 `sel_date` 是前一個交易日 ⇒ 加了 `_ai_picks_for()`（≥ sel_date、10 天內最近者）。
- AI 名單來源：2022 年 12 個日期＝本對話模型依封包判斷；2016-2021 與 2023-2025 共 105 個日期＝子代理用**固定公式**（動能／相對強度／
  PER／營收 z 分數）產生；2016-01、2016-02 暖機期封包為空（該兩月照程式自選）。全部名單存 `results/ai_picks_2016_2025.json`（117 日期）。
- 結果（100 萬、池 20、TOP5、每月、年線開、含成本；0050 同期 **+477.6%／年化 19.17%／MDD −34.0%／夏普 1.06**）：
  - 程式·不補·閒置 **+57.0%**／停泊 **+203.5%**；程式·補滿·閒置 +51.8%／停泊 **+219.1%**
  - AI·閒置 **+226.0%**（年化 12.54%、MDD −26.9%、夏普 0.90）；AI·停泊 **+651.7%**（年化 22.35%、MDD −35.2%、夏普 1.12）
- 三大發現：①**閒置要不要押 0050 是最大變數**（+57%→+204%、+226%→+652%）；②補滿影響小（閒置時 −5pp、停泊時 +15pp）；
  ③AI 明顯優於程式，AI·停泊甚至贏 0050。
- ⚠️ **兩個必須標明的偏差（已寫進 README）**：①**AI 有一天資訊優勢**——封包 as_of 是進場當天收盤（含自己的進場價），
  程式自選用的是前一交易日收盤 ⇒ AI 那兩列是**上界**，不是公平比較；②AI 組大多是子代理的固定公式，不是 LLM 判斷。
  要公平比需把封包改成「前一交易日收盤」重建（117 日期）再重跑，尚未做。
- 產出：README「六種組合」段、`results/hist_windows/way_*.json`（6 份）、`results/ai_picks_2016_2025.json`、
  `TMP/run_8way.sh`、`TMP/run_way_ai.sh`、`TMP/gen_packs_bulk.py`（2016-2021 封包 72 份）。

## 2026-10-29 · 取消「ETF 補滿」：ETF 只用在閒置停泊

- 使用者裁定：**自動選股不選 ETF、補滿也不拿 ETF 補**；ETF 只用在「閒置資金停泊」（`IDLE_CASH_ASSET`）。
- 已移除：回測的 `FILL_TOPUP_SOURCE`／`FILL_TOPUP_ETFS`／`FILL_TOPUP_ETF_RANK`／`_etf_rank()`／`_order_etfs()`／`_fill()` 的 ETF 分支；
  實盤的 `SELFSELECT_FILL_TOPUP_SOURCE`／`SELFSELECT_FILL_TOPUP_ETFS`／`_etf_available()`。`FILL_MODE=topup` 現在**只用個股**補
  （先放寬過熱／法人，再依 63 日動能）。`IDLE_CASH_ASSET`（停泊 0050）完全保留。
- 回歸：移除後 `FILL_MODE=topup`（2022-2025、池 20、TOP5、年線開、100 萬）回到 **正常 +30.86%／高風險 +17.21%／高穩定 −3.69%**，
  與加入 ETF 補滿之前那一版（`fill_topup_w2225.json`：+30.9%／+17.2%／−3.7%）一致；連跑兩次逐位相同（可重現）。
  （中途那版 `fill_topup_ranked.json` 的 +30.4%／+16.1% 是「ETF 被載入資料集」時的數字，已作廢。）
- 文件：`.env.example.txt`、`使用手冊.md` §5-2a（移除 ETF 補法對照表，改註明「ETF 只作停泊」）、`策略說明.md` §J.1。
- 測試：`TestTopupSource` 改為 `TestTopupOnlyStocks`（2 個：確認 ETF 相關介面已不存在、補滿只用個股）⇒ 全套 **726 passed**。
- 保留為歷史證據：`results/hist_windows/fill_topup_etf.json`（實驗用，現行代碼已無法重跑）。

## 2026-10-29 · 補滿的「拿什麼補」也做成選項：原次序 vs ETF 名單（預設不選 ETF）

- 使用者裁定：①**自動選股維持不選 ETF**（池子仍只有個股）②補滿時讓使用者選：**(1) 照原先次序補 (2) 用 ETF 第一名開始依序補**。
- 實作：`FILL_TOPUP_SOURCE`（回測）／`SELFSELECT_FILL_TOPUP_SOURCE`（實盤），預設 `ranked`：
  - `ranked`：先放寬「過熱／法人」補個股，仍不足再依 63 日動能補（原行為）。
  - `etf`：**不放寬個股濾網**，改用 `FILL_TOPUP_ETFS`（預設 `0050,006208,00878,0056`）依序補；ETF 用完仍不足才退回 `ranked`。
  - ETF「第一名」可用 `FILL_TOPUP_ETF_RANK=list`（預設，照名單）或 `momentum`（依 63 日動能排序）決定。
  - 選股池本身**不含 ETF**（`mcap_ranking`／`historical_shares` 都只有 4 碼個股）——只有「補滿」與「閒置停泊」會碰到 ETF。
- 實測（2022-2025、池 20、TOP5、年線開、100 萬；0050 +99.9%）：正常 **+31.1%（不補）／+30.4%（補滿·原次序）／+29.1%（補滿·ETF）**；
  高風險 +17.9%／+16.1%／**+9.0%**；高穩定 −4.0%／−4.2%／−4.5%；權值動能同上。補滿·ETF 在動能型組別最差（−7.2pp）。
  ETF 補進的次數：正常組 9/48 次選股、共 15 檔；高穩定 2/48 次、5 檔。
- 實盤驗證（`--as-of 2023-11-01`，該月只選得出 3 檔）：`topup + etf` 補成 **2454／2412／3711／0050／006208**（依 ETF 名單順序），
  並修掉 ETF 的 `max_entry_price` 為 0 的問題（ETF 不在候選池的 data 裡 ⇒ 直接載入算收盤）。
- 文件：`.env.example.txt`、`使用手冊.md` §5-2a（新增補法對照表＋三選項實測）、`策略說明.md` §J.1。
- 測試：`TestTopupSource`（5 個：ETF 先補、ETF 用完才退回個股、ranked 不變、proportional 忽略來源、ETF 排序 list/momentum）⇒ 全套 **729 passed**。

## 2026-10-29 · 依健檢結果更新知識層：AI 選股補完、儀表板憑證改 deploy key、新增教材專題

- `cairn/ai-stock-selection.md` 大幅補完：A/B 實測表（n=44／嚴格等量 n=21／規則組補滿 n=47）、`--require-full`、`FILL_MODE`／`SELFSELECT_FILL_MODE`、DSH 兩步流程（`ai_pick_dsh.py`）、實盤 `SELFSELECT_AI` 與 D1 fallback；並加了 §更正 註明舊版「A/B 未做／新聞未接」是錯的（規則：修正舊判斷要留更正說明，不靜默覆蓋）。
- `cairn/deploy-pipeline.md` 儀表板憑證段改寫成「deploy key 優先、PAT fallback」，補「憑證檔存在≠有效」（`~/.dash-publish-token` 0 bytes ⇒ 10-27／10-28 停更）與 cron 無 `user.email` 的坑。
- `cairn/ROADMAP.md` 當前焦點改成現況（AI 選股不再佔焦點、真錢上線仍是閘門），新增 3 個里程碑（儀表板連續成功／AI 去留決策／教材一致性）。
- 新增 `cairn/teaching-material-pipeline.md`：W1–W6 教材產製模型＋五個反覆踩的坑（使用者存檔覆蓋、tab 排版錯位、`sz` 1/100pt、螢光筆是 run 屬性、一份簡報混兩套口徑）。
- 5 份專題的 `contains` 從中文小節名改為受控詞彙（`experience`／`procedure`／`lesson`／`open_question`）；正文標題不動。
- 未做（使用者未選）：畢業候選 `graduation_status` 覆核；`monthly_selfselect_run.py` 路徑寫法在舊 LOG 條目裡仍缺 `scripts/`（歷史條目不改）。
- 指標：`cairn/ai-stock-selection.md`、`deploy-pipeline.md`、`ROADMAP.md`、`teaching-material-pipeline.md`。

## 2026-10-29 · Cairn 健檢：知識層落後 LOG 一輪（AI 選股專題自相矛盾、儀表板憑證仍寫 PAT）

- 範圍：LOG 倒序與長度、5 份知識專題的 frontmatter 與內容、ROADMAP、`.cairn/config.yaml` 規格漂移、`related` 連結、`Cited.md`／`Reference/` 是否該存在。
- 通過：LOG 53 則倒序正確、最長 19 行（≤20）；8 條 `related` 連結全部存在；AGENTS.md 57 行（≤60）；`skill_spec_date` 已等於現行 spec（2026-07-16）⇒ 無版本漂移；`Cited.md`／`Reference/` 未預建（正確）；`cairn/` 內沒有工程資產混入。
- **缺陷 1**：`ai-stock-selection.md` 落後 10-28 晚～10-29 共 5 則 LOG，且**文件內自相矛盾**——§當前結論 ⑤ 與「還沒做 2／6」仍寫 A/B harness、`--require-full`、新聞來源「未做」，但 §已實作 B／C 已記為已接。
- **缺陷 2**：`deploy-pipeline.md` §儀表板自動發佈仍把 PAT（`~/.dash-publish-token`）寫成憑證，實際 `scripts/vm/publish_dashboard.sh` 已改 deploy key 優先（10-28 三則 LOG 有記錄與驗證）。
- 未沉澱進專題（只存在 LOG）：n=47 A/B 結果（1M +0.99%／t=1.99、12M 打平）、`FILL_MODE`／`SELFSELECT_FILL_MODE`、DSH 選股流程（`ai_pick_dsh.py`、`docs/AI選股-DSH操作.md`、D1 fallback）。
- 結構性：ROADMAP 停在 10-27（當前焦點仍是真錢帳務、開放問題 3 條未更新）；W1–W6 影片/簡報的 23 則 LOG 沒有任何知識專題（兩個反覆踩的陷阱仍只在 LOG）；5 份專題的 `contains` 用中文小節名，不符受控詞彙。
- 本輪只做檢查、未改任何內容；修哪幾項由使用者決定。
- 指標：`cairn/ai-stock-selection.md`、`cairn/deploy-pipeline.md`、`cairn/ROADMAP.md`、`scripts/vm/publish_dashboard.sh`。

## 2026-10-29 · A/B 加上「規則組補滿」對照：AI 優勢只剩 1 個月那點邊際

- 動機：先前的「AI 顯著較好（1M t=2.18）」可能只是規則組常選不滿 5 檔（空手差異）。做法：規則組改用 `topup`
  （與回測 `FILL_MODE` 同義：先放寬過熱、再依 63 日動能補滿），其餘不變，`--reuse` 沿用既有 AI 稽核結果。
- 為了避開「重建 48 份封包」的慢路徑（實測會跑到 20+ 分鐘且中途被砍），另寫 `TMP/rules_topup_ab.py`：
  只算規則組（pool＋價格），AI 組直接讀既有 A/B 的 rows ⇒ 約 2 分鐘跑完。
- **樣本更正**：慢版（完整 pipeline、`--rules-fill topup`）最後也跑完了，日期數是 **47**（比先前多 3 天：2022-09／2024-07／2025-02——那 3 天比例模式規則組是 0 檔，補滿後才有 5 檔可比）。正式採用 **n=47**；先前報的 n=44 是同一批日期的子集，數字一致（兩份檔案：`ai_ab_2225_rulestopup_n47.json`／快速版 `_fast.json`）。
- n=47 結果：1M 差 **+0.99%（t=1.99）**、3M +1.96%（1.69）、6M +1.85%（0.92）、**12M +0.31%（0.08，完全打平）**。
- n=44 子集（等權、未計成本，供對照）：
  - **AI − 比例規則（現況）**：1M **+1.69%（t=2.18）**、3M +3.13%（1.79）、6M +2.76%（0.87）、12M +3.10%（0.55）
  - **AI − 補滿規則**：1M **+1.05%（t=2.00，邊界）**、3M +2.05%（1.66）、6M +2.04%（0.95）、**12M +0.01%（0.00）**
  - **補滿 − 比例（規則組自身）**：−0.63%（−1.58）、−1.08%（−1.04）、−0.72%（−0.38）、**−3.09%（−0.96）**
- 解讀：①1 個月那點優勢在「補滿規則」下仍然存在（t≈2.0，邊界顯著）⇒ 不是純粹的空手 artifact；
  ②3/6/12 個月沒有統計差異，12 個月完全打平；③規則組**自己補滿反而略差**，與回測結論一致（少而精）。
- 限制不變：窗口重疊（有效 n 更小）、2023-2025 的 AI 組是子代理的固定公式、未計成本、池只有 20 檔。
- 產出：`results/ai_ab_2225_rulestopup.json`、`results/ai_ab_2022_2025_report.md`（追加一節）、`TMP/rules_topup_ab.py`。

## 2026-10-29 · 「選不滿 N 檔」做成兩個選項（`FILL_MODE`／`SELFSELECT_FILL_MODE`）

- 需求：規則組常常選不滿 5 檔（A/B 觀察到 28/48 個月）⇒ 讓使用者選：①補滿 ②就選出的 N 檔、資金平均分配。
- 實作（回測 `FILL_MODE`／實盤 `SELFSELECT_FILL_MODE`，預設都是 `proportional`＝現況）：
  - `proportional`：維持現行——只買過濾網的股票，資金**平均分配給選出的檔數**（例：只有 2 檔 ⇒ 每檔 50% 額度）。
  - `topup`：**補滿**——先依分數補「被過熱／法人擋掉」的，仍不足再依 `_fallback_rank()`（同池 63 日動能）補到 N 檔。
- 過程中發現真正的原因：`ssg.score_stock()` 在「跌破 MA20」或流動性不足時**回傳 None** ⇒ 有些月份整個池子一檔都打不出分數（實測 2023-11 全部 None、只選出 2 檔）。所以只放寬過熱／法人補不滿，必須有第二層動能備援排序。
- 實測（池 20、TOP5、大盤年線開、100 萬）：
  - 2022-2025：正常 +31.1%→**+30.9%**、高風險 +17.9%→+17.2%、高穩定 −4.0%→**−3.7%**、權值 +17.9%→+17.2%（差異 −0.7~+0.3pp，MDD 略差）
  - 2016-2021：正常 +20.9%→+17.2%、高風險 +55.6%→**+47.8%**、高穩定 +12.5%→**+15.7%**（補滿在長窗口較差）
  - ⇒ 現行「寧缺勿濫」在報酬上略優；`topup` 換得固定持股數與較高利用率。
- 實盤驗證（`monthly_rebalance_picker.py --as-of 2023-11-01`）：`proportional` 選 3 檔（alloc 33.33%），
  `topup` 選滿 5 檔（**2454/2412/3711/2303/6505**，alloc 20%）。
- 介面：`.env` 的 `SELFSELECT_FILL_MODE`；回測 `FILL_MODE`；已加入 `ENV_OVERRIDE_KEYS`（否則 `.env` 會蓋掉明示值）。
- 文件：`使用手冊.md` §5-2a＋參數速查、`.env.example.txt`、`策略說明.md` §J.1。
- 測試：`test/test_backtest_rebalance.py` 新增 `TestFillMode`（4 個：比例模式不補／補滿會補／不超過 N／已滿時不變）。

## 2026-10-28 · AI vs 規則 A/B 擴到 2022-2025（48 個選股日）：嚴格等量下「沒有統計優勢」

- 擴充：2023-2025 共 36 個選股日的封包一次產生（同行程共用快取，3 年約 5 分鐘；`TMP/gen_packs_bulk.py`），
  由 3 個子代理（每年 1 個）依封包作答、35 份 picks 全數通過 `parse_selection` 驗證並落地。
- 非嚴格（規則組選不滿 5 檔也照比，n=44）：1M AI **+1.88%** vs 規則 +0.19%（差 +1.69%、t=**2.18**、顯著較好）；
  3M +3.13%（t=1.79）；6M +2.76%（t=0.87）；12M +3.10%（t=0.55）。
- **嚴格等量（兩邊都必須剛好 5 檔，n=21）⇒ 優勢消失**：1M +0.90%（t=1.03）／3M +2.44%（1.05）／
  6M +1.77%（0.48）／**12M −2.81%（t=−0.40，AI 略輸）**。
- **關鍵發現（要修的是規則組，不是選股能力）**：48 個月裡有 **28 個月規則組選不到 5 檔**（多次只有 1~3 檔；
  2022-09、2024-07、2025-02 甚至 **0 檔**）⇒ 非嚴格模式的「AI 顯著較好」主要是「AI 滿倉 5 檔」贏「規則組大半時間在現金」。
- 逐年：2023 AI 明顯較好（12M +29.6% vs +8.1%、t=2.69）、2024 小幅較好（+17.4% vs +9.2%、t=1.09）、
  **2025 反而較差（12M +83.3% vs +102.0%）**、2022 混合（12M −1.9% vs +0.5%）。
- 誠實限制：AI 組是**混合口徑**（2022 模型判斷／2023-2025 子代理固定公式）；2023-2025 封包含月營收、2022 沒有；
  每月選股＋12 個月持有＝窗口重疊（有效 n 遠小於 44，t 偏樂觀）；未計交易成本；池只有 20 檔。
- 產出：`results/ai_ab_2022_2025_report.md`、`results/ai_ab_2022_2025.json`、`results/ai_ab_2022_2025_strict.json`、
  `TMP/aipick_*.json`（35）、`logs/ai_pick/<48 日期>/`、`TMP/gen_packs_bulk.py`、`TMP/validate_subagent_picks.sh`。

## 2026-10-28 · AI 選股做成「可選模式」＋D1 fallback＋寫入使用手冊

- 需求：①AI 選股做成選項，**D1 使用者必須執行；D1 沒手動執行就 fallback 原本的自動選股** ②跑 2022 全年 12 個選股日 ③寫進使用手冊。
- `SELFSELECT_AI=1`（預設 0）＋`SELFSELECT_AI_DEADLINE=13:50`：
  D1 13:36 起**不自動選股**（`should_pick` 回 None）；到期限前若使用者已完成 AI 選股（`logs/selfselect_auto.json` 的 `ai_applied=<年月>`）則不動作；**期限後若還沒完成 ⇒ D1 當天 fallback 跑原本的 `monthly_selfselect_run.py --apply`**（label 會標 `（AI 未完成 → fallback）`）。`mark_applied()` 由寫入成功後的 `.env` 更新流程呼叫（刻意放在**寫檔成功之後**）。
- `monthly_selfselect_run.py` 新增 `--picks`／`--picks-file`（外部指定名單，跳過內建選股）與 `--ai`（寫入成功後標記 `ai_applied`）；**所有既有安全檢查完全不變**（備份 `.env`、絕不刪已持倉、絕不動 keep_wait、`--sync-env-to-vm` 前 md5 比對）。
- `scripts/ai_pick_dsh.py --apply-env [--sync-env-to-vm]`：驗證通過後直接走上面那條寫入流程，一步完成「選股→落地→寫 `.env`」。
- 文件：`使用手冊.md` 新增 **§5-2b AI 選股模式**（時間軸表、兩步指令、誠實提醒）＋參數速查兩列；`.env.example.txt` 加 `SELFSELECT_AI`／`SELFSELECT_AI_DEADLINE`。
- 測試：`test/test_selfselect_scheduler.py` 新增 `TestAiMode`（6 個：預設關閉／D1 期限前等待／期限後 fallback／AI 已完成不再覆蓋／關閉時照舊／期限字串壞值退回 13:50）。全套 **720 passed**。
- 2022 年 12 個月的 AI 選股（池 20、TOP5）**已完成**：12 份封包全部產生、11 個日期由 DSH 現行模型依封包選股並通過驗證落地（`logs/ai_pick/<日期>/response.json`，model=dsh:deepseek-flash）。
  A/B（`--reuse`，等權、未計成本）：**1 個月 AI −2.40% vs 規則 −2.71%（差 +0.31%、勝率 64%、t=0.36）｜3 個月 −2.73% vs −4.01%（+1.28%、45%、t=1.03）｜6 個月 −7.48% vs −5.74%（−1.74%、45%、t=−1.05）⇒ 全部「沒有顯著差異」**（n=11；2022 是空頭年，兩邊絕對報酬都負）。
  2022-09-01 那天規則組「一個都沒選出」（過熱＋法人濾網全滅）⇒ 依 `eligible_for_compare` 不納入比較（記錄在 `skipped`）。
- 踩到的坑：**AI 名單必須用「同一個池」產生**——2022-01-03 的示範是池 50 選的，A/B 用池 20 ⇒ 部分代號不在池內被 `parse_selection` 擋掉、該日不納入比較。之後 12 個月統一用池 20（封包已按池 20 重生成）。

## 2026-10-28 · 「貼日期就用 DSH 目前的模型選股」整套流程（不需 API 金鑰）

- 需求：使用者不想另外設定模型 CLI——**在 DSH 對話框貼上選股日，就由 DSH 目前的模型選股；換模型＝在 DSH 換**。
- 新增 `scripts/ai_pick_dsh.py`（兩步、用檔案銜接，模型不必自己讀磁碟）：
  ① `--as-of <日期> --emit prompt` → 重建**當時**誠實池＋point-in-time 封包 → 落地 `logs/ai_pick/<日期>/pack.json`＋`prompt.txt`（含 sha256）；
  ② `--picks '<模型回的 JSON>' --model dsh:<模型名>` → `parse_selection` 驗證（不得新增池外標的／檔數要對／引用必須 `R#`）→ 落地 `response.json`＋`audit.json`；
  ③ `ai_pick_ab.py --reuse` 直接讀 `response.json` 納入 AI vs 規則統計（不需重跑模型、不需 API）。
- 新增 `scripts/llm_cli.py`（給想自動化的人）：`--provider openai`（OpenAI 相容 API，金鑰只放環境變數）／`--provider ollama`（本機免費）／`--provider echo`（不呼叫模型、只驗管線）；模型愛加的 ```json 圍欄會由 `extract_json()` 清掉，抽不到 JSON 就 exit 2。
- 文件：`docs/AI選股-DSH操作.md`（使用者只要貼「2022-01-03 選股」；含助理的四步、prompt 全文、換模型方式、限制）。
- 實測（2022-01-03、池 50、取 5）：封包 50 檔（PER 有、法人 null 因快取只涵蓋近期、月營收／新聞預設留空）→ 依封包選出 **2454、3034、2382、2883、2330**（每檔附理由與 `[R#]` 引用）→ 驗證通過並落地（model=dsh:deepseek-flash）→ `--reuse` 納入 A/B：1 個月 AI −2.58% vs 規則 −10.18%（差 +7.60%，n=1，樣本不足）。
- 測試：`test/test_ai_pick_dsh.py`（4：沒封包要大聲失敗／合格落地含 model 標記／池外標的 exit 2 且不落地／檔數不符 exit 2）＋`test/test_llm_cli.py`（8：JSON 抽取與 echo 管線）。
- 誠實限制不變：模型記憶無法證明無先見之明 ⇒ 這些選股是**假設**；要當證據得靠 ≥30 個選股日的 A/B。

## 2026-10-28 · A/B 嚴格等量（`--require-full`）＋新聞 point-in-time 來源（FinMind）

- `--require-full`：AI 與規則**都要剛好選滿 N 檔**才納入比較；不符合的選股日記進 `skipped` 並印原因。實測 2022-01~03（池 20、取 5）→ **2022-02-07 被排除**（規則組只有 2 檔，濾網把其餘剔除）。純函式 `core.ai_pick_ab.eligible_for_compare()`＋4 個測試。
- **新聞來源接上了**：`core/pit_news.py`＋FinMind `TaiwanStockNews`（本專案 token 可用）。每筆有到秒時間戳／標題／來源／連結；`NEWS_PROVIDER=finmind` 或 CLI `--news` 啟用。
  - **cutoff 13:30**（決策在收盤後）：當天 13:30 之後才發布的新聞對該次決策是未來資訊，**排除**（測試守住：20:00 的新聞不得進 1/3 的封包；實測 2330 於 2022-01-03 有 20 則可用新聞）。
  - 成本：**一檔一天一次呼叫**（不帶 data_id 要更高等級），故預設關、`--news-lookback` 預設 14 天、抓過就落地 `cache/news/news_<sid>_<day>.pkl`（重跑免費）、抓不到就留空並計 `misses`。
  - 順手修：A/B 的封包先前**沒帶 PER／法人**（只有價格＋營收）→ 已補（實測封包出現 PER 28.55＠2022-01-03；法人快取只涵蓋近期，故 null）。
  - 順手修：`pick_dates` 在 `--start` 不是月初時會**靜默 0 個選股日**（實測 `--start 2022-01-03` → 0 筆）→ 改成「月初早於 start 就用 start」，並加 3 個測試。
- 端到端驗證（含新聞＋strict，假模型）：1 個月 n=2、AI −2.83% vs 規則 −3.90%、差 +1.07%（樣本不足，勿下結論）——再次確認**假模型只驗流程，不是結論**。
- 全套測試 **702 passed**。

## 2026-10-28 · 口徑 profile（可選）＋月營收 point-in-time＋AI vs 規則 A/B harness

### A. 口徑做成選項：`PROFILE=conservative|fair|levered|raw`
- 需求：「全現金＝保守版、停泊＝公平版 ⇒ 做成選項讓使用者選」。
- `core/backtest_profiles.py`：四個具名口徑（保守／公平／等效滿倉／舊口徑），**明示的環境變數優先**（profile 只提供預設值）；回測腳本開頭套用並印出；名稱錯誤大聲失敗。
- `PROFILE` 等新旋鈕已加入 `ENV_OVERRIDE_KEYS`（否則 `.env` 會把明示值蓋掉——這正是 2026-10-05 事故的同類坑）。
- 驗證：`PROFILE=fair` 重現停泊版結果（正常 +66.94%）；`PROFILE=fair IDLE_CASH_ASSET=00878` 會用 00878（明示優先）。
- `scripts/backtest_profile_compare.py`：同一組設定跑多個 profile 並排（輸出 markdown）。
- 測試：`test/test_ai_ab_and_profiles.py` 的 profile 6 個（含「明示 env 優先」）。

### B. 月營收的 point-in-time 來源（FinMind，免費層可用）
- 關鍵坑：月營收的 `date` 是**所屬月份**不是**公布日**（實測 `create_time` 多為空）⇒ 若直接用 `date`，1 月中就知道 1 月整月營收＝偷看未來。
- `core/pit_data.py`：`available_from = create_time（若有）否則 次月 10 日（法定公告期限）`；只取 `available_from ≤ as_of` 的月份；算 YoY／MoM；快取 `cache/stock_revenue/rev_<sid>.pkl`。
- 新聞仍無來源：`NewsProvider` 介面＋`UnavailableNews`（明確留空，不得用模型記憶填）。
- 測試：1/2 選股看不到 2021/12 營收（1/10 才公布）、2/11 看得到且 YoY 正確、provenance 不晚於 as_of。

### C. AI 選股 vs 純規則 A/B harness
- `core/ai_pick_ab.py`（純函式）：`forward_return`（還原價、對齊交易日）、`basket_return`（等權）、`summarize`（平均差／勝率／配對 t；n<10 直接標「勿下結論」）。
- `scripts/ai_pick_ab.py`：逐選股日重建當時誠實池 → 封包（可含月營收）→ 規則組（`score_stock`＋過熱剔除）與 AI 組（`--llm-cmd`／`--reuse`）→ 1/3/6/12 個月等權報酬 → 配對彙總 → JSON。
- 端到端用**假模型**驗證流程（2022 全年 12 個選股日；假模型＝照池子順序取前 5）：1 個月差 +2.50%（勝率 75%、t=1.43、無顯著）、3 個月差 +5.10%（t=2.06）。**這只證明流程可用，不是任何結論**；真模型要使用者自己接。
- 已知差異：規則組在濾網下常選不滿 N 檔（實例 2022-09 只有 2 檔）⇒ 比的是「實際會持有的籃子」。
- 測試：`test/test_ai_ab_and_profiles.py` 的 A/B 數學 7 個（含週六對齊交易日、缺資料略過、差為 0 不除零）。
- 全套測試 **692 passed**。

## 2026-10-28 · 閒置資金停泊 0050（利用率≈100%、不借錢）＋ AI 選股可稽核外殼

### A. `IDLE_CASH_ASSET=0050`：公平比較口徑
- 問題：自選股腿常態 40%~55% 的錢在「等訊號／被大盤年線擋住」領 0%，跟永遠滿倉的 0050 比不合理。
- 做法：把**每天真正閒置的金額**（現金＋已分配未買的額度）押在 `IDLE_CASH_ASSET`，需要買股自動釋出；停泊收益＝閒置金額×該標的當日報酬−`PARK_COST`（0.2%/年），每天重算閒置金額 ⇒ 獲利滾入。**不需融資**（與 `SCALE_TO_UTIL` 的借錢放大不同）；實盤就是多持有那檔 ETF。
- 回歸：`IDLE_CASH_ASSET` 未設時與改動前**逐位相同**（2022-2025 正常 +37.01%／MDD −18.35%／夏普 0.54）。
- 結果（100 萬、TOP5、年線開）：總曝險 **100%**。**部分設定真的贏過 0050**：
  - 每年換股 2022-2026：高風險 **+258.4%**、權值 **+264.0%** vs 0050 +231.4%；2023-2026 正常 **+340.6%**、權值 +337.4% vs +322.5%；2016-2021 正常 **+203.0%**、權值 +198.5% vs +186.2%。
  - 每月換股 2022-2025：正常 +19.9% → **+66.9%**（MDD −46.4%→−38.4%、夏普 0.32→0.66）；2023-2026 正常 +304.3%（0050 +322.5%，略輸）。
  - **代價**：閒置不再是避風港，回撤跟著大盤（2022-2025 正常 −46.4%→−38.4% 但 2016-2021 月換股 −33.1%→−40.5%）。⇒ 兩個口徑都要看：全現金＝保守版、停泊 0050＝公平版；且停泊後整體是「核心 0050＋衛星自選股」，贏 0050 有一部分是核心的功勞。
- 新檔名後綴 `_park0050`；JSON 增 `idle_cash_asset`／`park_avg`／`util_total_avg`；每日曝險明細另存 `results/exposure_*.csv`。
- 產出：`results/backtest_idle_parked_0050.md`、`results/hist_windows/park_*.json`（8 份）、`TMP/run_park.sh`、`TMP/gen_park_report.py`、`TMP/blend_idle_etf.py`（離線驗算用）。

### B. AI 選股的可稽核外殼（`core/ai_pick.py`＋`scripts/ai_pick_preview.py`）
- 結論先寫：**LLM 的「無先見之明」在技術上無法證明**（訓練語料含選股日之後的事件）⇒ AI 選股只能是**假設**，不能當績效證據。
- 已實作可稽核的四件事：①只餵 ≤ 選股日的 point-in-time 封包（逐欄記錄資料日）②資料日晚於選股日 → **丟錯**（`assert_no_lookahead`）③輸出必須 JSON 且每檔引用封包編號 `[R#]`、不得新增標的（`parse_selection`）④封包／prompt／回應／模型／sha256 落地 `logs/ai_pick/<as-of>/`。
- CLI 實測：`--as-of 2022-01-03 --pool-n 50` → 重建當時誠實池（2021-11 季點、50 檔）→ 50 份封包 → prompt → 稽核落地（`pack_sha256 3f080791…`）；預設**不呼叫任何模型**，要真的選股得給 `--llm-cmd "<stdin→stdout 的 CLI>"`。
- 缺的資料一律標 `unavailable`（月營收／新聞目前無來源）；法人快取只有 41 個交易日。
- 未做（接 A/B 前的必要條件）：同日同池的 AI vs 規則 A/B harness（≥30 個選股日）、月營收/新聞的 point-in-time 來源、盲測保留期。
- 產出：`cairn/ai-stock-selection.md`（設計與紀律）、`core/ai_pick.py`、`scripts/ai_pick_preview.py`、`test/test_ai_pick_pack.py`（14 個測試：不夾帶未來資料／缺資料留空／輸出驗證／稽核 hash 可重現）。
- 全套測試 **675 passed**。

## 2026-10-28 · 訂出「正式基準＝實盤等價口徑」並改寫 README 回測段

- 使用者要求把「實盤等價」整套定成基準。口徑：100 萬、每月換股、`TOP_N=5`、`POOL_N=50`、含成本、**`MARKET_FILTER=1`**（大盤年線），另附「等效 100% 利用率」欄（`SCALE_TO_UTIL=100`）。
- 主表（2022-2025）：**正常 +37.0%（年化 8.2%、MDD −18.4%、夏普 0.54、util 56.0%）**／權值股動能 +17.9%／高風險 −6.0%／高穩定 −6.5%；**0050 +99.9%** ⇒ 四組全輸。等效 100%：正常 **+54.3%（MDD −33.2%、L=1.78）**、權值 +54.2%，夏普沒有變好（0.54→0.51）。
- 多期間（同口徑，報酬／MDD／夏普）：2022-2026 正常 +119.2%／−18.4%／0.92（0050 +231.4%）；2023-2026 正常 +160.7%／−14.2%／1.28（0050 +322.5%）；2016-2021 正常 +38.0%（0050 +186.2%）；2018 正常 −7.6%（0050 −6.1%，唯一贏的年份是「每年換股版」）。
- README「## 回測」段改寫：表格換成上表＋兩個口徑更正說明（暖機空池、缺大盤年線），重跑指令改為 `INITIAL=1000000 MARKET_FILTER=1`；使用手冊的風險組數字同步（高風險 −6.0%、正常 +37.0%）。
- 知識沉澱：`cairn/backtest-data-pitfalls.md` 新增第五、六節（短歷史暖機空池／回測缺實盤大盤年線濾網）＋實踐指南兩列。
- 產出：`results/backtest_baseline_live_parity.md`（主表＋多期間＋限制）、`results/hist_windows/base_*.json`（12 份）、`TMP/run_baseline_liveparity.sh`、`TMP/gen_baseline_report.py`。全套測試 657 passed。

## 2026-10-28 · 回測補上「大盤年線濾網」＝與實盤等價（2022 回撤 −46% → −18%）

- 起因：上一則記的口徑缺口——實盤買進前看加權指數是否在 MA200 之上（`selfselect_trader.py:819`＋`core/market_filter.py`，`.env` 的 `MARKET_TREND_FILTER=true`），**回測沒有**。
- 新增：`scripts/build_market_index.py` 逐月抓 TWSE `FMTQIK`（免 token）→ `cache/market_index/taiex.pkl`（**2,878 筆、2015-01-05~2026-10-28**；只補缺月）。回測開關 `MARKET_FILTER=1`（預設 0；**刻意不用 `MARKET_TREND_FILTER`**，因為 `.env` 已設 true，沿用會讓既有回測靜默改變）＋`MF_WINDOW=200`。判定抽成純函式 `core/backtest_rules.above_ma200()`（只用 `as_of` 以前資料；不足 200 筆→不過濾，與實盤同），行為**只擋買進、賣出照舊**。測試 `test/test_market_filter_backtest.py`（6）。`MARKET_FILTER=0` 重跑 2022-2025 與先前逐位相同（回歸通過）。
- 年線下方期間（≥10 交易日）：2015-10~2016-03、2016-04~05、2018-04、**2018-10~2019-03（106 日）**、**2020-03~06（58 日）**、2022-03、**2022-04~2023-01（199 日）**、2025-03~06（64 日）⇒ 全期 20.5% 的交易日。
- 結果（TOP5、100 萬、含成本、月換股）：**2022-2025 正常組 +19.9% → +37.0%，MDD −46.4% → −18.4%**；高風險 −21.9% → −6.0%（MDD −44.2% → −23.4%）。**但牛市末段會被擋**：2023-2026 正常組 +217.9% → +160.7%、權值 +287.2% → +181.5%；2016-2021 也變差（+53.1% → +38.0%，2020 V 轉期間被擋）。2018 單年則是改善（正常 −14.3% → −7.6%、MDD −23.8% → −17.7%）。年換股版本同理（2022-2026 正常組 +101.0% → +130.5%、MDD −39.2% → −19.7%）。
- 對 0050 的結論不變：48 個組合（6 期間 × 2 頻率 × 4 組）只有 **6 個贏過 0050**，全部集中在 **2018 空頭年**；純多頭期間最接近的是 2022-2026 每年換股權值股動能 +203.5% vs 0050 +231.4%。
- 之後看回測的預設口徑：**應該用 `MARKET_FILTER=1`**（與 `.env` 的實盤設定一致）；舊的無濾網數字當「若不啟用濾網」的對照。
- 產出：`results/backtest_market_filter.md`（6 期間 × 4 組 × 2 頻率的對照表＋檔下次數）、`results/hist_windows/mf1_*.json`、`TMP/run_market_filter.sh`、`TMP/gen_market_filter_report.py`；文件同步 `策略說明.md` §J.1。

## 2026-10-28 · 價格快取補到 2016 ⇒ 舊的 2022+ 回測數字全部作廢（重要更正）

- 動機：上一輪的「每月 vs 每年換股」只用 2022+（且那段有暖機洞）。使用者要求補 2018/2020 的快取再驗一輪。
- 工具：新增 `scripts/prepend_selector_prices.py`（dry-run 預設、`--apply` 先整目錄備份）。只補「快取第一天之前」的列，**既有列一位元都不動**（用備份逐檔比對：0 檔被改動）；用重疊日算 `ratio=舊÷新` 只縮放新增段（實測 1.000000~1.003、逐日變異 ~1e-7 ⇒ 純版本差異），接縫無假跳空。測試 `test/test_prepend_selector_prices.py`（8）。
- 結果：**578 檔補到 2016-01-04**（34 檔是 2018 後才上市、1 檔 Yahoo 查無）；逐季空池由 28 個季點降到 4 個。備份在 `cache/selector_prices_bak_prepend_*`。
- ⚠️ **更正舊數字**：補資料後 2022-2025 正常組 **+59.1% → +19.9%**、高風險組 **+25.0% → −21.9%**（0050 不變 +99.9%）。原因：2022 年 1~3 月原本是暖機空池＝**跳過了 2022 年初大跌**；現在 1 月就進場（選中 2615/3008/2603/2454 等 2021 強勢股，正是 2022 跌最兇的一批）⇒ 正常組 2022 −45.3%、2023 +41.6% 才補回。README／使用手冊／策略說明已同步並加註更正。
- 多期間結果（TOP5、100 萬、含成本）：**2016-2021 全部落後 0050（+186.2%）**，最好的是每年換股正常組 +138.2%；**2018 空頭年只有「每年換股」抗跌**（四組 −3.6%~+4.3%，0050 −6.1%，每月換股 −1.7%~−18.8%）；**2023-2026 則是每月換股勝**。⇒ 換股頻率**沒有穩定優勢**，效果完全取決於期間；先前「每月較好」的結論已撤回。
- 兩個口徑缺口（尚未修，已列 ROADMAP）：①**回測沒有實盤的「大盤年線（MA200）濾網」**（`selfselect_trader.py:819` 指數 < MA200 不買）⇒ 2018/2022 的回測比實盤更差；②法人確認資料全期只有 41 個交易日 ⇒ 該濾網從未實際生效。
- 產出：`results/backtest_multiwindow_2016_2026.md`、`results/hist_windows/*.json`（21 份）、`TMP/run_hist_windows.sh`、`TMP/run_2326_sweep.sh`、`TMP/gen_multiwindow_report.py`。

## 2026-10-28 · 新增「等效 100% 資金利用率」參數（`SCALE_TO_UTIL`／`LEVERAGE`）

- 需求：「資金利用率不到 100%，給我一個參數把使用的平均資本等效拉大到 100% 的獲利%」。
- 實作：`SCALE_TO_UTIL=100` ＝**自動多段式**（先量 `util_avg`，再放大部位使平均曝險≈100%，迭代到 2% 內）；`LEVERAGE` ＝固定倍數；`MARGIN_RATE=0.06` ＝融資年息（只對負債計息）。機制：買進金額 = 自有額度×L、超出記為 `debt`；**權益 = 現金 + 額度 + 持股市值 − 負債**；賣出/換出**先從回款扣掉融資**（否則下一輪把借來的錢當自有資金再放大 ⇒ 實測跑到 NT$545 億，已修）；負債每日計息。`LEVERAGE=1`（預設）與舊行為**完全一致**（2022-2025 四組數字回歸驗證通過）。規則純函式 `core/backtest_rules.leverage_for_target()`＋測試 `test/test_backtest_leverage.py`（4）。
- 結果（2022-2025、TOP5、每月、100 萬）：正常組 原始 +19.9%（util 81.9%）→ **等效 100%：+46.1%（L=1.22）**，但 MDD −46.4% → **−55.4%**、夏普 0.32→0.48；權值 +27.4% → +38.9%；高風險 −21.9% → −15.5%；高穩定 −4.0% → −13.7%。2016-2021 高穩定 +1.0% → **−15.4%（MDD −49.4%）** ⇒ **放大不會創造 edge，只會放大既有結果**（沒有 edge 的期間放大＝放大虧損）。夏普幾乎不變（超額部位要付 6% 年息）。
- 產出：`results/backtest_util100_leverage.md`（8 個期間 × 4 組的原始 vs 等效 100% 對照）、`TMP/run_scale100.sh`、`TMP/gen_util100_report.py`；文件同步 `策略說明.md` §J.1。

## 2026-10-28 · 換股頻率可設定（`REBAL_MONTHS`／`SELFSELECT_REBAL_MONTHS`）＋N=12×TOP_N 3~10 掃描：結論是「不要改」

- 需求：「每月選股改成每 N 個月、N 可設定（預設 1）」＋「2022~2026、N=12、TOP_N 3~10 的結果」。
- 實作：回測 `REBAL_MONTHS`（預設 1＝舊行為；選股點＝期間內第 1、N+1… 個月）；實盤 `SELFSELECT_REBAL_MONTHS`（預設 1；日曆月對齊，12⇒每年 1 月）。非選股月份**不換股**（不剔除、不補新標的），但策略訊號照常進出。輸出檔名自動帶 `_rebal{N}`／`_top{N}`（先前同窗口不同 TOP_N 會互相覆蓋）。規則純函式在 `core/backtest_rules.selection_month_starts()`；新測 `test/test_backtest_rebalance.py`（5）＋scheduler 測試 +4（共 26），相關 8 個測試檔 67 passed。
- 掃描（100 萬、POOL_N=50、含成本）：`REBAL_MONTHS` ∈ {1,3,6,12} × `TOP_N` 3~10，共 40 次回測。**公平窗口 2023-01-01~2026-10-23**（兩組同起跑點）
  - N=12 最佳：高風險 TOP7 +240.1%（夏普 1.44）／正常 TOP6 +189.2%（1.40）／權值 TOP5 +228.2%（1.38）／高穩定 TOP8 +58.6%（1.38）
  - N=1 最佳：正常 TOP7 +293.0%（夏普 **1.76**、MDD −17.8%）／高風險 TOP3 +394.2%（MDD −40%）／權值 TOP5 +258.6%（1.52）
  - 0050 買進持有 +322.5%（年化 46.0%、夏普 1.76、MDD −27.5%）
- **關鍵發現（兩個坑）**：①需求窗口 2022-2026 會讓 N=12「看起來較好」，其實是股價快取從 2022-01 開始、唯一 2022 選股日是暖機空池 ⇒ **整個 2022 用現金躲過 −20%**，不是規則的功勞（同起跑點比較後結論反轉）；②換股間隔越長，「選股日挑不足檔數」時的集中風險越大（實例：2026-04-01 權值組只選出 1 檔 ⇒ 現金全押 1 檔，N=3/TOP10 因此只有 +0.4%／MDD −38.5%）。
- 結論：**維持每月（N=1）**。年換股只在「高穩定」組勝出（+47.2%／MDD −6.4% vs +30.2%／−8.7%），且月換股正常組的 MDD 反而更小（TOP_N 6~9：−16%）。期間只有 2023-2026 大多頭，空頭未驗證。
- 回歸驗證：`REBAL_MONTHS=1` 重跑 2022-2025 基線，四組終值/報酬/年化/MDD/夏普/曝險與改動前完全相同（1250060／1591023／1015010／1286621）。
- 產出：`results/backtest_rebal_topn_2022_2026.md`（完整 4 張表＋結論）、`results/sweep_rebal_top/*.json`（40 份）、`TMP/run_sweep*.sh`／`TMP/gen_rebal_report.py`（可重跑）。文件同步 `.env.example.txt`／`使用手冊.md` §5-2／`策略說明.md` §J.1。

## 2026-10-28 · 2022-2025 回測改問「100 萬本金」：結果百分比與 50 萬完全相同（模型線性）

- 使用者問「100 萬資本、TOP_N=5」的 2022-2025 回測。用文件既有可重現指令跑（`POOL_N=50 TOP_N=5 INITIAL=1000000`），其餘口徑不變。
- 四組終值（本金 100 萬）：**正常 +59.10%（1,591,023）**／權值股動能 +28.66%（1,286,621）／高風險 +25.01%（1,250,060）／高穩定 +1.50%（1,015,010）；**0050 買進持有（含成本）+99.85%（1,998,475）**。四組仍全部輸 0050。
- 關鍵發現：**百分比報酬與 50 萬版本完全相同**（正常組 795,512 → 1,591,023 正好 2 倍）⇒ 回測模擬用零股（分數股），沒有整股取整、滑價、部分成交，所以「資本大小」在這個模型裡不影響結論。實盤 100 萬／5 檔＝每檔 20 萬，高價股的整股取整才會造成偏離。
- 兩個資料面限制（讀數字前必看）：①**2022-01~03 四組全空手**（價格快取從 2022-01-03 起、63 日動能與 52 週高仍在暖機）⇒ 2022 的 −20% 有一部分是「過熱濾網未生效」；②**法人確認只有 41 個交易日**的資料，約 980 個交易日裡絕大多數選股日該濾網實質沒作用。
- 產出：`results/backtest_2022-2025_init1M_topn5.md`（完整表格＋利用率）、`results/plan2_monthly_3group_2022-01-01_2025-12-31_immediate.json`（100 萬版）；原本 50 萬版備份在 `results/_init500k/`。

## 2026-10-28 · 對照組：個股停損 10% 與池放大到 100，在這個窗口都是負貢獻

- 同樣 100 萬、TOP_N=5、2022-2025，只改一個變數（輸出分放 `results/variants/{stop10,pool100}/`，不與基準同名覆蓋）：
  - `STOP_LOSS_PCT=10`：正常組 **+59.10% → +49.07%**（−10.0pp）、MDD 幾乎沒改善（−29.18% → −28.23%）、夏普 0.65 → 0.59；停損觸發 24 次。高風險 −4.5pp、權值 −3.9pp；只有低波動的「高穩定」組 +1.50% → +2.83%（雜訊範圍）。
    ⇒ **個股固定 % 停損擋不了系統性回撤**（平均曝險 79%、4~5 檔同步下跌），只是把虧損鎖在 −10% 並在上漲段被洗掉。要減碼應該做在指數/組合層級（現行 `MIN_DRAW_BACK` 已是這條路）。
  - `POOL_N=100`：正常組 **+24.44%**（MDD **−47.07%**）、高風險 **+1.11%**（MDD **−50.78%**）、高穩定 **−7.71%**；**權值股動能不變**（它只在 `MEGA_N=20` 裡挑，與 POOL_N 無關 ⇒ 順便驗證 A/B 沒污染其他變數）。放寬池子＝前 5 名可來自市值 50~100 名的中小型股，同樣集中度下波動與回撤翻倍。
- 與 LOG 2022-2025／50 萬版的 N=100 數字完全相同（正常 +24.44%／高風險 +1.11%）⇒ 再次確認資本規模不影響百分比報酬（模型線性）。
- 結論（限本窗口）：現行預設（N=50、無個股停損）風險調整後最佳；兩個「看起來合理」的改動都是負貢獻。**單一 4 年窗口不足以定規則**，換期間可能翻盤。


## 2026-10-28 · deploy key 驗證通過（VM 自動發佈已可運作）＋修掉 commit 沒身分的坑

- 使用者把公鑰貼進 GitHub Deploy keys（Allow write access）後，在 VM 逐項驗證：
  - `ssh -T git@github.com` → `Hi dinchentech/tw-selfselect! You've successfully authenticated`
  - sparse clone 走 SSH → `git push origin HEAD:refs/heads/tmp-deploykey-test` 成功（隨後刪除）⇒ 寫入權限 OK
  - `DRY_RUN=1 publish_dashboard.sh` → 成功 fetch、判斷「內容與線上相同 ⇒ 不用發佈」（今日已手動發佈同一份）
  - 另跑一次「clone → commit → push → 刪除」全鏈路測試通過
- **踩到潛在坑**：VM 的 git 只有 `user.name`、沒有 `user.email` ⇒ 腳本裡的 `git commit` 在 cron 環境會直接失敗（明天 13:50 就會踩到）。已在腳本把身分寫進命令列：`git -c user.name=… -c user.email=… commit`（可用 `GIT_AUTHOR_NAME/EMAIL` 覆寫），並在 VM 設了 global 身分 `tw-selfselect-dashboard <dashboard@tw-selfselect.local>`。
- VM 端 `/usr/local/bin/publish_dashboard.sh` 已更新為含 deploy-key 分支＋自帶身分的版本；cron（`/etc/cron.d/publish_dashboard`，05:50 UTC＝13:50 台北）不需改。
- 今日頁面仍為 13:45 版（真實資料）；**明天 13:45 產生新儀表板、13:50 由 cron 自動發佈**即為第一次自動發佈。
- 註：VM 上的儀表板由 Docker 容器內的程式產生（host 沒有 `.venv`），所以想在 host 手動重生要進容器，不影響 cron 流程。

## 2026-10-28 · 儀表板自動發佈改用 deploy key（不再依賴 PAT）

- 使用者選方案 2（deploy key）。`scripts/vm/publish_dashboard.sh` 改成**憑證二選一**：有 `~/.dash-deploy-key`（ed25519, 600）就走 SSH（`git@github.com:<repo>.git`＋`GIT_SSH_COMMAND` 帶 `IdentitiesOnly`／`accept-new`），否則才退回原本的 PAT＋`http.extraheader`；log 會記 `🔑 憑證：deploy key`／`pat` 與 `AUTH_MODE`。clone 用 `CLONE_URL`（deploy key ⇒ 無 token URL），fetch/push 用 `AUTH_ARGS` 陣列，避免 shell 引號炸掉。
- `scripts/vm/install_dashboard_publish.sh` 同步改：安裝前檢查「deploy key 或 PAT 任一存在」，`VERIFY_ONLY=1` 會印出公鑰與權限；都沒有時印出方法 A（deploy key，推薦）與方法 B（PAT）兩套步驟。
- 已在 VM 產生金鑰（`~/.dash-deploy-key`，600）並把新版腳本裝到 `/usr/local/bin/publish_dashboard.sh`（sudo install）。
  公鑰：`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMt4ItfMXQURKq04Cr9H1yE5JXP4oDejlkeBPllhR3un tw-selfselect-dashboard-deploy`
- **待使用者動作**：GitHub repo → Settings → Deploy keys → Add deploy key（貼公鑰、勾 Allow write access）。加入前 SSH 測試仍會 `Permission denied`；加入後 `DRY_RUN=1 publish_dashboard.sh` → 正式跑即可驗證。
- 文件：使用手冊 §5-3 改成「方法 A：deploy key（建議）／方法 B：PAT」；README「📊 儀表板」段補一行指向。

## 2026-10-28 · 線上儀表板修好：手動發佈 2026-10-28 版本（含 5 檔持倉）

- 依上一則根因（VM `~/.dash-publish-token` 0 bytes ⇒ 13:50 都跳過），今天用「本機手動發佈」補上：paramiko 取回 VM `logs/dashboard.html`（2026-10-28 13:45 版本、11,809 bytes）→ 覆蓋 `docs/index.html` → `commit 0932026` → `push origin main` → pages.yml 部署。
- 驗證 <https://dinchentech.github.io/tw-selfselect/>：最後更新 2026-10-28 13:45；持倉 5 檔（6505/4938/1301/1802/1101，全部 `auto→breakout`）、持倉市值 1,041,000、未實現 −5,300、總權益 −5,300；「缺少 holdings.json」警告消失。累積損益曲線與各標的損益仍空（尚無賣出、已實現＝0），第一次賣出後才會有資料。
- 有用的發現：**WSL 端可以直接 push**——用 Windows 的 Git Credential Manager（`git -c credential.helper="/mnt/c/Program Files/Git/mingw64/bin/git-credential-manager.exe" push`）已有 write 權限（先推一個暫時 branch 驗證後刪掉）。因此「VM token 失效」時仍可從 WSL 手動補發佈。
- 文件：使用手冊 §5-3 加「手動發佈（token 沒設／過期時的備援）」與本次實例；README「📊 儀表板」段加一行指向該備援。
- 仍待處理：VM 的自動發佈需要新的 PAT（fine-grained、Contents: Read+Write）或改 deploy key（SSH，不會過期）。

## 2026-10-28 · 線上儀表板停更的根因：VM 的 PAT 檔是空的

- 現象：<https://dinchentech.github.io/tw-selfselect/> 顯示「最後更新 2026-10-27 12:32」、數字全 0，並掛「缺少狀態檔 holdings.json（無法對帳）」警告。
- 查證（paramiko 進 VM `35.194.221.238`，快照見 `~/tw-selfselect/logs/`）：
  - `publish_dashboard.log`：10/27 12:32 成功推過一次（`38cf511`，那是 VM 還沒有 `holdings.json` 時產生的頁面 ⇒ 全 0）；之後 **10/27、10/28 13:50 都是 `⏭ token 檔為空 ⇒ 跳過`**。
  - `~/.dash-publish-token`：**0 bytes**（10/27 13:05 建立時就沒內容）。
  - cron 正常：`/etc/cron.d/publish_dashboard` → `50 5 * * 1-5 frank /usr/local/bin/publish_dashboard.sh`（05:50 UTC＝13:50 台北）。
  - VM 端資料其實有：`holdings.json` 5 檔（6505 2000、4938 2000、1301 3000、1802 3000、1101 7000）、`performance.csv` 5 筆 10/27 13:26 BUY、`dashboard.html` 已是 **2026-10-28 13:45** 版本。
- 結論：不是程式壞，是**缺少發佈憑證**；補上 fine-grained PAT（repo `dinchentech/tw-selfselect`、Contents: Read and write）到 `~/.dash-publish-token`（600）後手動跑一次 publish 即會更新 Pages（pages.yml 約 1–2 分鐘）。
- README「📊 儀表板」段補一行 troubleshooting（頁面停更先看 `publish_dashboard.log`、最常見是 token 為空）。

## 2026-10-28 · README 加上儀表板預覽

- 需求：「把 dash-board 放到 README 中」。在 `README.md`「這是什麼？」與「架構」之間新增「## 📊 儀表板」段，嵌入 `plans/assets/dashboard_real_20261026.png`（W1 教材用的 VM 實機截圖，1113×852）。
- 內容說明照 `scripts/generate_dashboard.py` 實作寫：上排數字（已實現／交易次數／本腿／未實現／持倉市值／檔數／總損益）、未平倉部位 9 欄（含「策略」＝進場當下鎖定策略）、**累積損益曲線＝已實現損益逐日累積（FIFO、含手續費與證交稅）**，並註明 13:45 產生、13:50 推 Pages（`DASHBOARD_PUBLISH=1`）與換圖方式。
- 修正自己第一版寫錯的兩處：圖表 JS 走 CDN（不是完全離線可用）、曲線只含已實現損益（未實現只在上排與部位表）。

## 2026-10-28 · W5 全部 tab 排版頁改真表格（S10/13/20/22/23，含 S12 共 6 頁）

- 依「處理 W5 即可」把 W5 剩下用 tab 對齊的頁面全部換成真表格：S10 盤整盤／震盪盤（3 欄）、S13 聯發科 2024vs2025（5 欄）、S20 參數掃描（6 欄）、S22 潛力股 TOP5（7 欄）、S23 動能選股（6 欄）；加上先前 S12 共 6 頁。
- 做法：表格內容以「run 複製」保留原格式與螢光筆（S10 的「大（寬幅）／快」、S13/S20/S22 的黃底都在）；非表格段落留在上方或移到表格下的文字框。順手修兩處原稿黏字：S22 第 5 列 index 用全形空白且「天二科技64.6」黏在一起 → 拆成 5／6834／天二科技／64.6；S23「2xx1␣␣␣xxx」缺 tab → 拆成兩欄。
- 陷阱：自建 `a:r` 時 `a:rPr/@sz` 單位是 **1/100 pt**（11pt → sz="1100"）。第一次誤用 EMU（139700）→ LibreOffice 把表格列撐爆並出現黑色方塊；修正後正常。
- `-講稿版` 與 `-配音版` 都改（配音版用 spTree 節點搬移、保留每頁音訊 pic），26 頁音訊 md5 全數相符、`<Default Extension="mp3">` 補回。
- 重出：W5 MP4 1,291 s（12:23），抽幀確認 S10、S22 等頁欄位整齊。備份 `TMP/W5_講稿版_before_tabfix_all.pptx`。

## 2026-10-28 · W5-12 改用真表格（tab 對齊在 LibreOffice 會錯位）

- 現象：使用者看影片發現 W5-12（台積電 2022/2025 四策略比較）欄位對不齊。查出該頁是用「tab＋空白」排版（`defTabSz=914400` 已設），但 PowerPoint 與 LibreOffice 對 tab 落點與字寬的計算不同 ⇒ 轉成 PNG 的影片會左右錯位（PowerPoint 內看是齊的）。
- 修法：把兩塊 tab 文字改成**真表格**——表A「年度／台積電價格／買進持有報酬／市場」(3×4)、表B「策略／2022報酬／2022損益／2025報酬／2025損益」(5×6)，數字與文字一字未改；四行結論保留為 bullet。`-講稿版` 與 `-配音版` 兩邊都改（配音版用 spTree 節點搬移，保留音訊 pic），26 頁音訊 md5 全數相符。
- 重出：W5 MP4 1,291 s（09:41），抽幀確認欄位整齊對齊；旁白未重錄。
- 同類頁面（仍是 tab 排版，未動）：W2-24、W3-15/17、W4-9、W5-10/13/20/22/23、W6-7 —— 若要一致處理可再逐頁換表。

## 2026-10-28 · 螢光筆補進 W6／W1 影片；W6-9 被存檔還原後重建

- W6：使用者 08:22 存檔把 07:18 的 W6-9 改寫（三種選股方式＋比較表）**整頁還原成舊版**（PowerPoint 開著舊版覆寫），但同時帶進 S6 的 8 處螢光筆。處理：先在 `-講稿版` 重建 S9（三行說明＋六列比較表＋口徑註），再跑 `generate_narration.sh build`（S9 講稿回到 2 分 30 秒 → 必須重配音）→ `ppt_to_mp4.sh`。結果：W6 配音 25.1 分鐘（1,504.7 s）、MP4 1,494 s；S6 螢光筆與原截圖一致、S9 表格回來。
- W1：S13 的螢光筆在講稿版是「群組內文字」、在配音版是 SmartArt（`graphicFrame`）⇒ 無法用 run 複製同步。改為**直接用講稿版當畫面來源**、沿用既有旁白出片（不重跑 TTS）：MP4 872 s，S13「說明視頻」綠底已入片。副作用：`-W1-配音版.pptx` 的 S13 仍是 SmartArt，PowerPoint 內看與 MP4 略有差異（要完全一致就得重跑 build 重配音）。
- 教訓（已兩次）：使用者在 PowerPoint 開著舊版存檔會覆蓋我對該檔的修改（W4 S25 標題/表格、W6 S9 整頁）。以後重出前先比對「講稿版 vs 配音版」的文字差異，發現被回退就先重建再產片。
- 產物：W1 MP4 872 s（08:33 前後）、W6 MP4 1,494 s（08:36 前後）、W4 1,201 s、W5 1,291 s；四份 `-配音版.pptx` 的 `<Default Extension="mp3">` 均已確認存在。

## 2026-10-28 · 「marker」＝螢光筆：把講稿版的螢光筆同步進配音版並重出 W4／W5

- 使用者澄清「marker」指 PowerPoint 螢光筆（OMML `<a:highlight>`，run 屬性，python-pptx 的 `.text` 看不到）。
- 掃描六份講稿的 `<a:highlight>` 數量後與 `-配音版` 比對，找出「使用者後來加的、影片裡還沒有」的部分：W4 S24(1)、S26(3)；W5 S10(10)、S20(2)、S25(1)。W2／W3／W6 兩邊一致；W1 S13(1) 另有差異但屬 10/26 舊帳（W1 從未重出）。
- 同步手法：逐投影片對齊 shape（排除 MEDIA）→ 逐段落比對，若該段在講稿版有任何帶 `a:highlight` 的 run，就把整段 run 由講稿版 `deepcopy` 重建到配音版（含表格儲存格；PowerPoint 存檔會重切 run，所以不能用索引對應）。W4 重建 109 段、W5 重建 135 段，兩邊 `<a:highlight>` 數完全一致；28／26 頁嵌入音訊 md5 與 `audio_44k` 相符、`<Default Extension="mp3">` 已補回。
- 重出：W4 MP4 1,201 s（08:00）、W5 MP4 1,291 s（08:04）。抽幀確認 W4 S26「每月 D1 選股後『就下場』」、W5 S10「大／快／盤整盤／震盪盤」都有黃底。
- 順帶發現並已修：使用者 07:03 的 PowerPoint 存檔把先前兩處修正還原了（S25 標題 Group1、表格 5 次），已改回「正常組」、「10 次」，配音版同步。
- 待辦：使用者截圖的 W6 S6 螢光筆不在 `…-W6-講稿版.pptx`（該檔 S6 為 0 處；W6 僅 S2/S12/S18/S19/S20 有）⇒ 需使用者存檔或提供實際檔案路徑，才能重出 W6。另詢問是否要一併重出 W1（S13 有 1 處未進影片）。

## 2026-10-28 · W6-9 補「三種選股方式」＋與母專案機械化的比較（重配音）

- 需求：「固定池／機械化／手工選股方式簡單說明一下，並比較目前自選股跟機械化的差異」。
- 定義來源（母專案教材 `文件/tw_autotrader/doc/定期定額與tw_autotrader比較.pptx` S3）：**固定池**＝年初買定 8 檔、四年不換；**機械化**＝`backtest_yearly_review.py` 的 Rule 0–3 硬規則、每年底汰弱留強、零主觀判斷；**手工（人工）**＝`backtest_manual_review.py` 逐年由人看市場資訊調整。母專案評語：機械式報酬最高但換股偏積極，人工版較穩健。
- W6-9 版面：上半三行說明（+77.6%／+195.5%／+157.2%）＋DCA 與 0050 對照；下半六列比較表（選股來源／換股頻率／怎麼決定／進場／2022-2025 報酬／能否重跑）；底部提醒「兩者不能直接比，同口徑只能比 0050 +99.9%」。
- 比較重點：本專案每月用「當時市值前 50 大」誠實池評分取前 5、每月換股（D1 選股 D2 換股）、評分＋法人確認＋過熱剔除、選股日收盤買滿（EXEC=immediate）、**+59.1%／年化 12.3%／利用率 79%／MDD −29.2%／可重跑**；母專案機械化＝人工挑的 8 檔、每年一次、Rule 0–3、**+195.5%／年化 31.1%／利用率 61%／不可重跑**。
- 重出 W6：配音 24 分 54 秒（1,494.0 s）、MP4 1,483 s（原 1,496 s）；S9 段落 855.6–1015.0 s（159 s），附錄時間表 1 分 30 秒 → 2 分 30 秒（合計 33 分 30 秒）。
- 同步 `README.md`：母專案表加上三種方式的定義與「本專案 vs 機械化」對照說明。備份 `TMP/W6_講稿版_before_S9.pptx`。
- 未取得：母專案 `backtest_yearly_review.py`／`backtest_manual_review.py` 本機沒有（`File not found`；OneDrive 備份只有 `live_trader_multi.py`），所以 Rule 0–3 的細則寫成「硬規則汰弱留強」，未逐條列出。

## 2026-10-28 · W4-26 數據口徑說清楚＋W5-26 改「第五個策略（週KD）」＋清掉殘留命名

- W4-26：使用者自行補了「平均只用了不到 8 成的資金」，但該版仍是我修正前的舊數字 → 合併重寫：`+59.1%（利用率 79%）`、`0050 +99.9%`、`落後 40.8 個百分點`、`2022 −20.6% vs 0050 −22.2%（含費用）`；並新增第 5 行「口徑」。Group1/Group 1 → 正常組。
- **口徑釐清（重點）**：這組數字是「每月選股後就下場」＝選股日當天用收盤價買滿（回測 `EXEC=immediate`，實盤對應 D2 13:25–13:30 掛單），**不是**選完等回檔、也**不是**等策略買訊（`EXEC=signal` 是另一種規則）。已寫進 S26 畫面與講稿，README 回測段同步。
- 重出 W4：配音 20 分 14 秒（1,214.0 s）、MP4 1,201 s；S26 段落 1039.9–1128.9 s。`📌` 該字型在 LibreOffice 會掉字，改 `※`（只改字不動旁白，重轉 MP4 即可）。
- W5-26：標題「試著於 Group 1備用２的策略…」→「試著於第五個策略（週KD）的位置…」，講稿改「試著在第五個策略、也就是週KD 的位置」；重出 W5 配音 21 分 42 秒（1,302.5 s）、MP4 1,291 s（原 1,270 s）。
- 殘留命名清除（依「以免使用者有疑問」）：`selfselect_trader.py`、`scripts/{make_selfselect_env,stock_selector_grid,build_historical_shares}.py`、11 個 `test/*.py` 的註解／docstring／assert 訊息，以及 `.env` 三行註解（`STOCK_NO`／`MIN_DRAW_BACK`／`MAX_DAILY_TRADES`）全部改寫成本專案用語；全庫關鍵字掃描（程式、測試、`.env`、所有 `.md`、六份投影片）＝**0 命中**。`pytest test/` **634 passed**。
- 備份：`TMP/W4_講稿版_before_user_edit_merge.pptx`（合併前）、`TMP/W4_講稿版_before_S26fix.pptx`、`TMP/W5_講稿版_before_S26title.pptx`。

## 2026-10-27 · W4 稽核：S27 不是殘留；S26 舊口徑數字／S25 Group 語言修正（重配音）

- 疑問：「W4-27 是不是母專案策略（法人動能／季度換股）沒刪掉？」→ **不是**。S27「法人確認濾網」是本專案真實功能：`scripts/monthly_rebalance_picker.py`（`--no-inst`／`--inst-days` 預設 15、`load_twse_inst_merged` 近 N 日投信＋外資淨買超>0 才入選、無資料 pass-through）、`core/inst_data.py`（TWSE T86 唯一實作）、`scripts/stock_selector_grid.py` 印「法人資料合併完成」。與母專案的法人動能、季度換股策略皆無關。
- 掃描：六份 `-講稿版.pptx` 與所有 `.md` 對母專案策略用語（抬轎／ROTATE／Group 2／live_trader_multi 等）＝ **0 命中**；程式註解與測試的舊用語當時仍在（已於同日清除，見下則）。
- 實修（重跑 `POOL_N=50` 取得當期數字：正常 +59.10%、2022 −20.57%、2023 +34.61%、2024 +7.70%、2025 +40.60%；高風險 +25.01%；0050 +99.85%）：
  - S26 總結：`+71.4%／買入持有 +81.0%／落後不到 10%` → `+59.1%／+99.9%／落後 40.8 個百分點`；`2022 空手避開` → `−20.6% vs 0050 −22.2%（含費用），只少賠 1.6 個百分點`；移除「盤整 yearly +5~15%」（實際 2023 +34.6／2024 +7.7／2025 +40.6）。
  - S25：`MAX_DAILY_TRADES` 5 次 → **10 次**（與 `.env` 一致）；講稿刪掉母專案已移除的「第二資金組」段落。
  - 兩頁「Group1／Group 1」→「正常組」。
- 重出：配音 20 分 17 秒（1,217.4 s）、MP4 1,205 s；抽幀確認 S25（10 次）、S26（新數字）正常。備份 `TMP/W4_講稿版_before_S26fix.pptx`。
- 當時未處理：W5-26 標題的「Group 1備用２」、`.env` 與程式／測試註解的母專案舊策略名——已於同日清除（見下則）。

## 2026-10-27 · W3 S3／S4 聲音與畫面錯位修正（重配音）

- 症狀：W3 第 3、4 頁「語音跟畫面接得不好，S4 太早出現」。查時間軸後確認**不是播放漂移**（每段畫面長度＝該頁 mp3 實際長度，切點 95.28s 正好是 S3 語音結束）；真因是**講稿與畫面內容對不上**＋S3 版面擠成一行一字。
- S3（切換模型）：三個 bullet 被塞進 1.8 吋寬的文字框（20pt）→ 一行一字幾乎讀不出來。改為 4 吋寬、18pt、三條短句（「右下角輸入框旁的下拉選單／統一 deepseek-flash／不要混用他廠模型」），截圖改放右側（寬 6.8e6 EMU），順手刪掉蓋在截圖上的兩個「（DSH 介面截圖待補）」殘留文字框（S3、S4 各 2 個）。
- 講稿：S3 從 23s 加長到 **35.6s**（先講下拉選單在哪、再講統一模型、再講不要混用的兩個理由）；S4 原本①②…⑥ 的順序與畫面上的六條 bullet 不一致（還講了畫面上沒有的 plan 模式、cairn/LOG）→ 改成沿畫面順序講：繁中／關瀏覽器分頁／工作目錄／技能／session 清單／WSL 執行 dsh_web，**71.0s**。附錄時間表同步（3→1 分鐘、4→1 分 30 秒，合計 27 分 30 秒）。
- 重跑 `generate_narration.sh build` + `ppt_to_mp4.sh`：配音 15.6 分鐘（938.4s）、MP4 928 s；切點 S3 74.6s→110.2s、S4 110.2s→181.3s，抽幀確認版面可讀、畫面與語音同頁。
- 備份：改版前的 `TMP/W3_講稿版_before_20261027.pptx`。W3 頁數仍 23。
- 追加（21:07）：使用者自行把講稿版 S5 錯字「開啟**心**對話」改成「開啟**新**對話」，要求更新 MP4。因旁白（S5 講稿）沒提到該字，**不必重跑 TTS**：直接改 `-配音版.pptx` 內 `ppt/slides/slide5.xml` 的 run 文字，再跑 `ppt_to_mp4.sh`（沿用既有 `_narration_…-W3-___`）→ MP4 21:12 重出（928 s）。抽幀確認 S5 顯示「按 + 開啟新對話」、S3/S4 修正未回退、影音軌等長（928.41 / 928.47 s）。
- 檢查時另發現 W3 有 4 頁（2、5、6、19）、W6 有 1 頁（14）的「（DSH 介面截圖待補）」字樣仍露在畫面上（未被截圖覆蓋），待決定是否清掉重出。備份 `TMP/W3_配音版_before_2107.pptx`。
- 已依選擇清掉：W3 第 2、5、6、19 頁與 W6 第 14 頁共 5 個「（DSH 介面截圖待補）」殘留文字框（判準＝該框與圖片重疊 <90%）。只動 `-講稿版`／`-配音版` 的版面，備註與旁白未變，故**不重跑 TTS**，直接 `ppt_to_mp4.sh` 重出：W3 21:32（928 s / 23 MB）、W6 21:39（1,496 s / 36 MB）。抽幀確認 5 頁乾淨、配音檔仍在（23／24 頁各一顆媒體、md5 與 `audio_44k` 一致）。
- 陷阱：用 python-pptx 存回 `-配音版` 會掉 `[Content_Types].xml` 的 `<Default Extension="mp3">`，存檔後要用 zip 手術補回，否則 PowerPoint 可能不認嵌入音訊。
- 待修（未動）：跨檔案替換座標時，W3 第 2 頁終端機截圖蓋住一行文字（`wsl 中先 WSL 中先執行 activate_venv`），若要修需調整截圖位置。



## 2026-10-27 · W2–W6 配音版與 MP4 全部重製（數字改完後重新配音）

- 需求：「W2-W6 請依序完成配音檔及 MP4」。全部重跑 `plans/generate_narration.sh build`（旁白寫回講稿備註）＋`plans/ppt_to_mp4.sh`。
- 結果（講稿頁數／配音時長／MP4 實長）：W2 28 頁 23:13 / 1,381s；W3 23 頁 15:09 / 909s；W4 28 頁 19:29 / 1,169s；W5 26 頁 21:10 / 1,270s；W6 24 頁 24:56 / 1,496s。W1 既有（872s）不動，合計約 1 小時 58 分。
- 旁白來源是 `-解說腳本.md`（由講稿備註產生），所以 10/27 改過的數字（正常組 +59.1%、高風險組 +25.0%、0050 +99.9%、母專案自選股 31.1%）都已在聲音裡。
- 陷阱：沙箱內 `soffice` 要寫 `$HOME/.config/libreoffice`，直接跑會在「PPTX → PDF」步驟失敗 ⇒ MP4 步驟要 `HOME=$PWD/TMP/lohome`。
- 文件：`plans/ppt/README.md` 補「配音版與 MP4」段（時長表＋重建指令＋`.gitignore` 說明），並修正 W3 頁數 24→**23**（重複的 plan 模式頁早已刪除，README 一直沒改）。
- 產物不入版控：`.gitignore` 已排除 `_narration_*/`、`*-配音版.pptx`、`*.mp4`。日誌：`TMP/narrate/{W3..W6}.log`、`*_mp4.log`。

## 2026-10-27 · 母專案「自選股」回測數據出土：README「回測」段＋W6 新頁 9

- 需求：「S7 的『同期』是什麼？母專案 tw-autotrader 回測裡年化 >20% 的數據找出來，寫進 README 與 W6」＋「專案文件不要提到母專案專屬的季度換股策略，母專案比較只比自選股」。
- 「同期」＝S7／S8 的 0050 基準與策略同一段期間：**2022-01-01～2025-12-31**（50 萬全額、含手續費）；兩頁的 0050 那行已明寫。
- 找到的母專案**自選股**數據（來源：`/mnt/c/Users/GOLF/OneDrive/...` 舊教材，2026-07-02 更新；8 檔 `PC_` 策略組合）：
  - Lumpsum 50 萬：固定池 **+77.6%**（年化 15.4%）；逐年檢討機械式 **+195.5%**（年化 **31.1%**）、人工 +157.2%（年化 26.6%）
  - DCA 每月 2 萬（4 年 96 萬）：+39.7%（機械式逐年檢討 +126%）
  - 對照 0050：Lumpsum +164.1%、DCA +89.7%；平均資金利用率 61%（每元效率 NT$2.27、0050 NT$1.90）
  - ⇒「年化 20%+」的來源是**自選股＋逐年汰弱留強**版本（31.1%／26.6%），不是固定池
- README 新增「## 回測」：本專案可重現表（正常組 N=50 +59.1%／年化 12.3%、高風險組 +25.0%、0050 +99.9%／年化 18.9%、資金利用率）＋母專案自選股表（上列）＋重跑指令與口徑警告。
- W6 新頁 9 改為「母專案自選股回測（2022-2025）」：固定池／逐年檢討／DCA／0050 對照＋口徑提醒；頁碼自動位移（現 24 頁）。文件掃描已無母專案專屬季度換股策略的敘述（README／W6／plans ppt README 都改寫）。
- 驗證：W6 24 頁 render 正常（新頁 9 目視 OK）、解說腳本重生成（24 頁、32 分 30 秒）；`grep 母專案專屬季度換股策略` 於文件為 0（程式註解／測試的歷史說明未動）。


## 2026-10-27 · 「高獲利組」改名「高風險組」（名實不符）

- 理由：2022-2025 回測實際報酬 **高風險組 +25.01% < 正常組 +59.10%**（N=50；N=100 時 1.11% < 24.44%）⇒「高獲利」名實不符。該組只留 `ma_cross`／`breakout` 兩支順勢策略，特性是**波動大**，改稱「高風險（高波動）」。
- 程式：`monthly_rebalance_picker.GROUPS["high_profit"]["label"]` 與 `backtest_plan2_monthly_3group.GROUPS[...]` → 「高風險（高波動）」；docstring／argparse 描述同步；**內部 key `high_profit` 不動**（`SELFSELECT_RISK=high_profit`、`--risk high_profit`、`.env` 都相容）。
- 文件：`.env.example.txt`、`使用手冊.md` §4、`策略說明.md`（風險組表與 `SELFSELECT_RISK` 表）都補「名稱不代表報酬較高」與 2022-2025 實測（+25.0% vs +59.1%）。
- W6：S8 標題改「選股-正常組與高風險組」、內文與講稿同步（講稿新增「改名原因」說明）；S6 風險組那行補「（高風險，名稱不代表報酬較高）」。
- 驗證：W6 S6／S8 render 正常、解說腳本重生成（23 頁）；`pytest test/` **634 passed**；`pyflakes` 無 undefined name。
- 未動：`cairn/LOG.md` 舊條目與 `core/backtest_rules.py` 的歷史註解保留舊稱（歷史紀錄）。

## 2026-10-27 · 接線 `SELFSELECT_POOL_N`（實盤候選池改 50）＋W6 S6 補「N 怎麼設」

- 需求：「選股選出最強的 N 股，這怎麼設？S6 說明一下」＋先前選 C（讓實盤真的用 50、與 S8 一致）。
- 程式：`scripts/monthly_selfselect_run.py` 新增 `--pool-n`（`resolve_pool_n`：CLI ＞ `SELFSELECT_POOL_N` ＞ 100）與純函式 `build_picker_cmd()`（把 `--pool-n` 傳給 picker）；`core/selfselect_scheduler.py` 的 `picker_command()` 也從 `SELFSELECT_POOL_N` 帶 `--pool-n`（沒設時維持 100，行為不變）。
- 設定：`.env` 加 `SELFSELECT_POOL_N=50`；`.env.example.txt` 加同鍵（預設 100＋註記 S7 回測 50 較好）；`使用手冊.md` §4 參數表加一列。
- W6 S6 改寫：新增「N（持股檔數）怎麼設」——N＝`SELFSELECT_TOP_N`（預設 5）、評分排序後只買最強 N 檔、每檔 `alloc＝SELFSELECT_LEG_PCT ÷ N`（100÷5＝20%）、並釐清 `--pool-n`（候選池「從幾檔挑」）≠ N（持股數「留幾檔」）；S7 來源列補「持股固定 top 5」避免誤會。
- 驗證：新增 5 個測試（`resolve_pool_n` / `build_picker_cmd` / scheduler `picker_command`）→ `pytest test/` **634 passed**；runner 實跑確認 `--pool-n 50` 有傳到 picker（輸出「候選池: 當時市值前 50 大（50 檔）」）；W6 S6/S7 render 正常、解說腳本重生成（23 頁）。

## 2026-10-27 · W6 S4 改寫：潛力股掃描＝參考用、進場用 keep_wait

- 需求：「S4 潛力股掃瞄要說明這是給使用者參考用；有合適的潛力股可以手動用 keep_wait 買入」。
- S4 改寫：定位改成「**參考用、不會自動買進**」；保留 `catalyst_score()` 四維權重與「實盤 `catalyst_weight` 預設 0」；新增「看到合適 ⇒ 手動用 keep_wait」三步：① `.env` 加 `PC_<代號>={"strategy":"keep_wait","alloc":15,"max_entry_price":580,"initial_shares":12}` ② keep_wait＝低接＋DCA 加碼＋分層停利（參數見策略說明 §9.5／§9.6）③ 選股程式**不增不刪 keep_wait 條目**（人工管理）⇒ 不會被每月換股汰換；保留「高分≠買進訊號」警告。
- S5 註記補一句「要進場請手動用 keep_wait（見上一頁）」。
- 驗證：S4／S5 render 正常；W6 解說腳本重生成（23 頁）。

## 2026-10-27 · 補「資金利用率」提醒（W6 S7/S8＋使用手冊）

- 需求：使用者提醒「50 萬是名目本金，實際上平均只動用 30 多萬（利用率不到 8 成）」，要求對使用者說清楚。
- 實測（2022-2025、NT$500,000、每月換股、現行快取）：平均曝險（÷當下權益）正常組 N=50 **79.1%**／N=100 76.4%／N=150 72.3%；高獲利 N=50 **76.1%**／N=100 75.2%；平均動用金額 **33.0–41.8 萬**（尖峰 100%）。
- W6 S7 加註：「50 萬是名目本金，平均資金利用率 72–79%（實際平均只動用約 33–42 萬）；0050 是 100% 曝險」；S8 加註「平均資金利用率 79.1%／76.1%（不是滿倉）」。兩頁講稿同步補「輸給 0050 是對名目本金說的，策略實際只動用七成多」。
- `使用手冊.md` §9 新增已知限制：回測本金＝名目本金、須附資金利用率（指向 `策略說明.md` §6.5）。
- 驗證：S7/S8 render 正常（S7 較滿但無溢位）；W6 解說腳本重生成（23 頁）。

## 2026-10-27 · VM 同步 cache＋補 0050 歷史＋W6 S7/S8 補上買進持有基準

- 需求：「VM_sync_cache 補上」——把 0050 買進持有基準補回來，重跑 S7/S8。
- 同步：VM 原本 TERMINATED ⇒ `gcloud compute instances start`（沙箱對 `~/.config/gcloud` 唯讀，改用工作區內 `CLOUDSDK_CONFIG` 副本）；SSH 被 `/etc/ssh/ssh_config.d`（nobody 擁有）擋住 ⇒ 改用臨時 venv 的 **paramiko** 拉 `~/tw-selfselect/cache`（tar 49MB、VM cache 94MB／612 檔），解壓覆蓋本機 cache（先備份 `TMP/cache_backup.tgz`）。同步後 VM 已再 stop 回 TERMINATED。
- 但 **VM 的 0050 快取同樣只有 2026-02-23 起 167 天** ⇒ 同步補不到基準；改抓 yfinance 0050 還原價 2015→2026（2873 筆、ratio 1.0、接縫 +0.26%）寫回 `cache/selector_prices/0050.pkl`（`dump_cache` v2）。
- 重跑（2022-2025、NT$500,000、每月換股）：**0050 買進持有 +99.85%**（年化 +18.91%、MDD -34.0%、夏普 0.93）；正常組 N=50 +59.10%／N=100 +24.44%／N=150 +34.15%；高獲利組 N=50 +25.01%／N=100 +1.11% ⇒ **所有選股組都輸給 0050 買進持有**。
- S7/S8 更新：兩頁都加「0050 買進持有（同期）+99.85%」與「三個 N 都輸給它／兩組都輸給它」；講稿同步（S7「先跟基準比」、S8「這段期間最好的選擇其實是買 0050」）。
- 待辦：0050 歷史只補在本機，VM 的 cache 仍缺（若要在 VM 跑回測需再補）；`/etc/ssh/ssh_config.d` 權限是 nobody:nogroup，會讓一般 `ssh`／`gcloud compute ssh` 失敗，值得另外修。
- 驗證：S7/S8 render 正常；W6 解說腳本重生成（23 頁）；`pytest test/` 629 passed。

## 2026-10-27 · 修月頻回測工具（0050 日曆 bug）＋W6 S7/S8 換成可重現數字

- 需求：「A」＝先修 `backtest_plan2_monthly_3group.py` 的 0050 日曆 bug，再用現行四組重跑、把 W6 S7/S8 換成可重現版本。
- 修 bug（`scripts/backtest_plan2_monthly_3group.py`）：①交易日曆原本只取 0050 快取（現在只有 2026-02-23 起 167 天）⇒ 2022-2025 的選股日 `sel_date` 全 None ⇒ **靜默 0 筆交易**；改成「所有標的日期聯集」，0050 只當備援。②`main()` 的 0050 基準在快取不足時 `IndexError`；改成印「略過：0050 快取沒有涵蓋本次回測期間」。
- 重跑（2022-2025、NT$500,000、每月換股、含手續費＋證交稅、現行快取）：
  - N=50：正常 **+59.10%**（終值 795,512；2022 −20.57／2023 +34.61／2024 +7.70／2025 +40.60；MDD −29.2%、夏普 0.65）｜高獲利 +25.01%（625,030；−21.53／+46.66／−4.59／+16.31）
  - N=100：正常 +24.44%（622,189；−21.68／+50.91／−8.75／+15.28）｜高獲利 +1.11%（505,575）
  - N=150：正常 +34.15%（670,734；−35.10／+32.74／+19.36／+29.44）
- S7 改寫：N=50/100/150 表（正常組）＋資料來源與切換方式（回測 `POOL_N`、實盤 `--pool-n`）；講稿重寫（明講與舊版 +575% 不同、0050 基準不可用）。
- S8 改寫：標題改「選股-正常組與高獲利組」、列兩組年度報酬（N=50），結論＝高獲利 2023 衝高但 2024/2025 落後，四年總報酬僅正常組四成多。
- 驗證：S7/S8 render 正常；W6 解說腳本重生成（23 頁）；`pytest test/` 629 passed；pyflakes 僅剩既有的未使用變數。

## 2026-10-27 · W6 S6 改寫（現行選股引擎）＋S7/S8 數字溯源

- 需求：「好」＝S6 改成現行風險組說明，並核 S7／S8 的 N=50/100/150 數字來源。
- S6 改寫：標題「選股引擎：每月一次」；內容＝入口（`monthly_rebalance_picker.py`）、兩風險組（normal／high_profit）、`score_stock()` 四維權重（動能 2.0／技術 0.3／穩定度 0.5／催化劑 0）、誠實池 `--pool-n 100`、法人確認／過熱剔除／總數上限、輸出（賣出／維持／買入、fixed／auto、`PC_`、`logs/monthly_pick.json`）；備忘稿重寫並明講舊 `--recommend` 已不存在。
- S7／S8 溯源（**不能重現**）：①「純動能／核心+衛星」模式與 `--recommend --mode …` CLI 都已移除，現行只有 normal／high_profit／stable／megacap 四組。②現行回測工具 `backtest_plan2_monthly_3group.py` 有潛在 bug：交易日曆取自 0050 快取（`ssg.load_stock("0050")`），而 0050 快取現在只從 2026-02-23 起（167 天）⇒ 2022-2025 的 `sel_date` 全為 None ⇒ **0 筆交易、+0.00%**，收尾的 benchmark 還 `IndexError`。③把日曆改成「全部資料日聯集」後，`normal` N=50（2022-2025）實跑 **+59.1%**（2022 −20.6%／2023 +35.0%／2024 +6.3%／2025 +39.7%），與 S7 的 +575.2%（2022 −3.3%）差距過大 ⇒ S7／S8 應是舊工具＋舊快取結果，無法驗證。
- 未改 S7／S8 內文（等指示：修工具重算／標記為歷史／刪除）。
- 驗證：S6 render 正常、W6 解說腳本重生成（23 頁、31 分鐘）。

## 2026-10-27 · W6 S4/S5 換成現行催化劑說明＋頁碼校正

- 需求：「1+2」＝S4／S5 從已移除的 `find_catalyst_stocks.py` 換成現況，並校正 W6 頁碼。
- 查證：`find_catalyst_stocks.py`、`selector_workflow.py`、`stock_selector_grid.py --recommend` 都不存在（selector 只剩函式庫，入口是 `monthly_rebalance_picker.py`）；催化劑評分只剩 `stock_selector_grid.catalyst_score()`，且 `DEFAULT_PARAMS.catalyst_weight = 0` ⇒ 實盤每月選股不看它。
- S4 改寫：催化劑評分四維度＋公式（盤整 20%／突破 35%／量能 15%／動能 30%，130 天＝前後各 65 天），並明講「只有函式、實盤權重 0、要啟用請自行調高再回測」。
- S5 換頁：移除舊截圖，改成**目前 5 檔自選股（6505／1301／1101／4938／1802）在 2026-10-23 的催化劑分數實算表**＋註記（高分只是有潛力、不是買點）；講稿重寫（6505 vs 1802 對照）。
- 頁碼：第 5 頁頁碼欄位快取文字 `4` → `5`（顯示本來就是 5，修正是讓產生的講稿標題正確）；第 17、18 頁原本沒有頁碼 → 補上（24pt bold Century Gothic，位置避開標題）。
- 驗證：soffice→PNG 目視 4／5／17／18 無溢版、頁碼不壓字；`notes_to_script.py --force` 重生成 W6 解說腳本（23 頁，31 分鐘）。
- 未動（待確認）：S6 仍寫 `stock_selector_grid.py --recommend --mode catalyst`（該 CLI 不存在）；S7／S8 的 N 比較數字來源未核。

## 2026-10-27 · W6 第 3 頁改寫：每月自動選股流程

- 需求：「W6-S3 說明目前自選股的每月自動選股流程」。
- 改寫：標題改「再談選股：每月自動選股流程」；內文由舊「工具總覽」（列了已不存在的 `find_catalyst_stocks.py`／`selector_workflow.py`）改成現行流程＋濾網＋安全帶：
  - ① D1 13:36–13:55 程式：補資料 → 選股 → 改寫 `.env`（先備份）→ TG；② D1 晚～D2 13:25 人可 `--exclude` 宣告式剔除；③ D2 08:05–08:39 補跑（趕上 08:40 熱重載）；④ D2 13:25–13:30 `immediate` 買新名單。
  - 四道濾網：誠實候選池（當時市值前 100，歷史股本×當季股價）→ 法人確認（近 15 日買超）→ 過熱剔除（離 52 週高點 ≤7%、YTD ≤100%、PER ≤45，命中 2 項）→ 總數上限 N（只補 N−已持倉，預設 5；每檔 alloc＝腿額度÷N）。
  - 安全帶：預設 dry-run、`--apply` 才寫檔（自動備份）、絕不刪已持倉、`keep_wait` 不增不刪、基準日落後拒絕寫入。
- 依據：`core/selfselect_scheduler.py`（D1/D2 時窗、補跑）、`scripts/monthly_selfselect_run.py`（步驟 0–4）、`scripts/monthly_rebalance_picker.py`（風險組／法人／過熱／N 上限）、`使用手冊.md` §3。
- 備忘稿重寫後 `notes_to_script.py --force` 重生成 W6 解說腳本（23 頁，31 分鐘）。
- 順帶發現（未動）：W6 S4／S5 仍引用不存在的 `find_catalyst_stocks.py`；S5 的頁碼文字是「4」（md 標題因此顯示 slide-5 4）。W6 目前版本本來就比 git HEAD 新（使用者的編輯），本輪只碰第 3 頁。

## 2026-10-27 · W5 全面對齊新口徑（又修 3/4/6/7/8/14/21 頁）

- 起因：「W5 中還有哪些數據與現在四個策略不符，一併更正」。掃全 26 頁，除前兩輪的 12–20 外又找到 6 類不一致。
- S8（台積電 2025 1–6 月四策略）：表格換新口徑（VWAP −5.61%、均線 +13.13%、布林 −9.19%、突破 0 筆 0%；月度＝該月損益÷50 萬、加總＝半年）。右下「重點觀察」原本是 **image8.png 的圖片填滿**（python-pptx 讀不到文字，grep 也找不到）⇒ 改成可編輯白色文字框並依新數字重寫（VWAP 2/14 進 1060→5/2 出 950、三月 −12.97% 是持倉損失；布林 2/27 進→5/2 出；均線 4/30 進 908→6/6 出 995；突破整半年零訊號）。
- S14（聯發科走勢圖）：圖內「四策略表現」是舊 2024 數字、分段漲幅也是舊版 ⇒ 用 FinMind 原始價重畫（股價黑線＋突破策略實際持倉區段與買賣點），備忘稿改「色塊＝持倉區段」。舊圖 image10.png 成孤兒（不影響）。
- S3／S7：標的清單「8 檔」→ 依 `config/symbols.py` 改「12 檔」（2330/2454/2317/2881/2382/2886/0050/0056/00632R/00646/006208/00878）。
- S4：模式二「四種策略」→「四個內建策略＋週KD、買進持有」；「交易次數／平均報酬」→「買賣次數／報酬率」＋`--years` 與 CSV；適用場景改「各策略」。S6：註記「模式一～三僅支持策略１～４」→「模式一～三為單一策略／單一標的；模式四才是多策略投資組合」。
- S21：SOP 第六步引用的 `live_trader_finmind.py` 已不存在 → 改 `selfselect_trader.py（ESUN_ENVIRONMENT=simulation）`，備忘稿同步。
- 確認不必動：S5／S11（文字描述）、S9（雙巴示意圖無數據）、S10（示意價格）、S22–S24（選股工具數據，與四策略無關）。
- 驗證：soffice→PDF→PNG 逐頁目視 3/4/6/7/8/14/21 無溢版（26 頁不變）；`notes_to_script.py --force` 重生成解說腳本（diff 只在 3/4/6/8/12/13/14/18–21）。

## 2026-10-27 · W5 簡報 12–13 頁重跑（四策略 2022/2024/2025 換成新模式口徑）

- 需求：「1.重跑一下更新數據」——把 12–13 頁（台積電 2022/2025、聯發科 2024/2025 的四策略表）換成與 18–20 頁相同的真實部位口徑，避免同一份簡報兩套算法。
- 重跑：FinMind 原始價、500,000 本金、單一部位（空手才買、滿倉不重複買）、買 0.1425%／賣 0.4425%、各年 1/1 起算。
- 2330：2022 均線 −3.71%（−18,553，5/5）｜VWAP −22.99%（−114,927，4/4）｜布林 −12.61%（−63,044，4/4）｜突破 −10.55%（−52,748，1/1）｜買進持有 −29.33%（−146,639）；2025 均線 +54.79%（+273,925，7/7）｜VWAP +0.55%（3/3）｜布林 −0.42%（2/2）｜突破 0.00%（0 筆）｜買進持有 +44.61%（+223,060）。
- 2454：2024 均線 +31.76%（+158,811，6/6）｜布林 +16.64%（2/2）｜突破 +13.33%（3/3）｜VWAP +11.71%（3/3）｜買進持有 +43.32%（+216,581）；2025 布林 +9.81%（2/2）｜VWAP −0.06%（2/2）｜突破 −3.21%（3/3）｜均線 −27.76%（9/9）｜買進持有 +5.30%。
- 結論改寫：S12「均線交叉兩年都優於買進持有（合計 +NT$255,372），逆勢策略空頭接刀、多頭抓不到主升段，突破 2025 零交易」；S13「突破＝時機型（2024 +13.33%、2025 −3.21%），但 2024 最好其實是均線交叉 +31.76%，突破只排第三」。
- 格式：S12 四條 bullet 統一（去掉殘留黃底、加回項目符號）；S13 只保留結論第一行黃底；soffice→PDF→PNG 目視 12/13/18 無溢版。備忘稿重寫後 `notes_to_script.py --force` 重生成解說腳本（diff 只在 12–13、18–20 頁）。

## 2026-10-27 · W5 簡報 18–20 頁改用新損益口徑（數字＋結論重寫）

- 需求：「用目前新的結果更新 W5 簡報 18–20 頁的數字，也更新相關結論」。
- 做法：改 `plans/ppt/…W5-講稿版.pptx` 的三頁（表格／文字框／備忘稿），再用 `plans/ppt/notes_to_script.py --force` 重生成 `…W5-解說腳本.md`（diff 只在 18–20 頁）。
- S18 表格改為真實部位損益（單一部位、全額投入、含手續費），BUY 欄改「買/賣」，列依合計損益排序：突破 −46,906（2/2、3/3）｜布林 −80,130（4/4、2/2）｜週KD −117,195（3/3、0/0）｜均線 −138,820（5/5、9/9）｜VWAP −192,116（4/4、2/2）｜買進持有 −203,286。表格欄寬（首欄 1.48"）與字級 12pt 調整避免數字折行。
- S19 結論改寫：週KD 由「第 5 名、小虧 3,718」改為「第 3、−117,195」；原因是訊號太少＋門檻 30 太嚴——2022 三筆都在下跌段（843→670、717→623、585→660 只有第三筆賺），2025 零訊號（11-28 反彈週 K=36.3 > 30 被擋），門檻放寬 40 才會買（+9,526）。
- S20 參數掃描改掃 kp 6–24 × kt 15–60 × dp 2–6，最佳 15/20/2：2022 +102,859（2 筆都賺）、2025 0（空手），合計 +102,859 是五策略唯一正報酬；結論由「週KD 沒有 VWAP 好」翻成「調參後週KD 最好，但只靠 2022 兩筆、樣本太小，不能當穩定優勢」。
- 口徑提醒：18–20 頁現在是模式二（真實部位）口徑；12–13 頁（台積電 2022/2025、聯發科 2024/2025 四策略）仍是舊「買訊隔日漲跌加總」口徑，本輪未動，兩組數字不可直接比較。
- 驗證：soffice→PDF→PNG 目視 18–20 無溢版（表格數字不折行）；程式未動，`pytest test/` 仍 629 passed。

## 2026-10-27 · 2454 2022/2025 五策略損益比較（`backtest_finmind.py` 擴充）

- 需求：「2022、2025 年聯發科用週 KD 跑跑看，跟 4 個策略（不含 keep_wait）比較損益／買賣比數」。
- 工具：`backtest_finmind.py` 擴充成 7 列（4 內建＋週KD 9/30/3＋週KD 12/25/5 調參＋買進持有），新增 `--symbol/--start/--end/--years` CLI 與 `results/` CSV；`compute_backtest` 口徑改為**單一部位**（空手才買、滿倉不重複買、買訊投入 100% 現金、賣訊全出、期末平倉計入賣出），回傳 `buys/sells/win_rate/final_equity/total_return`。⚠️ 模式二口徑變更（原為每次買訊投入 50% 現金、可重複加碼）。
- 資料：FinMind 原始價（未還原權息）、資本 500,000、買 0.1425%／賣 0.4425%（含證交稅）；逐年各自從 1/1 起算（指標各自暖機）。
- 結果（2454，合計＝兩年相加；買/賣為實際成交次數）：VWAP −192,116（2022 −191,794／4/4；2025 −323／2/2）｜均線交叉 −138,820（−33／5/5；−138,787／9/9）｜布林 −80,130（−129,171／4/4；+49,041／2/2）｜突破 −46,906（−30,832／2/2；−16,073／3/3）｜週KD 預設 **−117,195**（2022 −117,195／3/3；2025 0／0/0）｜週KD 12/25/5 −52,601（2/2；0/0）｜買進持有 −203,286。
- 觀察：2025 週 KD 零訊號——2025-11-28 反彈週 K=36.3（> 門檻 30），低檔金叉被門檻擋掉；`k_threshold` 放寬到 40 就會買（+9,526、1買1賣）。2022 三筆買進（05-13 843→06-24 670、08-05 717→09-08 623、10-14 585→12-23 660）只有第三筆賺。
- 口徑差異：W5 簡報 18–20 頁那組（VWAP +105k、突破 +38k、週KD −3,718…）是**模式一**「買訊隔日漲跌加總」算的（不計持有期／出場／手續費）；用模式二重算結論會翻（VWAP 從最佳變最差）。簡報未改，待確認見下方條目。
- 測試：新增 `test/test_backtest_finmind_compare.py`（5 個）；`pytest test/` 624 → 629 passed。

## 2026-10-27 · `g1_strategy_2` 週 KD 策略：審計＋封週對齊

- 需求：「用 g1 備用2 完成週 KD 低檔黃金交叉策略」（W5 slide-15）。審計結論：範本早已實作需求全部規則（週 K 聚合、KD(9,3,3)、K<30 低檔金叉買、死叉賣、+1/−1 狀態機、參數白名單、文件、7 個回歸測試），**不需重寫**。
- 唯一實質缺口：實盤每輪用「今天」那根日 K 重算週 KD（`selfselect_trader.py:574-609`），未收完的週也可能金叉 ⇒ 週三就買；回測只在該週最後交易日發訊號。實測截到 2019-02-18（週一）在未擋封週的版本會發買訊、同週週五才該發。
- 修法：`core/trading_calendar.TradingCalendar.is_last_trading_day_of_week()`（週一～週日口徑、含國定假日、非交易日回 False）＋ `user_strategies._is_week_final()`（日曆壞掉退回「週五才算封週」）；週 KD 狀態機後把未封週的訊號歸零（只有資料最後一週可能未封，已收盤週不受影響）。
- 測試：`test/test_weekly_kd.py` 7 → 12（門檻 0/30/100 買進數＝0/6/51；700 根下跌後單邊上漲只 1 買 0 賣；訊號只在週最後交易日；2019-02-18 週一不發、02-22 週五發；週五放假→週四為該週最後交易日）。`pytest test/` 619 → **624 passed**；CI 的 `unittest discover` 亦綠。
- 回歸：2454 快取資料（末日週五）訊號完全不變＝2022-05-13／07-22／10-14 買、06-24／09-02／12-23 賣；`backtest.py --strategy g1_strategy_2 --symbol 2454` 預設 6 筆、參數 12/25/5 為 4 筆（CSV 在 `results/`，已 gitignore）。
- 文件：`策略說明.md` §3／§4.1／附錄F、`使用手冊.md` §策略選擇 補「只在該週最後交易日、未封週不發訊號」。未改 `.env`（實盤仍 5 檔 `auto`）。
- 待確認：W5 18–20 頁週 KD 數字與現行資料源重跑不一致（FinMind 2454 2022：VWAP −29.7%、週 KD 預設 −57,487；簡報為 +3.64%、−3,718），疑為當時腳本／資料版本不同，未動 PPTX。

## 2026-10-27 · W4-S22/S23 keep_wait：說法修正＋`max_additions` 語意與記帳修正

- 起因：使用者指出「W4 第 23 頁關於 keep_wait 的說法不太對」。逐條對程式確認三處不符，使用者指示「程式也修、S22 也改」。
- ①（原）「改參數只影響後續加碼與資金滾入，不會立刻賣」⇒ 錯。keep_wait 分支每輪都重算 `profit_pct`（`selfselect_trader.py:723`），停利門檻調低到現價已達標會在**下一輪（≤1 分鐘）立刻停利**；只有調高才不會賣。
- ②（原）「DCA 最多 `max_additions` 次」⇒ 程式不符。`buy_count` 在初始建倉／偵測既有持股就設 1（`:674`, `:680`），而條件是 `buy_count < max_additions` ⇒ 預設 2 實際只加碼 1 次。**已改程式**：`:747` 改判 `(trk['buy_count'] - 1) < kw_max_add`，語意＝「加碼次數，不含初始建倉」，文件／投影片的說法因此成立。
- ③（原）「下個交易日 09:00 孤兒清倉會賣掉」⇒ 太窄。實際是交易日 **09:00–13:30**（`intraday_trade_window`）內每檔每日只試一次；「先賣到 0 股」還必須讓 `logs/holdings.json` 歸零，否則刪條目後會對不存在的股數下賣單。
- 順帶修（同段程式）：`++buy_count`／`last_buy_price`／`total_cost`／`total_shares` 原本寫在 `if max_entry_price 擋價` 的 if/else **之外** ⇒ 被擋掉那次也吃掉一次加碼額度、還把沒發生的交易記進均價與股數。已移入 else。
- 測試：新增 `test/test_keep_wait_dca_count.py`（AST 抽出實盤那行判斷式重跑：2 次加碼／0 次／1 次＋回跌門檻＋擋價不得更新 tracker）；全套 `pytest test/` **619 passed**。
- 投影片：W4-S23（4 bullet＋表格＋備註，字級 21.7→18.5、區塊上移）；W4-S22（表格改用實際 `PC_` 鍵名，原 `KW_*` 舊名已不存在；加碼基準「從均價」→「從上次買價」；冷卻改「賣光後」；動作欄加寬 1.85"）。兩頁轉 PDF 目視確認不溢出。
- 文件：`策略說明.md` §9.2／§9.3／§9.4（範例＋📌 更正註）／§9.9 ②④；`使用手冊.md` §5-2（keep_wait 停利屬分鐘級，不受 13:25–13:30 窗口限制）；W4 解說腳本 S22／S23。
- 指標：`selfselect_trader.py:747`、`core/live_utils.intraday_trade_window`、`test/test_keep_wait_dca_count.py`。

## 2026-10-27 · 台塑化（6505）近一年走勢圖 HTML（一次性產出）

- 需求：給一份可直接開的走勢圖 HTML，放 `results/`。
- 產出：`results/6505_台塑石化_近一年走勢圖.html`（單檔、無外部依賴，資料內嵌）、`results/6505_daily.csv`（原始日線）、`results/6505_走勢圖預覽.png`。
- 做法：FinMind `TaiwanStockPrice`（6505，2025-10-27～2026-10-22，241 交易日）→ 手寫 SVG K 線 + MA20/MA60 + 成交量 + 十字游標 tooltip，漲紅跌綠、繁中軸標。
- 驗證：node 打樁跑過整段 JS（無 NaN/undefined）＋ Windows Chrome headless 截圖目視。
- 可重用技巧：WSL 內 `/mnt/c` 唯讀，但 Windows Chrome 可寫 UNC 路徑 ⇒ `chrome.exe --headless=new --screenshot='\\wsl.localhost\ubuntu\<repo>/x.png' '\\wsl.localhost\ubuntu\<repo>/x.html'` 直接把截圖存回 repo，不必對 `/mnt/c` 提權。
- 觀察：2026-10-27 查詢時 FinMind 全部個股日線都只到 **10-22**（2330／0050 同樣）⇒ 資料源延遲，不是查詢條件問題。

## 2026-10-27 · 儀表板自動發佈到 GitHub Pages（等 token）

- 需求：公開頁只認 `docs/index.html`，而 `pages.yml` 只在「push 到 main 且改到 docs/」時部署；儀表板 13:45 才產生 ⇒ 中間沒有橋，頁面一直停在手動更新那天。
- 做法：新增 `scripts/vm/publish_dashboard.sh` + `install_dashboard_publish.sh`；VM 上另建只取 `docs/` 的 sparse clone `~/dash-publish`（部署目錄沒有 `.git`，不能直接 commit）。
- 排程：台北 13:50、週一至五（cron UTC `50 5 * * 1-5`）——13:45 產生、14:00 關機，13:50 是唯一安全窗。
- 狀態：腳本已安裝到 VM，但**尚未設 token** ⇒ 安裝器刻意不加 cron（避免每天空跑）。缺 `~/.dash-publish-token`（fine-grained PAT，Contents: Read and write）。
- 開關：`.env` 的 `DASHBOARD_PUBLISH`（預設 `0`＝不公開，`1`＝公開）。使用者選「完整公開」，本機與 VM 的 `.env` 均已設 `1`；腳本每次重讀 `.env`，關掉下一輪就跳過。
- ⚠️ 公開的是完整儀表板（股數／成本／總資產）⇒ 切 `ESUN_ENVIRONMENT=real` 前必須改回 `0`。
- 指標：`cairn/deploy-pipeline.md` §儀表板自動發佈、`scripts/vm/*dash*`。

## 2026-10-27 · VM 守門員納入版控 + 補 deploy-pipeline 知識檔

- 把原本只存在 VM `/usr/local/bin` 的三支腳本收進 repo：`scripts/vm/tw_watchdog.sh`、`tw_restart_guard.sh`、`auto_shutdown.sh`。
- 新增唯一安裝入口 `scripts/vm/install_vm_guards.sh`（idempotent：安裝檔案 + root crontab + `/etc/cron.d` 兩支；`VERIFY_ONLY=1` 只檢查）。已在 VM 實跑一次，驗證 watchdog `exit=0` 不誤報、restart_guard 正常計次。
- `deploy_source.sh` 加 `INSTALL_GUARDS=1`：部署時可順帶同步守門員（預設不做，避免部署腳本動 root 設定）。
- 新增 `cairn/deploy-pipeline.md`：部署六步、`tw-autotrader`／`tw_autotrader_bot`／`tw_selfselect_bot` 三個名字的區別、守門員排程與驗證方式、2026-10-02 崩潰迴圈與 2026-10-27 假告警兩次事故。
- 修掉一個漂移註解：`/etc/cron.d/auto_shutdown` 原本指向不存在的 `scripts/vm_set_auto_shutdown_cron.sh`（git 與 VM 都查無此檔），改指向 `scripts/vm/install_vm_guards.sh`。

## 2026-10-27 · 雲端 watchdog 綁著母專案容器名，天天假告警（已修）

- 症狀：Telegram `⚠️ TW AutoTrader 容器未運行，已自動重啟（watchdog）` 每 5 分鐘一則；10-26 觸發 **115 次**、10-27 到 11:15 已 **38 次**。
- 根因：VM 上 `/usr/local/bin/tw_watchdog.sh`（root cron `*/5`）檢查 `CONTAINER_NAME="tw_autotrader_bot"`、讀 `~/tw-autotrader/.env`——那是拆出 tw-selfselect **之前**的雲端部署名；現在的容器是 `tw_selfselect_bot` ⇒ 每輪都判「未運行」，`docker start` 失敗（`No such container`）後照樣發通知。
- 連帶風險：該腳本的行為是「沒跑就 `docker start`」。若日後回滾或手動建了 `tw_autotrader_bot`，它會**主動拉起母專案 bot 跟 selfselect 搶同一個玉山帳號**（`使用手冊 §部署`：同一券商帳號不能兩隻 bot 同時下單）。
- 同時發現 `/usr/local/bin/tw_restart_guard.sh`（2026-10-02 崩潰迴圈事故後加的守門員）也綁舊容器名 ⇒ 一直在「略過」，**真正的保護是失效的**。
- 處置（VM 上，均已備份 `*.bak-20261027`）：兩支腳本改指 `tw_selfselect_bot`／`~/tw-selfselect/.env`、訊息改 `TW SelfSelect`、重複實例比對 `live_trader_multi.py` → `selfselect_trader.py`、移除硬編的 Telegram token fallback（讀不到只寫 log）。
- 驗證：手動跑 watchdog → 容器在跑 ⇒ 不發通知；restart_guard `DRY_RUN=1 GUARD_ALERT_ONLY=1` → 正確讀到 `StartedAt` 並計次。
- 指標：`/var/log/tw_watchdog.log`、`/var/log/tw_restart_guard.log`；腳本不在 repo 內（只在 VM），待納入版控。
- 附註：11:11:39 CST 有人寫入 VM 的 `docker-compose.yml`、11:13:22 容器被**重建**（`Created` 變、log 重置、`RestartCount=0`，image 未重建）。內容與 repo 一致，疑為手動 `deploy_source.sh`。

## 2026-10-27 · `~/.ssh` 權限又被打回 0644，修好並驗證

- 症狀：`gcloud compute ssh tw-autotrader` 失敗，OpenSSH 拒用 `google_compute_engine`（0644 too open）→ `Permission denied (publickey)`。
- 處置：`chmod 700 ~/.ssh`、`chmod 600 ~/.ssh/*`，公鑰與 `known_hosts` 設回 644；`ssh-keygen -y` 驗兩把私鑰皆可讀。
- 驗證：直連 `frank@35.194.221.238` 與 `gcloud compute ssh tw-autotrader --zone=asia-east1-b` 都回 OK（`hostname` = tw-autotrader）。
- 觀察：`~/.ssh` 目錄 mtime 是同日 00:07 ⇒ 金鑰疑似又從 Windows 還原過一次；修法見 `WSL恢復.md` §「還原 `~/.ssh` 之後必做：修正金鑰權限」。
- 指標：這是同一坑第二次踩（第一次已寫進 `WSL恢復.md`）；若再發生，值得查是什麼在還原金鑰。

## 2026-10-26 · 收斂開放問題、校正 W3 教材腳本

- 依指示刪除兩則開放問題：`backtest-data-pitfalls.md` 的「待補原始時序」、`total-assets-reconciliation.md` 的「92,484 / 93,048 數字差」。
- `backtest-data-pitfalls.md` 由 `draft` 轉 `status: active`：內容改註為「由程式註解反推整理」，不再標成待校正草稿。
- 校正 `plans/ppt/…W3-解說腳本.md` slide-21／22：檔名改回 `.md`、講稿描述對齊檔案實際章節（背景／根因／實踐指南／教訓）、`AGENTS.md` 註明在根目錄、補一句「這些檔案進版控」。
- 指標：2 份知識專題 + 1 份教材腳本；程式碼未動。

## 2026-10-26 · 重建 cairn 知識層，補回 4 份被引用卻不存在的檔案

- 現況：repo 有 7 處程式註解、教材腳本引用 `cairn/total-assets-reconciliation.md`、`cairn/environment-scope.md`、`cairn/LOG.md`、`cairn/backtest-data-pitfalls.md` 與 `AGENTS.md`，但這 5 個檔案在檔案系統與 git 歷史中都不存在 ⇒ 死連結。
- 處置：以 `selective_migrate` 從程式註解與腳本 docstring 反推 3 份知識專題文件，並建立規則入口。
- 影響：7 處既有引用全部轉為有效連結，程式碼不需要修改。
- 指標：`cairn/total-assets-reconciliation.md`、`cairn/environment-scope.md`、`cairn/backtest-data-pitfalls.md`、`AGENTS.md`。

## 2026-10-26 · Project Cairn 初始化

- 建立 Project Cairn 結構。
- 歷史知識策略：`selective_migrate`（既有註解與 docstring 中的事故知識搬進知識專題文件；其餘既有文件不動）。
- `cairn/` 政策：`track`（進版控，避免知識層再度無聲消失）。
- 畢業 provider：暫緩對接。
- 細節：見 `AGENTS.md` 與 `.cairn/config.yaml`。
