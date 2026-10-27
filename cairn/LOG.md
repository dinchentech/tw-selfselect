# Project Cairn Log

本檔以倒序記錄實質推進（最新在最上面，緊接這行之下）。每則保持精簡——只寫摘要與指標，結論沉澱到 `cairn/<主題>.md`。

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
