# WSL 備份還原（tw-selfselect）

> 本文件說明如何備份／還原 WSL 開發環境。tw-selfselect 的**主程式為公開源碼**（沒有加密檔），
> 需要保留的只有：`esun_sdk/`（p12 憑證＋config ini）、`.env`（金鑰）、`~/.dsh/`（DSH 憑證）與 `.bashrc`。

## 憑證檔案注意（重要,以下是被移出的資訊使用者必須補回）

本專案使用玉山證券 `.p12` 憑證檔案（位於 `~/tw-selfselect/esun_sdk/`）。**憑證是個人資產，無法共用。**

- **備份前**：請自行將憑證檔移出備份範圍（或告知買家需自備憑證）
- **還原後**：買家必須將自己的 `.p12` 憑證放到 `~/tw-selfselect/esun_sdk/` 目錄下
- 程式會自動偵測該目錄下的 `.p12` 檔案，無需額外設定

## 備份前清理（使用者必須補回）

```bash
# 1. 將個人憑證移出（賣給他人時，買家會用自己的憑證）
#    建議移到 Windows 磁碟暫存
mv ~/tw-selfselect/esun_sdk/*.p12 /mnt/c/Users/frank/Documents/tw_selfselect_backup/
mv ~/tw-selfselect/esun_sdk/*.example /mnt/c/Users/frank/Documents/tw_selfselect_backup/
mv ~/tw-selfselect/esun_sdk/*.ini /mnt/c/Users/frank/Documents/tw_selfselect_backup/

# 2. 移 .env（含玉山密碼、Telegram Token、FinMind Token）live_trader_multi.py
mv ~/tw-selfselect/.env /mnt/c/Users/frank/Documents/tw_selfselect_backup/

# 3. 移 DSH（DeepSeek Harness）API Key 憑證（沒有 key 就打不了任何 LLM API）
mv ~/.dsh/.credentials.yaml /mnt/c/Users/frank/Documents/tw_selfselect_backup/

# 4. 清 shell 歷史
history -c && history -w

# 5. （可選）移 SSH Key — 如果你有放金鑰在 WSL 裡 GCP SSH key安裝M過程會在產生
# 先複製
cp -a ~/.ssh /mnt/c/Users/frank/Documents/tw_selfselect_backup/
# 刪原件
rm -rf ~/.ssh

# 6. 移 .bashrc
mv ~/.bashrc /mnt/c/Users/frank/Documents/tw_selfselect_backup/


```

> ⚠️ **`.env` 有玉山帳密、Telegram Token、FinMind Token，可以直接用你的身份下單、發訊息、叫資料。**
> ⚠️ **`~/.ssh/` 一般有你的 GitHub / GCP SSH 金鑰。**
> ⚠️ **`.p12` 憑證是個人數位簽章。**

## 備份
在 **PowerShell（系統管理員）** 中執行：

```powershell
wsl --export <Distribution Name> D:\backup\wsl-backup.tar
```
不知道<Distribution Name>可以
```powershell
wsl --list --verbose
```
例如

C:\Users\frank>wsl --list --verbose
  NAME                     STATE           VERSION
* skyworkdistro-skywork    Stopped         2
  
  Ubuntu                   Exporting       2

這裡有兩個wsl的安裝, 若要備份哪一個就把<Distribution Name>換成你要備份的.

## 注意：還原後買家需自行設定

還原後買家第一次進 WSL 要做的：

## 還原

```powershell
wsl --import <自訂系統名稱> <安裝目錄> <備份檔路徑>
```

| 參數 | 說明 | 範例 |
|------|------|------|
| `自訂系統名稱` | 你高興取什麼都行，跟備份時的名稱無關 | `Ubuntu_New` |
| `安裝目錄` | WSL 檔案實際存放的資料夾 | `D:\WSL_Storage` |
| `備份檔路徑` | 剛才 `--export` 產生的 tar 檔 | `D:\wsl_backup.tar` |

### 還原範例

```powershell
wsl --import Ubuntu_New D:\WSL_Storage D:\wsl_backup.tar
```

### 還原後啟動

```powershell
# 以指定使用者登入（假設使用者是 frank）
wsl --set-default-user frank -d Ubuntu_New

# 啟動
wsl -d Ubuntu_New
```

### 買家需要自己準備的

| 項目 | 說明 |
|------|------|
| 📄 玉山 `.p12` 憑證及 config.simulation.ini(或config.ini) | 放到 `~/tw-selfselect/esun_sdk/` |
| 📄 玉山 帳號/憑證密碼 | 填入.env |
| 🔑 自己的 `.env` | 參考 `.env.example.lump(dca)` 填寫 |
| 🤖 Telegram Bot Token | 自己跟 `@BotFather` 申請 填入 .env |
| 🔐 DeepSeek API Key（DSH） | 設定於 `~/.dsh/.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY`（或設 `DEEPSEEK_API_KEY` 環境變數） |
| 🔐 FinMind API Key | 自己跟 finmindtrade.com 申請,填入.\bashrc,.env |

### 還原後第一次設定

