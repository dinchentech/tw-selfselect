# GCP 申請與設置

## (1) 申請 GCP 帳號

### 步驟

1. **前往 Google Cloud 官網**
   - https://cloud.google.com
   - 點擊右上角「免費試用」

2. **登入 Google 帳號**
   - 使用你的 Gmail 或 Google 帳號登入
   - 建議建立一個專用帳號（如 `你的名字@gmail.com`）

3. **填寫帳單資訊**
   - 需要綁定信用卡（用於身份驗證）
   - 新用戶可獲得 **$300 美元免費額度**（有效期 90 天）
   - TW AutoTrader 使用 e2-micro 規格，每月約 $6-8 美元，遠低於免費額度

4. **建立專案**
   - 進入 GCP Console：https://console.cloud.google.com
   - 點擊頂端專案下拉選單 →「新增專案」
   - 專案名稱：`tw-selfselect`（或自訂名稱）

---

## (2) 啟用必要服務

### 啟用 Compute Engine API

```bash
# 在你的 WSL 終端機執行
gcloud services enable compute.googleapis.com
```

### 啟用 Cloud Build API（用於映像檔建構）

```bash
gcloud services enable cloudbuild.googleapis.com
```

---

## (3) 安裝與初始化 gcloud CLI

### 安裝 Google Cloud SDK

```bash
# 在 WSL 中執行
# 安裝 gcloud
sudo apt update
sudo apt install -y curl gnupg

# 加入 Google Cloud 套件庫
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list

# 安裝 gcloud CLI
sudo apt update && sudo apt install -y google-cloud-cli
```

### 初始化與登入

```bash
gcloud init
```

過程會：
1. 詢問是否登入 → 選擇 `Y`
2. 自動開啟瀏覽器 → 登入你的 Google 帳號
3. 選擇專案 → 選剛建立的 `tw-selfselect`
4. 設定地區 → 選 `asia-east1`（台灣）

### 驗證登入

```bash
gcloud auth list
# 應該顯示你登入的帳號
```

---

## (4) 建立 VM 執行個體

### 方式一：使用 gcloud 指令（推薦）

```bash
gcloud compute instances create tw-selfselect \
  --zone=asia-east1-b \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --tags=tw-selfselect
```

### 方式二：使用網頁主控台

1. 前往 Compute Engine → VM 執行個體
2. 點擊「建立執行個體」
3. 設定：
   - 名稱：`tw-selfselect`
   - 區域：`asia-east1-b`（台灣）
   - 機器類型：`e2-micro`（最便宜）
   - 開機磁碟：`Ubuntu 22.04 LTS`，大小 `20 GB`
4. 點擊「建立」

> **節費提醒**：VM 不需要 24 小時運作。交易時間為台股盤中（08:45-13:30），可設定排程：
> ```
> # 開機排程（週一至週五 08:00）
> gcloud compute instances add-schedule tw-selfselect \
>   --schedule="0 8 * * 1-5" \
>   --timezone="Asia/Taipei" \
>   --start
> 
> # 關機排程（週一至週五 14:00）
> gcloud compute instances add-schedule tw-selfselect \
>   --schedule="0 14 * * 1-5" \
>   --timezone="Asia/Taipei" \
>   --stop
> ```

---

## (5) VM 基本操作

### SSH 連線

```bash
# 使用 gcloud SSH（免 IP、免金鑰）
gcloud compute ssh tw-selfselect --zone=asia-east1-b
```

### 傳送檔案

```bash
# 從本機傳到 VM
gcloud compute scp 檔案名稱 tw-selfselect:~/ --zone=asia-east1-b

# 從 VM 傳回本機
gcloud compute scp tw-selfselect:~/檔案名稱 . --zone=asia-east1-b
```

### 查看 VM 清單

```bash
gcloud compute instances list
```

---

## (6) VM 基礎環境設定

### 安裝 Docker（在 VM 上只需執行一次）

```bash
# SSH 進 VM 後執行
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable docker
```

### 確認運作

```bash
sudo docker --version
sudo systemctl status docker --no-pager
```
