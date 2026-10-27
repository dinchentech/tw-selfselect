# tw-selfselect（TW SelfSelect Trader）路線圖

**當前焦點**：真錢上線（`ESUN_ENVIRONMENT=real`）前的帳務與資料一致性——三本帳對得上券商庫存、快取不再汙染回測。

## 里程碑

- [ ] **玉山舊部位清理（2026-10-27 使用者交代）**：VM 本機三本帳已清空（`holdings.json` 不存在、`performance.csv` 只有表頭、稽核 `三本帳一致`），但**玉山（模擬帳）那邊可能還留著之前交易留下的持股**。本機看不到 ⇒ 收盤後（避免與主程式的 SDK session 打架）跑 `scripts/reconcile_broker_books.py` 取得券商庫存，再決定：真存在就賣掉或補記進帳本，不存在就走 `scripts/void_untracked_buys.py` 作廢。
- [ ] 三本帳（`performance.csv`／`holdings.json`／`stock_allocation.json`）在實盤機上恆等，且與券商庫存逐檔一致
- [ ] 快取汙染零容忍：source 端與消費端都擋掉不可用列，且 `CACHE_SCHEMA_VERSION` 升級流程寫成 runbook
- [ ] 切 `real` 的狀態檔清空演練（`scripts/reset_paper_trading_vm.py`）實際跑過一次並留下紀錄
- [ ] 小額試跑一週：1 檔、小額 `alloc`，觀察下單與帳務無異常

## 開放問題

1. `cairn/` 的死連結要不要進 CI（這批 7 處引用曾長期無人察覺）？若要，需排除 `cairn/Cited.md` 與 `cairn/Reference/`——它們按規範在「第一次觸發」才建立，缺席是預期行為不是漏寫。
2. `cache/inst_momentum` 的寫入者在 repo 外或加密程式內，是否要補一份產生器或至少一份口徑文件？
3. 教學用的 `plans/ppt/` 腳本把 `cairn/` 當示範素材，教材與知識層的同步責任歸誰？
