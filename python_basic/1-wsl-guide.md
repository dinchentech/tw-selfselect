# WSL 簡易使用方式

## (1) 啟動與離開

### 啟動 WSL

**方法一：Windows 開始功能表**
- 開始 → 搜尋「Ubuntu」或「WSL」→ 點擊圖示

**方法二：Windows 終端機 (推薦)**
- 在工作列右鍵 →「Windows 終端機」或按 `Win + X → T`
- 下拉選單選擇 Ubuntu

**方法三：CMD / PowerShell**
```cmd
wsl
```

### 離開 WSL

```bash
exit
```
或直接關閉視窗。

### 重新啟動 WSL（當網路或服務異常時）
```cmd
# 在 Windows PowerShell（系統管理員）執行：
wsl --shutdown
wsl
```

---

## (2) 在 Windows 檔案總管查看 WSL 檔案

### 方法一：快捷鍵
在 WSL 終端機中輸入：
```bash
explorer.exe .
```
這會在檔案總管打開**目前目錄**。

### 方法二：網路路徑
在檔案總管網址列輸入：
```
\\wsl.localhost\Ubuntu
```
即可瀏覽整個 Ubuntu 檔案系統。

### 方法三：透過開始功能表
開始 → 搜尋「Ubuntu」→ 右鍵 →「開啟檔案位置」

### 常用路徑
| 路徑 | 說明 |
|------|------|
| `\\wsl.localhost\Ubuntu\home\<你的使用者名稱>` | 你的家目錄（大部分工作在此） |
| `\\wsl.localhost\Ubuntu\` | 整個 Ubuntu 根目錄 |

---

## (3) 從 WSL CLI 呼叫 Windows 程式

### 開啟檔案總管（目前目錄）
```bash
explorer.exe .
```

### 用 Notepad 開啟檔案
```bash
notepad.exe .env
```
適合快速查看或編輯設定檔。

### 用 VS Code 開啟（需安裝 Remote - WSL 擴充）
```bash
code .
```
**注意**：第一次執行需要安裝 VS Code Server，稍等幾秒即可。

### 用 Windows 瀏覽器開啟網頁
```bash
cmd.exe /c start https://google.com
```

---

## (4) 基本檔案操作命令

### 變更目錄
```bash
pwd                    # 查看現在位置
ls                     # 列出檔案
ls -la                 # 列出詳細資訊（含隱藏檔）
cd tw-selfselect       # 進入 tw-selfselect 目錄
cd ..                  # 回上一層
cd ~                   # 回家目錄
cd -                   # 回到上一個目錄
```

### 更改檔名
```bash
mv 舊名稱 新名稱
# 範例
mv old.txt new.txt
```

### 複製檔案
```bash
cp 來源 目的
# 範例
cp config.json config_backup.json
cp -r 資料夾 備份資料夾   # 複製整個目錄
```

### 刪除檔案
```bash
rm 檔案名稱              # 刪除檔案
rm -r 資料夾             # 刪除目錄（含內部所有檔案）
rm -rf 資料夾            # 強制刪除（⚠️ 無法復原，小心使用）
```

### 建立目錄
```bash
mkdir 新目錄名稱
mkdir -p a/b/c          # 建立巢狀目錄
```

---

## (5) WSL 重要檔案結構

```
/
├── home/
│   └── frank/               ← 你的家目錄（大部分工作在此）
│       └── tw-selfselect/   ← 交易程式專案目錄
│           ├── live_trader_multi.py  ← 主程式
│           ├── strategies/           ← 策略模組
│           ├── core/                 ← 核心功能
│           ├── .env                  ← 設定檔（含 API Key，**不要 commit**）
│           ├── deploy.sh             ← 部署腳本
│           └── logs/                 ← 執行日誌
│
├── mnt/                    ← Windows 磁碟掛載
│   ├── c/                  ← C: 槽
│   │   └── Users/frank/    ← Windows 使用者目錄
│   └── d/                  ← D: 槽（若有）
│       └── ...
│
└── etc/                    ← Linux 系統設定
    └── wsl.conf            ← WSL 設定檔
```

### 跨系統存取原則

| 要從哪讀寫 | 建議路徑 | 效能 |
|-----------|---------|------|
| WSL 讀寫 WSL 檔案 | `/home/frank/...` | ⚡ 最快 |
| WSL 讀寫 Windows 檔案 | `/mnt/c/Users/frank/...` | 🐢 較慢 |
| Windows 讀寫 WSL 檔案 | `\\wsl.localhost\Ubuntu\...` | 🐢 較慢 |
| Windows 讀寫 Windows 檔案 | `C:\Users\frank\...` | ⚡ 最快 |

**黃金法則**：程式碼和設定檔放在 WSL 家目錄（`/home/frank/`），只在需要時透過 `\\wsl.localhost` 或 `explorer.exe .` 從 Windows 存取。
