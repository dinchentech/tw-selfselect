---
type: project_topic
status: active
summary: "部署到 GCP VM 的完整流程（deploy_source.sh 建 image → SSH 直傳 → compose 重建 → 驗指紋）、VM 上三個 root 層守門員，以及 2026-10-02 崩潰迴圈與 2026-10-27 假告警兩次事故"
tags: [部署, VM, cron, watchdog, 事故]
contains: [背景, 當前結論, 實踐指南, 教訓, 開放問題]
created: "2026-10-27"
updated: "2026-10-27"
related: [environment-scope.md, total-assets-reconciliation.md]
authoring_mode: ai_generated
---
# 部署管線與 VM 守門員

## 背景

兩個母專案的痕跡必須分清楚，否則會像 2026-10-27 那樣被假告警騙一整週：

| 名稱 | 是什麼 | 現況 |
|---|---|---|
| `tw-autotrader` | GCP **VM 實例名**（metadata 就叫這個，`hostname` 也是） | 刻意保留不改 |
| `~/tw-autotrader`（VM 上） | 母專案的舊部署目錄 | **原地保留，回滾用** |
| `tw_autotrader_bot` | 母專案的舊容器名 | **不存在**（只有回滾、`docker compose up` 才會出現） |
| `~/tw-selfselect` | 本專案的 VM 部署目錄 | 現役 |
| `tw_selfselect_bot` | 本專案的容器名 | 現役 |

## 當前結論

### 部署流程（`deploy_source.sh`，本機執行）

1. **前置檢查**：GCP 認證、VM 狀態；`SKIP_PREFLIGHT=1` 可跳過（不建議）。
2. **本機建 image**（`tw-selfselect:latest`）→ 缺檔時自動補不進版控的 `esun_sdk/*.p12` 與 `config.simulation.ini`。
3. **SSH 直傳**：`docker save | gzip -1 | ssh 'gunzip | docker load'`（e2-micro 只有 1GB RAM，遠端只跑原生 `gunzip`／`docker load`，不在 VM 上跑 `gcloud` 串流以免 OOM）。本專案**沒有 GCS bucket**，一律直傳。
4. **上傳 `docker-compose.yml`／`.env`**（首次部署會用 `scripts/make_selfselect_env.py` 產生）。
5. **停舊容器 → `docker compose up -d --force-recreate`**（`KEEP_OLD_RUNNING=1` 可不停，但同一券商帳號**不可兩隻 bot 同時下單**）。
6. **驗 `core/version.py` 的 build fingerprint**，不符就 `exit 1` 並印容器 log 尾段。
7. **刻意不做 `docker system prune`**：舊 image 留著，回滾不必重 build。

觀測到的時間特徵（2026-10-27 11:11 那次）：`docker-compose.yml` 寫入 11:11:39 → 容器 `Created` 11:13:22、log 重置、`RestartCount=0`、image 版號不變 ⇒ **重建（recreate）不是崩潰**。

### VM 上三個 root 層守門員

來源全部在 `scripts/vm/`，**唯一安裝入口**：

```bash
./scripts/vm/install_vm_guards.sh                 # 安裝／更新三支
VERIFY_ONLY=1 ./scripts/vm/install_vm_guards.sh   # 只檢查現況
```

| 檔案 | 排程 | 做什麼 |
|---|---|---|
| `tw_watchdog.sh` | root crontab `*/5` | `docker inspect` 容器；沒跑就 `docker start` 並發 Telegram；另外 `kill -9` 容器以外的同名 python 實例（防重複實盤） |
| `tw_restart_guard.sh` | `/etc/cron.d/tw_restart_guard` `*/5` | 讀容器 `StartedAt` 計次；60 分鐘內重啟 ≥6 次 ⇒ 發 Telegram（附 log 尾段）、`docker update --restart=no` 止血、180 分鐘後自動恢復 |
| `auto_shutdown.sh` | `/etc/cron.d/auto_shutdown` `0 18 * * *`（UTC = 02:00 台北） | 忘記關機的安全網 |

VM 時間軸：GCP 資源政策 `trade-hours`（Asia/Taipei）**08:00 開機、14:00 關機**（週一至五）⇒ 收盤 13:30 之後才關。

驗證守門員是否正常（不要只看 `docker ps`）：

```bash
sudo /usr/local/bin/tw_watchdog.sh; echo "exit=$?"   # 0 且無輸出＝容器健康、沒亂發通知
sudo DRY_RUN=1 GUARD_ALERT_ONLY=1 /usr/local/bin/tw_restart_guard.sh
sudo tail -3 /var/log/tw_watchdog.log /var/log/tw_restart_guard.log
```

## 實踐指南

- **改容器名／目錄名時**，同時檢查這四處：`docker-compose.yml`、`deploy_source.sh` 的 `CONTAINER`／`OLD_CONTAINER`、`scripts/vm/tw_watchdog.sh` 的 `CONTAINER_NAME`／`ENV_FILE`／`pgrep` 目標、`scripts/vm/tw_restart_guard.sh` 的 `GUARD_CONTAINER`／`STATE`／`ENV_FILE`。
- **盤中不要部署**：`--force-recreate` 會讓 bot 重新初始化 5 檔並中斷當前判斷。收盤後（13:30 之後）或 08:00 開機前做。
- **回滾**：`gcloud compute ssh tw-autotrader --zone=asia-east1-b --command='cd ~/tw-autotrader && sudo docker compose up -d'`——但務必先把 `tw_selfselect_bot` 停掉，同帳號不能兩隻 bot。

## 教訓

- **只存在 VM 的腳本 = 沒有版控的腳本**。三支守門員原本只躺在 `/usr/local/bin`，專案改名後沒人知道要改它們，於是 watchdog 對著不存在的容器喊了一週、restart_guard 全程「略過」。
- **假告警會掩蓋真故障**：每 5 分鐘一則「容器未運行」，久了就沒人看，真的崩潰時也不會有人注意。
- **watchdog 的「沒跑就 `docker start`」是雙面刃**：目標名寫錯時它只是吵；但若那名字哪天真的存在（回滾、手動建立），它會把**舊 bot 拉起來跟現役 bot 搶同一個券商帳號**。
- **崩潰迴圈（2026-10-02）**：v4.41 部署了啟動即崩的版本，docker 依 restart policy 每分鐘重啟、每次都發啟動通知 ⇒ 無聲迴圈 15 小時、`RestartCount=25`、整個交易時段沒跑。守門員就是為此而生，別讓它再變成死的。

## 開放問題

1. `deploy_source.sh` 目前**不會**順帶更新守門員（要另跑 `install_vm_guards.sh`）。要不要加 `INSTALL_GUARDS=1` 讓部署一併帶上？
2. `/etc/cron.d` 的註解原本寫「由 `scripts/vm_set_auto_shutdown_cron.sh` 產生」，但那個腳本在 git 與 VM 都查無此物（從未進版控）——已改指向 `scripts/vm/install_vm_guards.sh`。
3. `tw_watchdog.sh` 的 `pgrep -f selfselect_trader.py` 仍可能誤中未來新增的同名工具；目前靠 `/proc/<pid>/exe` 是 python 才動手。
