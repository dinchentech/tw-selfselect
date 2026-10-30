# plans/ppt — 教學投影片（W1–W6，講稿版）

從母專案 [tw-autotrader](https://github.com/dinchentech/tw-autotrader) 的
`plans/ppt/TW-AUTOTRADER台股買賣自動化系統-W*-講稿版.pptx` 複製改寫而來，
改成 **tw-selfselect（自選股／每月換股單一資金腿）** 的內容。

> 只複製「講稿版」（含逐頁講稿備註）。母專案的舊配音版沒有複製——旁白已錄好，改文字會跟聲音對不上。
> 本專案的配音版是**用目前的講稿重新合成**的，見下方「配音版與 MP4」。

## 相對母檔的變更

| 項目 | 說明 |
|---|---|
| 品牌 | 檔名與標題頁 `TW-AUTOTRADER` → `TW-SELFSELECT` |
| 刪頁（W4） | 23–33（母專案專屬的季度換股策略、季度排程、ROTATE_MODE 自動化流程、法人抬轎動能、Group 2）、36（該策略的回測）、38（為什麼大資金不適合該策略） |
| 刪頁（W6） | 20（「每季選股為何勝 0050」——整頁都是母專案專屬季度換股策略的論述）|
| 表格列刪除 | W4 風險控制頁移除 Group 2 欄；W6 策略選擇建議表移除法人動能、母專案專屬季度換股策略兩列 |
| 文字改寫 | W1 六大策略→五大策略；W2 掛載用途與 DEBUG 範例去 ROTATE_；W3 法人動能案例改為通用舊回測；W4 策略清單 6→5；W5 回測模式五（法人抬轎）移除；W6 策略備註、持股數目講稿去母專案專屬季度換股策略 |
| W4「法人確認濾網」頁 | 表格改寫成 tw-selfselect 口徑（15 日法人淨買超、TWSE T86 自動補抓／pass-through、`--no-inst`／`--inst-days`），刪掉母專案專屬季度換股策略的回測數字列 |
| 全域替換 | `live_trader_multi.py` → `selfselect_trader.py`；`ROTATE_MODE_VAL` → 通用變數示例 |
| W1 第 7 頁「實際運行展示」 | 改用 VM 實機儀表板截圖（`plans/assets/dashboard_real_20261026.png`，已去識別＝只有代號／數字）＋右側白底說明卡；線上示範頁連結另註明「範例資料」 |

驗證：轉換後六個檔以 python-pptx 重新開啟無誤，全文（含講稿備註、表格）掃描
`法人動能｜法人抬轎｜ROTATE_｜live_trader_multi｜TW-AUTOTRADER` 皆 0 命中（母專案專屬季度換股策略的頁面已刪除）
W4/W6 以 LibreOffice 轉 PDF 抽頁目視確認版面正常（頁碼是自動欄位，刪頁後會自己重編）。
W4 另補「keep_wait 人工管理怎麼用」一頁，對應 `策略說明.md` §9.9。

## 檔案

| 檔案 | 頁數 |
|---|---|
| `TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx` | 17 |
| `TW-SELFSELECT台股買賣自動化系統-W2-講稿版.pptx` | 28 |
| `TW-SELFSELECT台股買賣自動化系統-W3-講稿版.pptx` | 23（原 24；刪掉重複的 plan 模式頁）|
| `TW-SELFSELECT台股買賣自動化系統-W4-講稿版.pptx` | 28（原 39；新增 2 頁：auto 型態感知、keep_wait 人工管理）|
| `TW-SELFSELECT台股買賣自動化系統-W5-講稿版.pptx` | 26 |
| `TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx` | 24（原 21；新增 4 頁：完整流程、生命週期、賣出後會不會補選、母專案自選股回測）|
| `TW-SELFSELECT台股買賣自動化系統-W7-講稿版.pptx` | 19（新編：v1.1 之後的 zscore（預設）＋ AI 選股／重要參數／AI 選股實作／可能的改進／最後的風險與獲利抉擇提醒）|

## W7（2026-10-30 新增，講稿版）

主題是 **v1.1.x 之後的選股方式**：新加的 `zscore`（現行預設）與 AI 選股，以及回測結果、參數、實作流程與改進方向。

- 產生器：`plans/ppt/make_w7.py`（沿用 W6 的母版與版型，刪光範例頁後用 python-pptx 重畫 18 頁＋講稿備註）。
  重新產生：`.venv/bin/python plans/ppt/make_w7.py`
- 講解腳本：`TW-SELFSELECT台股買賣自動化系統-W7-解說腳本.md`（由 `notes_to_script.py` 從備註反推，19 頁／約 43 分 30 秒）。
- 2026-10-30 追加：S14 定義 D1／D2；S7 加「產業上限」同一天名單對照實例；S16「產業上限已接進實盤、待定預設值」措辭更正；
  新增 S19「選股很重要，但代價是風險」——v1.0 legacy（+207.9%／MDD −36.0%／夏普 0.69）vs v1.1 預設（+762.4%／−53.7%／0.95），
  提醒「風險與獲利的取捨由使用者決定」。
- 內容與數字口徑：2016-2025、正常組、含成本、`PROFILE=default`（停泊 0050＋大盤年線），資料快照
  宇宙 672 檔、PER 672/672、月營收 645/672；三個 preset（current +411.1%／revenue +762.4%／aggressive +1323.6%）與 0050（+477.6%）。
- 尚未做配音版／MP4（需要 `plans/generate_narration.sh build` 重跑 TTS，本次未執行）。

## 配音版與 MP4（2026-10-27 重製）

六份講稿的內文與數字都已改成目前的回測口徑，配音全部**重新合成**（不是沿用母專案的舊錄音）。
每一份都產出兩個成品：

- `…-W*-配音版.pptx`：每頁右下角有喇叭圖示，點擊播放該頁旁白（旁白直接嵌在備註區的音訊）。
- `…-W*-配音版.mp4`：影片版，直接用來看／分享。

| 集 | 講稿版頁數 | 配音時長 | MP4 |
|---|---|---|---|
| W1 | 17 | 14 分 12 秒 | 872 s |
| W2 | 28 | 23 分 13 秒 | 1,381 s |
| W3 | 23 | 15 分 28 秒 | 928 s |
| W4 | 28 | 20 分 14 秒 | 1,201 s |
| W5 | 26 | 21 分 42 秒 | 1,291 s |
| W6 | 24 | 25 分 05 秒 | 1,494 s |

重建方式（先 `build` 合成旁白並寫回講稿備註，再轉 MP4）：

```bash
bash plans/generate_narration.sh build \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-解說腳本.md

# 沙箱／無 root 環境下 LibreOffice 會寫 $HOME/.config，故改 HOME
HOME=$PWD/TMP/lohome bash plans/ppt_to_mp4.sh \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-配音版.pptx \
  plans/ppt/_narration_TW-SELFSELECT_________-W6-___
```

- W3／W6 另清掉畫面上殘留的「（DSH 介面截圖待補）」字樣（W3 第 2、5、6、19 頁；W6 第 14 頁）並重出 MP4，長度不變（928 s / 1,496 s）；只刪文字框，不動旁白，所以沒有重跑 TTS。
- W3 於同日晚間因 S3／S4「語音與畫面接不上」重配音一次：S3 版面改寬、講稿加長到 35.6 s；S4 講稿改成照畫面六條 bullet 的順序講（71.0 s）。總長 928 s。
- W4 於同日晚間修掉三處與現行口徑不符：S26 總結頁換成 +59.1%／0050 +99.9%／落後 40.8 個百分點（原本 +71.4%／+81.0%／「落後不到 10%」），S25 交易次數上限 5→10 次、講稿刪掉已移除的「第二資金組」，兩頁的「Group1／Group 1」改「正常組」；重配音後 1,201 s（原 1,169 s）；S26 另加「口徑」一行：每月 D1 選股後就下場（選股日收盤價買滿、EXEC=immediate），不是等進場訊號。
- W5-26 標題「Group 1備用２的策略」→「第五個策略（週KD）」（旁白同步），重配音後 1,291 s（原 1,270 s）。
- W6-9 改寫：三種選股方式（固定池／機械化 Rule 0–3／手工人工）各一行說明＋「本專案每月自選股 vs 母專案機械化逐年檢討」六列比較表；講稿加長到 2 分 30 秒（S9 段落 159 s），總長 1,483 s。
- W5 其餘 tab 排版頁也一併改成真表格（S10 盤整盤／震盪盤、S13 聯發科四策略、S20 參數掃描、S22 潛力股 TOP5、S23 動能選股）：文字與數字保留，S10 的「大／快」與 S13/S20/S22 的黃底螢光筆以 run 複製保留；順手修掉原稿兩處黏字（S22 第 5 列「5」與「天二科技/64.6」、S23「2xx1 xxx」缺 tab）。
- W5-12 改成真表格：原本用 tab 空白對齊的兩塊「年度／台積電價格／買進持有報酬／市場」與「策略／2022-2025 報酬損益」，在 PowerPoint 與 LibreOffice 的 tab 寬度計算不同會左右錯位（影片是 LibreOffice 轉圖）⇒ 改用兩張真表格，兩邊渲染都對齊；講稿與配音沒動。
- 螢光筆（PowerPoint `<a:highlight>`）也算畫面內容：W4 S24／S26、W5 S10／S20／S25、W6 S6、W1 S13 都已補進影片（W1 由講稿版直接出畫面，因為它的 S13 在配音版是 SmartArt、講稿版是群組）。
- 旁白文字來源是 `…-解說腳本.md`（由 `notes_to_script.py` 從講稿備註產生）；**改了講稿就要重跑 `build`**，否則聲音與畫面會對不上。
- 逐頁旁白 mp3 中間產物在 `plans/ppt/_narration_*/`；`.gitignore` 已排除 `_narration_*/`、`*-配音版.pptx`、`*.mp4`，這些是產物不入版控。

## DSH 化（2026-10-26）

母檔用的是 opencode，本專案改用 **DSH（DeepSeek Harness）**，已把相關文字全部改寫：

| 項目 | 舊 | 新 |
|---|---|---|
| 名稱 | Opencode / opencode | DSH（DeepSeek Harness） |
| 啟動 | `opencode`（WSL）、`opencode_web` | `dsh_web`（＝`pnpm dsh web`）→ 瀏覽器開 http://127.0.0.1:3080 |
| 續接對話 | `opencode -s <session>` | Web 介面左側 session 清單 |
| 模型 | Deepseek V4 Flash／PRO（Ctrl+P 切換） | deepseek-flash（Web 介面可切換；同段對話不混他廠模型） |
| 模式 | Sisyphus Ultraworker／Prometheus Plan Builder | 一般對話＋**plan 模式**（先送計畫核准）；長任務用 **goal** 分回合續跑 |
| 技能 | `/finmind` 指令 | 自然語言呼叫（例：「用 finmind 抓台積電月營收」） |
| 準備清單 | 申請 OpenRouter／Nvidia 帳號 | 使用 DSH＋deepseek-flash（金鑰事先設好） |

### 截圖處理
- W3 的 s2–s6、s19、s20：內嵌的 opencode 介面截圖**已移除**，原位置留淡色「（DSH 介面截圖待補）」提示框；補到 DSH 截圖後直接換上即可。
- W5 的 s16、s17：截圖內容（計畫表／測試輸出）保留，只**裁掉底部狀態列**（原本寫著 Prometheus Plan Builder／Sisyphus Ultraworker）。
- 其餘截圖（PyCharm、VS Code、圖表、儀表板）與 AI 品牌無關，維持原樣。

## 部署章節改寫（2026-10-26 第二輪）

W2 的部署章節（s11–s17）與 W6 的部署頁（s2、s13）改成實際流程：

| 頁面 | 變更 |
|---|---|
| W2 s11–s13 | 三層架構圖重畫：Local（`~/tw-selfselect`，whl 進 git、p12／ini 不進）→ `./deploy_source.sh`（preflight → build → SSH 直傳）→ VM `~/tw-selfselect`（舊 `~/tw-autotrader` 保留可回滾）→ 容器 `tw_selfselect_bot` |
| W2 s14–s16 | 三層關係、容器執行層、修改流程：拿掉 pyarmor／加密版／源碼版兩種腳本；改成 `./deploy_source.sh`（含驗指紋）與 `logs/backups/cache/.env` 四掛載 |
| W2 s17 | 指令速查：`./deploy_source.sh`、`docker compose down/up`、`docker logs tw_selfselect_bot`、`gcloud compute ssh tw-autotrader` |
| W6 s2（講稿）、s13 | 第五步部署改成 `./deploy_source.sh`；s13 的舊 `deploy_user.sh` 截圖移除，留「實際輸出截圖待補」 |

仍保留的母專案痕跡（刻意的）：GCP VM 實例名稱仍為 `tw-autotrader`、GitHub 連結指向母專案。

## 語音流水線（配音版 / MP4）

從母專案搬過來的三支腳本，放在 `plans/`：

| 腳本 | 用途 |
|---|---|
| `plans/generate_narration.sh` | 主流水線：`extract` 抽逐頁文字 → `build` 講稿＋配音＋產生講稿版／配音版 |
| `plans/generate_voiceover.sh` | 只重配音（改完講稿重跑，不需要原始 PPT） |
| `plans/ppt_to_mp4.sh` | 配音版 → MP4（LibreOffice→PDF→PNG，逐頁配 mp3） |

### 前置需求

- `node` 18+、`ffmpeg`／`ffprobe`、LibreOffice（`soffice`）
- huashu-design skill：`/home/frank/.agents/skills/huashu-design`
  （內含 `scripts/narrate-pipeline.mjs`、`scripts/tts-doubao.mjs`）
- 豆包 TTS 金鑰放**該 skill 根目錄**的 `.env`：
  `DOUBAO_TTS_API_KEY`、`DOUBAO_TTS_VOICE_ID`（`S_` 開頭＝複刻音色）、
  `DOUBAO_TTS_CLUSTER`、`DOUBAO_TTS_ENDPOINT`
- `python-pptx`／`pypdfium2`：腳本會優先用本專案 `.venv/bin/python3`
  （沒有 `.venv` 才退回系統 `python3`）

### 用法

```bash
cd ~/tw-selfselect/plans

# 1. 抽逐頁文字（給 AI 寫講稿用；不花錢、不呼叫 TTS）
./generate_narration.sh extract "ppt/TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx"

# 2. 講稿 .md → 配音 + 講稿版 + 配音版（會呼叫豆包 TTS，17 頁約 2–5 分鐘）
./generate_narration.sh build \
  "ppt/TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx" \
  "ppt/TW-SELFSELECT台股買賣自動化系統-W1-解說腳本.md"

# 3. 只改了講稿、要重配音
./generate_voiceover.sh "ppt/TW-SELFSELECT台股買賣自動化系統-W1-解說腳本.md" \
                        "ppt/TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx"

# 4. 配音版 → MP4
./ppt_to_mp4.sh "ppt/TW-SELFSELECT台股買賣自動化系統-W1-配音版.pptx"
```

講稿 `.md` 格式（`## slide-N （X 分 Y 秒）` 分段；`**講師提示**：` 不配音、只寫進備註；
`> ` 開頭是引言、不配音）：

```markdown
## slide-7 （1 分 30 秒）
左邊是 VM 的實機儀表板截圖……
**講師提示**：強調示範頁數字不是績效。
```

### 產出

```
plans/ppt/<名稱>-內容.txt            （extract：逐頁文字，給 AI 寫稿）
plans/ppt/<名稱>-narration-script.md （講稿剝掉提示後的 TTS 專用稿）
plans/ppt/<名稱>-講稿版.pptx          （備註＝講稿）
plans/ppt/<名稱>-配音版.pptx          （每頁右下角嵌入 mp3）
plans/ppt/_narration_<安全名>/        （audio/slide-N.mp3、voiceover.mp3、timeline.json）
plans/ppt/<名稱>.mp4
```

以上產物（配音版、MP4、`_narration_*`、內容txt、pipeline 稿）都已加進 `.gitignore`，
只有「講稿版」進版控。

### 對母專案做的兩處修正

1. `python-pptx`／`pypdfium2` 改走 `plans/../.venv/bin/python3`（本專案沒有系統層 pip 套件）。
2. `ppt_to_mp4.sh` 的逐頁合成加上 `-af apad` 並移除 `-shortest`，
   避免音訊比畫面短時把段落提前截斷（時間軸長度會少 1–2 秒）。

驗證：以 2 頁測試簡報跑完整 build → 配音版（2 頁備註＋音訊驗證通過）→ MP4
（9.94 秒，與 timeline 的 4.82+5.06 相符）全程無誤。

## 解說腳本（六份，配音用）

由 `notes_to_script.py` 從「講稿版」的備忘稿反推產生，格式符合
`generate_narration.sh build` 的要求（`## slide-N 標題（X 分 Y 秒）`、
正文、`**講師提示**：`）：

```bash
cd ~/tw-selfselect
.venv/bin/python plans/ppt/notes_to_script.py            # 六份一起轉
.venv/bin/python plans/ppt/notes_to_script.py --force    # 覆寫（備忘稿改過之後）
```

| 解說腳本 | 頁數 | 建議時間合計 |
|---|---:|---:|
| `TW-SELFSELECT台股買賣自動化系統-W1-解說腳本.md` | 17 | 25 分 30 秒 |
| `TW-SELFSELECT台股買賣自動化系統-W2-解說腳本.md` | 28 | 39 分 30 秒 |
| `TW-SELFSELECT台股買賣自動化系統-W3-解說腳本.md` | 24 | 30 分鐘 |
| `TW-SELFSELECT台股買賣自動化系統-W4-解說腳本.md` | 28 | 40 分鐘 |
| `TW-SELFSELECT台股買賣自動化系統-W5-解說腳本.md` | 26 | 42 分鐘 |
| `TW-SELFSELECT台股買賣自動化系統-W6-解說腳本.md` | 24 | 32 分 30 秒 |

轉檔規則：

- 備忘稿首行 `⏱ 建議時間：X` → 標題的時間標籤；標題文字取自投影片標題版面配置區
  （沒有就用字級最大的文字框第一行，清掉尾端標點、問號後的補充說明，最多 28 字）。
- 正文逐行照搬；`【講師提示】…` → `**講師提示**：…`（`build` 會剝掉、不送 TTS）。
- 備忘稿裡的 `---` 分隔線自動濾除（那是舊流水線留下的殘留）。
- 附錄附「時間分配」表（頁碼／標題／建議時間／累計），`build` 會在 `## 附錄` 處截斷，不影響配音。

> 這六份是「依現有備忘稿反推」的結果，內容等同講稿、可直接配音；
> 若要調整語氣或長度，改 `.md` 後跑 `generate_voiceover.sh` 重配即可。

### 實際跑過的驗證（W1）

```bash
cd ~/tw-selfselect/plans
./generate_narration.sh build "ppt/TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx" \
                              "ppt/TW-SELFSELECT台股買賣自動化系統-W1-解說腳本.md"
./ppt_to_mp4.sh "ppt/TW-SELFSELECT台股買賣自動化系統-W1-配音版.pptx"
```

結果：17 頁、實測配音 **14 分 41 秒**（881 秒，比「建議時間」25 分 30 秒快，
因為建議時間是講師含停頓的節奏）、每頁一支 mp3（13.3 MB）、配音版 14 MB、
MP4 23 MB（1920×1080 H.264 + AAC，873 秒）。

過程中修掉三個問題：

| 問題 | 修法 |
|---|---|
| 輸入已是「-講稿版」時輸出變成 `…-講稿版-講稿版.pptx` | `generate_narration.sh`／`generate_voiceover.sh` 先剝掉結尾的 `-講稿版` 再組輸出檔名 |
| 解說腳本的分隔線 `---` 被寫進備忘稿、也送進 TTS | 兩支腳本的第 1 步（講稿→pipeline 稿）與 `build_notes()` 都跳過 `---`／`***`／`___` |
| 舊備忘稿殘留 `---` 已重寫 | 用快取的 `audio_44k/*.mp3` 重跑「備註＋嵌入音訊」步驟（不重新呼叫 TTS） |
