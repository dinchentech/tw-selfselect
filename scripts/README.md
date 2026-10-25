# scripts/ — 工具腳本

> 全部用專案的虛擬環境跑：`.venv/bin/python scripts/<檔名>.py`
> 需要 `.env` 的腳本都會以「檔案」為準載入（`load_dotenv(override=True)`），
> 這樣在容器內用 `docker exec` 跑也讀得到主機最新的 `.env`。

## 每月作業

| 腳本 | 用途 |
|---|---|
| `monthly_selfselect_run.py` | **每月作業一條指令**：補資料 → 選股 → 改 `.env`（預設 dry-run，`--apply` 才寫檔）|
| `monthly_rebalance_picker.py` | 選股引擎本體（`--risk normal` / `high_profit`；過熱剔除、法人確認、總數上限 N）|

```bash
.venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5            # 預覽
.venv/bin/python scripts/monthly_selfselect_run.py --risk normal --top-n 5 --apply    # 寫入 .env
```

## 資料維護（第一次必做）

| 腳本 | 用途 |
|---|---|
| `rebuild_mcap_ranking.py` | 重建「當期市值前 N 大」候選池（`cache/inst_momentum/mcap_ranking.pkl`）|
| `build_historical_shares.py` | 建歷史股本（誠實候選池：每季當時的市值排名）|
| `append_selector_prices.py` | 補選股用的日線快取（`cache/selector_prices/`）|
| `verify_cache.py` | 快取健檢（版本、語義、覆蓋範圍）|
| `update_taiwan_holidays.py` | 更新休市日曆 `config/taiwan_holidays.json`（主程式每天 08:40 自動檢查）|

## 對帳與修帳

| 腳本 | 用途 |
|---|---|
| `reconcile_total_assets.py` | 三本帳（`performance.csv` / `holdings.json` / 分帳本）一致性 |
| `reconcile_broker_books.py` | 與券商庫存對帳（**真錢上線前必跑**）|
| `check_holdings_vs_env.py` | `.env` 名單 vs 實際持股（找出孤兒部位）|
| `void_untracked_buys.py` | 作廢「只寫進 CSV、沒進 holdings」的幽靈買進列 |
| `migrate_performance_csv_schema.py` | `performance.csv` 舊 schema（6/7 欄）→ 8 欄 |

## 回測與研究

| 腳本 | 用途 |
|---|---|
| `backtest_plan2_monthly_3group.py` | 每月換股三組策略回測（誠實池、交易成本、可重現）|
| `selector_full.py` | 單檔／多檔策略掃描（找適合某檔的策略）|
| `selector_keep.py` | keep_wait 低接策略的參數掃描 |

回測範例：

```bash
START=2015-01-01 END=2025-12-31 \
  .venv/bin/python scripts/backtest_plan2_monthly_3group.py
```

## 維運／診斷

| 腳本 | 用途 |
|---|---|
| `generate_dashboard.py` | 產生 `logs/dashboard.html`（主程式 13:45 自動呼叫）|
| `reset_paper_trading.py` | 清空模擬帳狀態（**真錢上線前務必確認**要不要清）|
| `reset_paper_trading_vm.py` | 從**本機** SSH 進 VM 跑重置（自動停 bot → 一次性容器執行 → 重建／起回 bot）|
| `preflight_deploy.sh` | 部署前檢查（測試 ＋ 靜態檢查）|
| `make_selfselect_env.py` | 由 tw-autotrader 的 `.env` 產生 tw-selfselect 的 `.env`（一次性遷移；`deploy_source.sh` 第一次部署會自動呼叫）|
