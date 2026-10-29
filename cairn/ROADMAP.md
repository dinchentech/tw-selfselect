# tw-selfselect（TW SelfSelect Trader）路線圖

**當前焦點**：真錢上線（`ESUN_ENVIRONMENT=real`）前的帳務與資料一致性——三本帳對得上券商庫存、快取不再汙染回測。

> 2026-10-29 更新：AI 選股已從「做不做得到」推進到「值不值得做」——可稽核封包、DSH 兩步流程、實盤可選模式都已完成，
> A/B 結果顯示嚴格等量下沒有統計優勢、規則組補滿後只剩 1 個月邊際（`cairn/ai-stock-selection.md`）。
> 這條線**不再佔用當前焦點**，停在等決策；真錢上線仍是唯一閘門。

## 里程碑

- [ ] **玉山舊部位清理（2026-10-27 使用者交代）**：VM 本機三本帳已清空（`holdings.json` 不存在、`performance.csv` 只有表頭、稽核 `三本帳一致`），但**玉山（模擬帳）那邊可能還留著之前交易留下的持股**。本機看不到 ⇒ 收盤後（避免與主程式的 SDK session 打架）跑 `scripts/reconcile_broker_books.py` 取得券商庫存，再決定：真存在就賣掉或補記進帳本，不存在就走 `scripts/void_untracked_buys.py` 作廢。
- [ ] 三本帳（`performance.csv`／`holdings.json`／`stock_allocation.json`）在實盤機上恆等，且與券商庫存逐檔一致
- [ ] 快取汙染零容忍：source 端與消費端都擋掉不可用列，且 `CACHE_SCHEMA_VERSION` 升級流程寫成 runbook
- [ ] 切 `real` 的狀態檔清空演練（`scripts/reset_paper_trading_vm.py`）實際跑過一次並留下紀錄
- [ ] 小額試跑一週：1 檔、小額 `alloc`，觀察下單與帳務無異常
- [ ] **儀表板自動發佈連續成功**：deploy key 已於 2026-10-28 逐項驗證（SSH 認證／push／`DRY_RUN=1`）；確認 13:50 的 cron 連續幾個交易日自動發佈、公開頁不再停更（`cairn/deploy-pipeline.md`）
- [x] **選股口徑做成使用者可選 preset**（2026-10-29）：`SELFSELECT_PRESET=current|revenue|aggressive`（回測 `PRESET=`），
  實盤已支援營收因子與產業上限、與回測 9/9 逐位一致；切換時程式印出後果（`core/selection_presets.py`）。
  **使用者裁定：預設改為 `revenue`（池 100＋營收因子、+762.4%／MDD −53.7%／夏普 0.95）**，`.env` 的 `SELFSELECT_POOL_N` 同步改 100。
- [ ] **積極口徑的驗證**（不阻塞上線）：`aggressive`（池150＋營收＋上限2）= +1323.6%／MDD −40.2%／夏普 1.15 是 16 組裡
  事後挑出的最好一組，需①非重疊窗口＋walk-forward ②固定並記錄資料快照（月營收 515→645 檔使同一格 +1070.5%→+1323.6%）
  ③上櫃（TPEX）下市股與 2015 前資料，才談得上改成實盤預設。（`results/backtest_delisted_universe.md`）
- [ ] **AI 選股的去留決策**（不阻塞上線）：先補統計限制（池 50、互不重疊窗口、計交易成本），再決定「只當參考名單」或「維持並行記錄」
- [ ] 教材一致性（非阻塞）：其餘 tab 排版頁換真表格、W1 S13 螢光筆差異（`cairn/teaching-material-pipeline.md`）

## 開放問題

1. `cairn/` 的死連結要不要進 CI（這批 7 處引用曾長期無人察覺）？若要，需排除 `cairn/Cited.md` 與 `cairn/Reference/`——它們按規範在「第一次觸發」才建立，缺席是預期行為不是漏寫。
2. `cache/inst_momentum` 的寫入者在 repo 外或加密程式內，是否要補一份產生器或至少一份口徑文件？
3. 教學用的 `plans/ppt/` 腳本把 `cairn/` 當示範素材，教材與知識層的同步責任歸誰？
4. （2026-10-29 新增）知識專題的 frontmatter `contains` 已統一為受控詞彙（`decision`／`experience`／`lesson`／`procedure`／`reference`／`open_question`），但正文標題仍是中文小節名——要不要在 `AGENTS.md` 寫明這個對映，避免下次又寫成中文？
