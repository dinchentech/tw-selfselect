# why_wsl_python 解說腳本（短片旁白，2026-11-02）

> 給 `plans/generate_voiceover.sh` 用：`## slide-N 標題` 分段，段落內容就是 TTS 要念的旁白。
> 內容直接由 `plans/ppt/why_wsl_python/why_wsl_python.pptx` 左側「旁白文字」框抽出（8 頁），保證語音與簡報一致。
> 產出 `_narration_why_wsl_python-*`（不進版控）→ 再 `NARR=<dir> bash plans/ppt/why_to_mp4.sh` 合成帶旁白的 MP4。

## slide-1 封面：為什麼我要用 WSL（約 15 秒）

很多不是電子、資訊背景的朋友都會問我：為甚麼要用 WSL？這一支影片，我就用幾分鐘，把為甚麼要用 WSL、還有整套系統的基礎，一次講清楚。

## slide-2 為什麼是 WSL：Windows 之下的 Linux（約 33 秒）

WSL 就是 Windows 底下的 Linux 子系統。跟 Windows 比起來，Linux 不會三不五時改版，也不會一直跳出更新，執行起來非常穩定，不容易當機。我們實際在跑的實盤程式，就是跑在 Google 雲端的 Linux 主機上面，而且包成一個容器，也就是 Docker。容器裡面只放執行程式需要的東西，沒有其他多餘的程式和套件，中毒的機率也大大降低。

## slide-3 三個關鍵名詞：Docker、Image、Container（約 40 秒）

Docker 是開源平台，用貨櫃化的技術，把程式和它需要的環境、套件、設定一起打包，在任何電腦上都能開箱即用，結果完全一致。Image 映像檔是唯讀的範本，像光碟片，裡面包含執行所需的一切，本身不能執行。Container 容器，就是 Image 跑起來的實體，就像把光碟放進光碟機玩遊戲；容器之間完全隔離，互不影響。我們的實盤程式，就是擺在 Google 雲主機 Linux 系統裡的 Docker。

## slide-4 怎麼連上去：Google 雲主機與容器（約 37 秒）

我們的電腦是在本地端執行 WSL，那又要怎麼登入 Google 雲主機？進入 Google Cloud 控制台，選 Compute Engine，再選 VM 執行個體，就會看到 SSH 連線的按鈕，點下去就進到遠端雲主機。而要登入雲主機裡面的 Docker，就在雲主機裡用 docker exec 進去。不過大部分的指令，基本上在本地 WSL 操作就可以了；必須修改雲主機或 Docker 參數的時候，指示 AI 執行就好。

## slide-5 學習資源：從哪裡開始學 WSL（約 32 秒）

如果你不熟悉 Linux，可以上微軟的網站 learn.microsoft.com，搜尋 WSL 的簡介，目前已經到第二版的 WSL 2。就像 Windows 的 DOS 指令系統，WSL 使用的一般是 bash 這個 shell 指令。在微軟的 Learn 網站裡，路徑是 Learn、Windows、開發環境、WSL，其中有一節「開始使用 Linux 和 Bash」，專門介紹檔案與目錄的指令。

## slide-6 工具與字型：VS Code、等距更紗黑體、Git（約 36 秒）

Windows 建議安裝 VS Code，因為很多 AI 的輸出格式都是 MD 檔，這些 MD 檔用 VS Code 來觀看和修改都很方便。另外建議安裝「等距更紗黑體 TC」。因為一般的字體，英文的點距大小不一，所以許多 AI 產生的表格看起來很亂；而等距的字體，中文和英文的字寬是二比一，AI 的 MD 檔表格就會比較整齊。我們的源碼是放在 GitHub 網站上，所以使用者也必須了解簡單的 Git 操作。

## slide-7 為什麼選 Python（約 22 秒）

那為什麼選 Python？第一，AI 對 Python 最熟悉，產生程式碼又快又穩定。第二，許多券商提供的 API，本來就是 Python 版本。第三，Python 目前是學校教學的主流，遇到問題的時候，能找到的資料和帮手也最多。

## slide-8 總結：使用 WSL 是自動化系統的基礎（約 37 秒）

一套程式，要用哪些工具和系統，才能穩定執行？我們的方式，就是用 Linux 的 Docker 來跑 Python 程式；而且我們的 AI 系統和各式 AI 插件，也都是以 Linux 系統為主，這就是我們把開發環境選用 WSL 的原因。所以，簡單的 WSL 使用知識，還有 Git 的基本操作，就是建立我們這套自動化系統的基礎知識。如果不熟，請先補足這方面的知識！