```bash
# 1. 把 remote 改為 HTTPS（SSH 金鑰已清空，改用 HTTPS 免驗證 pull, 用備份wsl不用）
cd ~/tw-selfselect
git remote set-url origin https://github.com/dinchentech/tw-selfselect.git

# 2. 拉最新程式碼
git pull

# 3. 檢查 DSH 憑證已清空
ls ~/.dsh/.credentials.yaml
# 預期輸出：ls: cannot access ... No such file or directory

# 4. 重新設定 DSH provider（設定 DeepSeek API Key）
#    啟動 DSH Web GUI → 設定(Settings) → 憑證(credentials) → 填 DEEPSEEK_API_KEY
#    或設環境變數：export DEEPSEEK_API_KEY=你的key（加到 ~/.bashrc）

# 5. 還原 .bashrc（本專案主程式為公開源碼，沒有加密檔）
cp ~/.bashrc.txt  ~/.bashrc
```

進去後確認：

```bash
# 檢查 DSH 憑證已清空
ls ~/.dsh/.credentials.yaml
# 預期輸出：ls: cannot access ... No such file or directory

# 檢查憑證已放入
ls ~/tw-selfselect/esun_sdk/*.p12
# 應該看到你的 .p12 檔案

# 設定 DSH provider（重新輸入 DeepSeek API Key）
#   建議直接於 DSH 的設定中重新輸入 API Key：
#   → 啟動 DSH Web GUI → 設定(Settings) → 憑證(credentials) → DEEPSEEK_API_KEY → 填入你的 DeepSeek API Key
#   DSH 會自動以 mode 0600 存到 ~/.dsh/.credentials.yaml，無需手動建檔或設權限
```

接著設定自己：.bashrc 中的FinMind憑證, .env檔中的FinMind key/玉山密碼/TG key, esun_sdk中放上玉山.example,.p12檔
如果使用者要用自己的git別忘了清除~/tw-selfselect下的.git目錄=> rm -rf .git
再init你自己的.git目錄=>
```bash
git init
git add .
git commit -m "Your Initial commit"
```
若想對git有更多了解請參考: https://ukko.life.nctu.edu.tw/~u0417102/final.html

============================= 以上完成後就能執行本專案程式 =================================

## 注意事項

- `--import` 預設以 **root** 登入，要變回一般使用者需執行 `wsl --set-default-user`
- `wsl --import` 不支援 `--version 2` 以外的選項（預設就是 WSL 2）
- WSL 1 的發行版無法透過 `--import` 正確還原


## 附錄:Telegram bot/token 申請說明

1. 前置條件
手機安裝 Telegram 並已註冊帳號
申請 Bot 全程在 Telegram App 內完成，不需要寫任何程式碼
2. 找到 @BotFather
在 Telegram 搜尋欄輸入 @BotFather，找到官方機器人（注意認證標記 ✅ 才是官方的）：

![BotFather 官方帳號應有藍勾勾認證]

3. 建立新 Bot
對 BotFather 發送指令：

/newbot
BotFather 會依序問你兩個問題：

步驟	問題	範例回答
1	機器人顯示名稱（可中文，可換）	TW AutoTrader 通知
2	機器人username（唯一，只能英文+數字，結尾必須是 bot）	tw_autotrader_notify_bot
⚠️ username 是全域唯一的，若已被佔用需換一個。

完成後 BotFather 會回傳一段訊息，其中包含：

Done! Congratulations on your new bot.

Use this token to access the HTTP API:
<你的 Token>
這行 <你的 Token> 就是你要複製保存的 Bot Token。

格式為：1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

4. 取得你的 Telegram Chat ID
Bot 只會主動推送訊息，若要讓 Bot 知道把通知發給誰，需要取得你的個人 Chat ID：

方法一：用 @userinfobot

搜尋並對 @userinfobot 發送任意訊息（例如 /start）
它會回傳你的 chat_id（例如 8384117171）
方法二：用 API 查（適合已有 Bot Token） 先對你的 Bot 隨便發一則訊息（如 hi），然後用瀏覽器或 curl 執行：

https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
在回傳 JSON 中找到 "chat":{"id":<數字>} 即為你的 Chat ID。

5. 填入 tw-selfselect 的 .env
在 .env 檔案中設定：

TELEGRAM_BOT_TOKEN=<你的 Bot Token>
TELEGRAM_CHAT_ID=<你的 Chat ID>
例如：

TELEGRAM_BOT_TOKEN=<你的 Bot Token>
TELEGRAM_CHAT_ID=<你的 Chat ID>
6. 驗證
啟動程式後，Bot 應立即發送第一條通知到你的 Telegram。若沒收到：

確認 Token 複製完整（含冒號前後兩段）
確認已先對 Bot 發過至少一則訊息（Telegram Bot 不能主動對沒互動過的用戶發訊息）
確認 Chat ID 是數字格式，不是 username
7. 常用 BotFather 指令
指令	用途
/mybots	列出你所有的 Bot
/mybots → 選 Bot → API Token	重新取得/撤銷 Token
/setuserpic	更換 Bot 頭像
/setdescription	設定 Bot 介紹文字
/setcommands	設定斜線指令選單
/deletebot	刪除 Bot（不可逆）
