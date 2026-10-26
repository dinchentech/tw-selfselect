# plans/ppt — 教學投影片（W1–W6，講稿版）

從母專案 [tw-autotrader](https://github.com/dinchentech/tw-autotrader) 的
`plans/ppt/TW-AUTOTRADER台股買賣自動化系統-W*-講稿版.pptx` 複製改寫而來，
改成 **tw-selfselect（自選股／每月換股單一資金腿）** 的內容。

> 只複製「講稿版」（含逐頁講稿備註）。母專案另有「原版」與「配音版」（內嵌旁白音檔），
> 配音版沒有複製——旁白已錄好，改文字會跟聲音對不上。

## 相對母檔的變更

| 項目 | 說明 |
|---|---|
| 品牌 | 檔名與標題頁 `TW-AUTOTRADER` → `TW-SELFSELECT` |
| 刪頁（W4） | 23–33（全輪替策略、季度排程、ROTATE_MODE 自動化流程、法人抬轎動能、Group 2）、36（全輪替回測）、38（為什麼大資金不適合全輪替） |
| 刪頁（W6） | 20（「每季選股為何勝 0050」——整頁都是全輪替論述）|
| 表格列刪除 | W4 風險控制頁移除 Group 2 欄；W6 策略選擇建議表移除法人動能、全輪替兩列 |
| 文字改寫 | W1 六大策略→五大策略；W2 掛載用途與 DEBUG 範例去 ROTATE_；W3 法人動能案例改為通用舊回測；W4 策略清單 6→5；W5 回測模式五（法人抬轎）移除；W6 策略備註、持股數目講稿去全輪替 |
| W4「法人確認濾網」頁 | 表格改寫成 tw-selfselect 口徑（15 日法人淨買超、TWSE T86 自動補抓／pass-through、`--no-inst`／`--inst-days`），刪掉全輪替的回測數字列 |
| 全域替換 | `live_trader_multi.py` → `selfselect_trader.py`；`ROTATE_MODE_VAL` → 通用變數示例 |
| W1 第 7 頁「實際運行展示」 | 改用 VM 實機儀表板截圖（`plans/assets/dashboard_real_20261026.png`，已去識別＝只有代號／數字）＋右側白底說明卡；線上示範頁連結另註明「範例資料」 |

驗證：轉換後六個檔以 python-pptx 重新開啟無誤，全文（含講稿備註、表格）掃描
`全輪替｜法人動能｜法人抬轎｜ROTATE_｜live_trader_multi｜TW-AUTOTRADER` 皆 0 命中；
W4/W6 以 LibreOffice 轉 PDF 抽頁目視確認版面正常（頁碼是自動欄位，刪頁後會自己重編）。
W4 另補「keep_wait 人工管理怎麼用」一頁，對應 `策略說明.md` §9.9。

## 檔案

| 檔案 | 頁數 |
|---|---|
| `TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx` | 17 |
| `TW-SELFSELECT台股買賣自動化系統-W2-講稿版.pptx` | 28 |
| `TW-SELFSELECT台股買賣自動化系統-W3-講稿版.pptx` | 24 |
| `TW-SELFSELECT台股買賣自動化系統-W4-講稿版.pptx` | 28（原 39；新增 2 頁：auto 型態感知、keep_wait 人工管理）|
| `TW-SELFSELECT台股買賣自動化系統-W5-講稿版.pptx` | 26 |
| `TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx` | 23（原 21；新增 3 頁：完整流程、生命週期、賣出後會不會補選）|

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
| `TW-SELFSELECT台股買賣自動化系統-W6-解說腳本.md` | 23 | 31 分鐘 |

轉檔規則：

- 備忘稿首行 `⏱ 建議時間：X` → 標題的時間標籤；標題文字取自投影片標題版面配置區
  （沒有就用字級最大的文字框第一行，清掉尾端標點、問號後的補充說明，最多 28 字）。
- 正文逐行照搬；`【講師提示】…` → `**講師提示**：…`（`build` 會剝掉、不送 TTS）。
- 備忘稿裡的 `---` 分隔線自動濾除（那是舊流水線留下的殘留）。
- 附錄附「時間分配」表（頁碼／標題／建議時間／累計），`build` 會在 `## 附錄` 處截斷，不影響配音。

> 這六份是「依現有備忘稿反推」的結果，內容等同講稿、可直接配音；
> 若要調整語氣或長度，改 `.md` 後跑 `generate_voiceover.sh` 重配即可。
