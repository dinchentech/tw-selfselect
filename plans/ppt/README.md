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
| `why_design.pptx` | 6（**直式 9:16 短片用**，深色金融科技風；不是 W 系列）|
| `stock_index/stock_index.pptx` | 6（**直式 9:16**：年化／本益比／回撤／夏普 四個指標＋「40%，但是」）|
| `stock_index_2/stock_index_2.pptx` | 6（**直式 9:16**：K 線／均線／RSI／ATR 四個技術指標）|
| `kmap/kmap.pptx` | 6（**直式 9:16**：怎麼看 K 線 — 紅綠蠟燭／型態／交給程式）|
| `what_for/what_for.pptx` | 6（**直式 9:16**：為什麼收使用授權費＝29 杯咖啡；手做、無產生器）|
| `for_who/for_whom.pptx` | 6（**直式 9:16**：TW-SelfSelect 適合甚麼人；手做＋6 張現畫示意圖＋配音）|
| `about_backtest/about_backtest.pptx` | 6（**直式 9:16**：回測怎麼看——倖存者偏差／前向驗證／滑價／買不到；文案與 6 張圖都由 `make_about_backtest.py` 產生）|
| `git_contain/git_contain.pptx` | 22（**GitHub repo 導覽**，每頁備忘稿＝演講稿；不是 W 系列）|

## why_design（2026-11-01 新增，直式 9:16 短片）

「為什麼我要開發這套股票系統」6 頁短片用投影片，**與 W1–W7（16:9 教學稿）不同系列**：

- 版面：6.20 × 11.02 吋（直式）；深藍黑漸層＋K 線／走勢線光暈＋紅色重點的深色金融科技風。
- 產生器：`plans/ppt/make_why_design.py`。**背景圖用 Pillow 現畫、第 5 頁比較圖用 matplotlib 現畫**
  ⇒ 沒有外部圖檔、沒有版權問題、可重複產生（中間產物放 `TMP/whybuild/`，`TMP/` 不進版控）。
  重跑：`MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_why_design.py`
  預覽：`HOME=$PWD/TMP/lohome soffice -env:UserInstallation=file://$PWD/TMP/lohome/lo --headless --convert-to pdf --outdir TMP/x plans/ppt/why_design.pptx`
- 文字：使用者原稿（原本是 LibreOffice 手拉的 6 頁）**逐字保留**，只加強點字顏色與硬斷行
  （標題「為什麼我要開發／這一套股票系統」、「有了AI還要／自己弄這套系統嗎?」）。
  2026-11-01 使用者裁定改掉原稿三處錯字：「為甚麼」→「為什麼」、「拜股票大事」→「拜股票大師」、
  「回撤也高高達40多%」→「回撤也高達40多%」。半形逗號（`8個月時,`／`實測,`）保留原樣。
  ⚠️ 原手拉排版的檔案已被產生器覆寫（要改文字請改產生器裡的 `BODY`／`COVER` 再重跑）。
- 第 5 頁比較圖：**停泊 0050 口徑、2022-01-01～2026-10-23**（＝README「回測」主表近年那一列）
  目前版本 **+283.1%／MDD −33.4%／夏普 1.18**、0050 **+231.4%／MDD −34.0%／夏普 1.21**。
  重點句（使用者 2026-11-01 裁定、當天改寫）：「**單策略能不能贏 0050 不是重點**／**選股有合乎程式標準就買,**／
  **沒合適的時候就買0050**／⇒ 使用者的獲利最高」。
  ⇒ 本頁**刻意不提**「無停泊（實盤真實）+161.1%」的口徑差異，那是教學稿（W 系列／README 主表）才講的細節。
- 圖案（2026-11-01）：第 2／3／4／6 頁改成**圖示列**——每列一顆圓角圖示磁磚＋文字（不吃自動換行，逐列各自一個 textbox）。
  圖示由 `plans/ppt/why_icons.py` 現畫（Pillow，256×256 PNG，透明底；禁止類用右下角紅色 ✕ 徽章）。
  對照表在 `make_why_design.py::ICONS_ONSCREEN`：`chip`（30 年硬體）、`coins`（拿錢投資）、
  `gauge`（ETF 賺不到 20%）、`question`／`chart_x`／`gear_check`（不懂投資／不懂股票／完成）、
  `arrow_up`／`x_circle`（40%／放棄）、`calendar`（2026-07 起實測）。
  新增圖示：在 `why_icons.py` 的 `GLYPHS` 加一個小函式即可。
- **使用者插畫（2026-11-01 第二輪）**：`plans/ppt/why_design/` 下 5 張 1408×768 科技插畫（使用者提供）當每頁上半部的
  **主視覺橫幅**：置中裁切 → 壓暗 → 底部 1.2 吋漸層淡出接回背景色（`hero_png()`；封面另加 `crop_zoom=1.45` 取景放大）。

  | 頁 | 圖 | 用法 |
  |---|---|---|
  | 1 封面 | `image_1f450dfb.jpg` 玻璃晶片 | 橫幅 6.10 吋、壓暗 16% |
  | 2 動機 | `image_b44847b2.jpg` 金幣＋成長儀表 | 4.40 吋、壓暗 22% |
  | 3 不懂投資→完成 | `image_d9a4591d.jpg` AI 機器人＋程式碼 | 4.40 吋、壓暗 22% |
  | 4 40% 報酬與回撤 | `image_99066f06.jpg` 成長柱狀 | 4.95 吋、**壓暗 55%＋模糊 1.4px**（圖上是示意數字，不能讓人讀到） |
  | 5 比較圖 | —— | 不放插畫，留給真數據圖 |
  | 6 還要自己弄嗎 | `image_8fcf184f.jpg` 2026/07 日曆＋LIVE TESTING | 5.30 吋、壓暗 20% |

- **畫面上只放重點字**：`ONSCREEN`（上畫面，原稿逐字）／`SPOKEN`（旁白，含沒上畫面的句子）。
  沒上畫面的句子寫進該頁**備註**（`⏱ 約 N 秒`／`【旁白】`／`【畫面】`／`【只有語音、不上畫面】`），可交給 TTS 念。
  現況：第 2 頁少 2 句、第 3 頁少 2 句、第 4 頁少 1 句、第 6 頁少 2 句。
- **轉短視頻**：`bash plans/ppt/why_to_mp4.sh`（預設吃 `why_design.pptx`，輸出 `why_design.mp4`，不進版控）。
  成品 **1080×1920、30fps、H.264、faststart**；每頁緩慢推軌（Ken Burns 1.08×、方向逐頁交替）＋ **0.7s 交叉淡入**；
  6 頁 6 秒 ⇒ **32.5 秒**、8.5 MB，本機約 **27～31 秒**跑完（內部超取樣 1.5×；`SS=1` 更快、`SS=2` 更平滑）。
  可調：`SLIDE_SEC`（每頁秒數）、`FADE`（0＝硬切）、`ZOOM`（推軌倍率）、`NARR=<配音目錄>`（接 `_narration_*/` 的旁白，
  有旁白時自動改硬切以確保對嘴）。⚠️ **PPT 內建動畫在 LibreOffice 轉檔時會被拍掉**，所以「動」只能做在影片層。
- **帶旁白的版本（2026-11-01 完成）**：講稿在 `plans/ppt/why_design-解說腳本.md`（`## slide-N` 分段，就是備註裡的旁白）。
  ```bash
  bash plans/generate_voiceover.sh "plans/ppt/why_design-解說腳本.md"        # 豆包 TTS → _narration_why_design-____/
  NARR=plans/ppt/_narration_why_design-____ bash plans/ppt/why_to_mp4.sh     # → why_design.mp4（有旁白）
  ```
  成品 **89.8 秒／20 MB**、6 段旁白（2.8／17.9／10.8／14.3／24.8／19.2 秒；`timeline.json` 為準）、AAC 44.1 kHz，
  有旁白時**改硬切**（交叉淡入會讓旁白與畫面錯開）。改了講稿就重跑上面兩行；`_narration_*` 與 `*.mp4` 都不進版控。


## git_contain（2026-11-03 新增，講稿版）— 「GIT 上面有些甚麼」

導覽 GitHub repo 的 22 頁教材（不是 W 系列課，是「帶你看專案地圖」的單元）：`.cairn`／`config`／`core`／`data`／
`docs`／`esun_sdk`／`plans`／`python_basic`（WSL、GCP、Python 課程三頁）／`scripts`／`strategies`／`test`／`utils`，
再到根目錄的 `README.md`、`backtest.py`、`deploy_source.sh`、`selfselect_trader.py`、`user_strategies.py`，
另有一頁「如何檢視 git 上的 HTML」（Copy path → `htmlpreview.github.com`）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/git_contain/git_contain.pptx` | 22 頁教材，**每頁備忘稿＝演講稿**（`⏱ 建議時間` ＋旁白＋`【講師提示】`）＝**主檔**，要改內容改這份 |
| `plans/ppt/git_contain/add_notes.py` | 演講稿產生器：把 `NOTES` 寫進備忘稿（會先備份原檔到 `TMP/git_contain_backup/`） |
| `plans/ppt/git_contain/git_contain-解說腳本.md` | 由備忘稿反推的講稿（22 段、合計 16 分 25 秒），配音的輸入 |
| `plans/ppt/git_contain/git_contain-講稿版.pptx` | 流水線輸出的講稿版（備忘稿＝解說腳本、右下角喇叭圖示） |
| `plans/ppt/git_contain/git_contain-配音版.pptx` | 每頁嵌入旁白 mp3（20 MB，**不進版控**） |
| `plans/ppt/git_contain/git_contain-配音版.mp4` | 影片版（**不進版控**） |

改講稿的方式：改 `add_notes.py` 裡的 `NOTES` 再重跑，不要直接在 PowerPoint 改備忘稿（會被下一次重跑覆蓋）。

```bash
.venv/bin/python plans/ppt/git_contain/add_notes.py
```

- 建議時間合計 **16 分 25 秒**（最短 25 秒、最長 65 秒），備忘稿共 **6,359 字**。
- 備忘稿格式沿用 W1–W7 慣例（`⏱ 建議時間：…`／正文／`【講師提示】…`），之後要配音或轉 MP4 可直接接
  `notes_to_script.py`（⚠️ 該腳本用 `-講稿版.pptx` → `-解說腳本.md` 的檔名替換，這份檔名不含 `-講稿版`，
  跑之前要先複製成 `git_contain-講稿版.pptx`，否則輸出檔名會蓋回原 pptx）。
- 驗證：寫入後以 python-pptx 重開 22 頁備忘稿皆非空；LibreOffice 轉 PDF 仍為 22 頁、版面未動。

### 配音版與 MP4（2026-11-03 產出）

```bash
cd ~/tw-selfselect
# ① 備忘稿 → 解說腳本（先複製一份 -講稿版 當輸入，避免 notes_to_script 的檔名替換蓋回主檔）
cp plans/ppt/git_contain/git_contain.pptx plans/ppt/git_contain/git_contain-講稿版.pptx
.venv/bin/python plans/ppt/notes_to_script.py plans/ppt/git_contain/git_contain-講稿版.pptx --force
# ② 豆包 TTS ＋ 講稿版／配音版
bash plans/generate_narration.sh build \
  "plans/ppt/git_contain/git_contain-講稿版.pptx" "plans/ppt/git_contain/git_contain-解說腳本.md"
# ③ 配音版 → MP4（這份投影片是 11.02×6.2 吋的非標準尺寸，要指定輸出尺寸才是 1080p）
HOME=$PWD/TMP/lohome RENDER_SCALE=2.4 OUT_SIZE=1920:1080 bash plans/ppt_to_mp4.sh \
  "plans/ppt/git_contain/git_contain-配音版.pptx" \
  "plans/ppt/git_contain/_narration_git_contain-___" \
  "plans/ppt/git_contain/git_contain-配音版.mp4"
```

- 配音：**22 段／1,040.6 秒（17 分 20 秒）**，`_narration_git_contain-___/voiceover.mp3`（8.2 MB）；
  配音版 pptx 20 MB（每頁右下角喇叭）。
- MP4：**1920×1080、30fps、H.264＋AAC、1,031 秒／29.8 MB**（影片長度＝22 段旁白實際長度）；
  抽頁檢查第 1 頁封面與第 7 頁（Copy path／htmlpreview）畫面正常。
- ⚠️ 這份投影片是 **11.02 × 6.2 吋**（不是 13.333×7.5 的標準 16:9），`ppt_to_mp4.sh` 預設 scale=2.0 只會出
  1588×894；要 1080p 請帶 `RENDER_SCALE=2.4 OUT_SIZE=1920:1080`（兩個環境變數是這次新增的，預設值＝舊行為）。
- `.gitignore` 同步補了 `plans/ppt/**/_narration_*/` 與 `plans/ppt/**/*-narration-script.md`
  ——原本只排除 `plans/ppt/` 這一層，子目錄的產物會漏掉。
- 建議只把主檔 `git_contain.pptx`、`add_notes.py`、`git_contain-解說腳本.md` 進版控；
  `-講稿版.pptx` 是流水線中間產物（可由上面 ① 重生成），配音版／MP4／`_narration_*` 都已忽略。

#### 只改版面／標題、旁白沒動 → `revoice`（不用重跑 TTS）

```bash
# ① 沿用既有音檔重做「備註 + 音訊嵌入」（約 2 秒，不呼叫豆包 TTS、不花錢）
bash plans/generate_narration.sh revoice \
  "plans/ppt/git_contain/git_contain.pptx" "plans/ppt/git_contain/git_contain-解說腳本.md"
# ② 重出 MP4（約 4 分鐘：LibreOffice→PDF→22 張 PNG→22 段合成→concat）
HOME=$PWD/TMP/lohome RENDER_SCALE=2.4 OUT_SIZE=1920:1080 bash plans/ppt_to_mp4.sh \
  "plans/ppt/git_contain/git_contain-配音版.pptx" \
  "plans/ppt/git_contain/_narration_git_contain-___" \
  "plans/ppt/git_contain/git_contain-配音版.mp4"
```

- 2026-11-03 18:41 就靠這條路重出過一次：使用者修了 **P7 版面**與 **P8 標題錯字**
  （`沒上git_位置` → `沒上git)位置`），旁白沒動 ⇒ `revoice` 2.3 秒、MP4 3 分 58 秒；
  影片長度不變（1,031 秒）、`解說腳本.md` 的 slide-8 標題同步改成新標題。
- 抽頁驗證：P7（Video 309.9–358.1 s）與 P8（358.1–412.4 s）畫面已是新版。

## cap_mix（2026-11-01 新增，直式 9:16）— 選股結構：大型／中型／小型 × 各策略

回答「2022 年以來的回測，我們選股的市值分級占比、以及各級別用了哪些策略」。5 頁，視覺語言與 `why_design` 相同。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/cap_mix.pptx` | 產出的簡報（5 頁） |
| `plans/ppt/make_cap_mix.py` | **分析**：讀回測輸出 → 分級＋路由 → 統計（寫 `TMP/capmix_stats.json`、`TMP/capmix_picks.csv`） |
| `plans/ppt/make_cap_mix_deck.py` | **版面**：三張 matplotlib 圖＋投影片（沿用 `make_why_design` 的元件） |

重跑：
```bash
# ① 先跑真正的回測（會存 results/…json，內含每月 selection_log；results/ 與 TMP/ 都不進版控）
PRESET=revenue PROFILE=default GROUPS_ONLY=normal STRAT_MODE=form IMM_OVERHEAT=1 ENTRY_OVERHEAT=1 \
  START=2022-01-01 END=2026-10-23 TOP_N=5 INITIAL=1000000 \
  .venv/bin/python scripts/backtest_plan2_monthly_3group.py
# ② 分析 + 出稿
MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_cap_mix.py deck
```

數字（2022-01-01～2026-10-23、實盤口徑、**285 筆選股／57 次選股日／83 檔個股**）：

| 級別 | 筆數 | 占比 | 市值中位數 | 均線交叉 | 突破 | 布林回歸 | VWAP | 順勢合計 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 大型股（前 50 名） | 161 | 56.5% | 3,499 億 | 11% | 69% | 14% | 7% | 80% |
| 中型股（51–150 名） | 124 | 43.5% | 1,262 億 | 6% | 69% | 15% | 10% | 75% |
| 小型股（151 名後） | 0 | 0.0% | — | — | — | — | — | — |

- 全體策略：**突破 68.8%**／布林回歸 14.0%／均線交叉 8.8%／VWAP 8.4% ⇒ **順勢 77.5%／回歸 22.5%**。
- 逐年大型股占比：2022 51%／2023 45%／2024 77%／2025 58%／2026 50%。
- ⚠️ **小型股 0% 是「池子」造成的，不是策略偏好**：選股池＝每季市值前 100 名，151 名以後的股票根本進不了池。
  要真的買小型股得改 `POOL_N`（例：`POOL_N=300`），但那是另一個回測口徑。
- 分級用「全宇宙市值排名」（歷史股本 × 當期收盤，`core/candidate_pool` 同一套算法），不是絕對金額門檻。
- **第 4 頁「逆勢是怎麼被挑到的？」（2026-11-01 追加）**：型態路由的規則是
  - 順勢＝**三條全綠**：① 收盤 > MA20 ② MA20 > MA60 ③ 20 日動能 > 0 ⇒ 動能 > 5% 走 `breakout`、否則 `ma_cross`。
  - 逆勢＝**任一條不綠**，再依「價格站在 20 日線哪一邊」二選一：
    跌破 20 日線 ⇒ `bollinger`（回檔買低）；站在 20 日線上方但 MA20 仍在 MA60 之下 ⇒ `vwap`（不追價，等回到均價）。
  - 實測命中（285 筆）：順勢 **221**（突破 196／均線 25）；逆勢 **64**（布林 **40**／VWAP **24**）。
    布林 40 筆**全部**在月線下方（距 MA20 中位 **−1.4%**）；VWAP 24 筆**全部**在月線上方（中位 **+5.0%**），
    其中 **19 筆**是 MA20 仍在 MA60 之下（其餘為 20 日動能轉負）。
  - 一句話：**逆勢不是猜低點，是「趨勢條件不成立」後的補位**——判斷點一樣直觀，只是把「跌破」與「站上」分開處理。

- 策略＝回測 `STRAT_MODE=form` 的 `pick_strategy_by_form()` 規則（只用選股日以前的資料）。

## stock_index（2026-11-04 新增，直式 9:16）— 四個常見股票指標

「常見股票指標」6 頁直式短片：封面＋**年化／本益比／回撤／夏普**各一頁＋第 6 頁「**40%，但是**」。
視覺語言與 `why_design` 相同（6.20 × 11.02 吋、深藍黑漸層＋K 線殘影、紅色重點）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/stock_index/stock_index.pptx` | **主檔**（6 頁；每頁備忘稿＝講稿）|
| `plans/ppt/make_stock_index.py` | 產生器：背景／版面元件沿用 `make_why_design.py`，四張示意圖用 matplotlib 現畫 |
| `plans/ppt/stock_index/stock_index-解說腳本.md` | 由備忘稿反推的講稿（6 段／**607 字**／約 **2 分 52 秒**），語音的輸入 |

- **文字沿用手稿逐字**（年化／本益比／回撤／夏普的定義與高低情境），只把長段落拆成
  「定義卡＋重點列（圖示＋紅字關鍵詞）＋結論卡」；原稿唯一修訂：本益比那段「市场预期」→「市場預期」（簡體字）。
- **四張圖**（`TMP/whybuild/si_*.png`，產生器現畫、不進版控）：
  ① `si_cagr.png` 複利：同樣 10 年，年化 5%／20%／40% ⇒ ×1.6／×6.2／×28.9（log 軸，差 4.7 倍）。
  ② `si_pe.png` 市場願意給幾倍獲利：EPS 固定 5 元，股價 50（10 倍）vs 150（30 倍）；
     綠＝公司真的賺到的、紅／灰＝市場多付的倍數。
  ③ `si_dd.png` 回撤：上＝淨值＋歷史峰值虛線（中間填紅），下＝水下曲線並標出最大回撤％。
  ④ `si_sharpe.png` 夏普：橫軸波動、縱軸超額報酬＋三條等夏普射線（0.5／1.0／2.0）；
     點出「同樣超額 8%，波動 15% ⇒ 0.53；波動 8% ⇒ 1.00」。
- **第 5 頁計算例補齊（2026-11-04 第四輪，使用者「夏普那個計算例有缺」）**：原本只剩「（10% − 2%）÷ 15% = 0.53」
  一行數字、看不出 10%／2%／15% 各是什麼。改法：①定義卡放回原稿的符號式 **`SR =（R_p − R_f）÷ σ_p`**
  ＋中文式；②新增「計算例」卡三行——**輸入**（投資組合報酬 10%、無風險利率 2%、報酬率標準差 15%）
  →**算式**（`SR =（10% − 2%）÷ 15% = 0.53`）→**白話**（每多承擔 1 單位波動，約換得 0.53 單位超額報酬）；
  ③講稿第 5 段同步把三個輸入唸出來。
- **第 6 頁「40%，但是」（2026-11-04 追加，使用者指定）**：把原本被拖到畫布外（x 為負值、看不到）的那段
  「安聯台灣科技基金 高達40%,但是:」四點搬上畫面——**四點逐字保留**（內扣費用／「高淨值」心理恐懼 (700~800)／
  風險高度集中＋空頭無法空手／規模太大的大象轉身困難），上方是 `40%` 大字＋右側「每年扣 2% 內扣費用 ⇒
  十年終值 ×28.9 → ×25.1（少 13%）」的示意，下方結論卡「年化只算報酬——費用、心理、集中度、規模不進公式，
  但會進你的帳戶」。⚠️ **2%/年 是本頁的示意假設**（台灣主動式基金總費用率常見 1.5%～2.5%），
  講稿的【講師提示】已寫明「安聯 40% 是原稿數字、本專案未查證」。
- 圖示：`why_icons.py` 新增 `percent`／`divide`／`scale` 三顆（`scale`＝天平，用於「規模／取捨」那列）；
  封面四顆＝`percent`／`divide`／`valley`／`gauge`。
- **字級（2026-11-04 第二輪，使用者要求「圖形中的字太小」）**：四張圖裡的刻度 9→**13**、軸標題 8.6–9.6→**11.5–12.5**、
  重點數字 12–13.5→**14–16**、圖內小註 8.6→**11.5**；`si_pe` 的 x 上限 196→216、`si_cagr` 的 x 上限 13.6→16.4，
  讓放大後的標籤不會被切掉；`si_sharpe` 的 A／B 兩點說明改成兩行（放大後單行會超出圖框）；
  `si_dd`／`si_sharpe` 的左邊界 0.135→0.185（不然放大後的「淨值（萬元）」「超額報酬」會壓到刻度），
  回撤圖的「最大回撤 −37%」改成左下空白區＋引線連到谷底點。
  第 6 頁 40% 卡的字級同步放大（13／16／12）。
- **長度（2026-11-04 第三輪，使用者要求「180 秒內，必要時第 6 頁砍掉」）**：講稿從 262 秒／1,810 字壓到
  **172 秒標示／607 字旁白**（12／32／34／28／32／33 秒），以 3.6–4.0 字/秒估 ⇒ 實測約 **154～171 秒**，
  在 180 秒內留 11～28 秒餘裕 ⇒ **第 6 頁保留、不砍**。精簡原則：每頁只留畫面上看得到的重點，
  例子與結論各一句，`【講師提示】`（不進配音）放細節與免責。
- **講稿格式刻意用 `⏱ 建議時間：`＋旁白段落＋`【講師提示】`**（而不是 `why_design` 的 `⏱ 約 N 秒`／`【畫面】`）
  ——這樣 `notes_to_script.py` 與 `generate_narration.sh build` 可以直接吃，要配音時：
  ```bash
  cp plans/ppt/stock_index/stock_index.pptx plans/ppt/stock_index/stock_index-講稿版.pptx
  .venv/bin/python plans/ppt/notes_to_script.py plans/ppt/stock_index/stock_index-講稿版.pptx --force
  bash plans/generate_narration.sh build \
    "plans/ppt/stock_index/stock_index-講稿版.pptx" "plans/ppt/stock_index/stock_index-解說腳本.md"
  ```
  （`-講稿版.pptx` 是中間產物，跑完可刪。）
- 重出 PPT：`MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_stock_index.py`
- 驗證：LibreOffice → PDF → gs 抽頁逐頁目視（6 頁無重疊、無溢出到頁碼下方）；原手拉版備份在
  `TMP/stock_index_backup_20261104/stock_index.pptx`。

### 配音版與 MP4（2026-11-04 產出）

```bash
cd ~/tw-selfselect
# ① 講稿 → 豆包 TTS ＋ 講稿版／配音版（總長 167.6 秒）
bash plans/generate_narration.sh build \
  "plans/ppt/stock_index/stock_index.pptx" "plans/ppt/stock_index/stock_index-解說腳本.md"
# ② 直式 1080×1920 MP4（⚠️ 第 1 個參數給「講稿版」——配音版會把右下角喇叭圖示渲進畫面）
HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
  "plans/ppt/stock_index/stock_index-講稿版.pptx" \
  "plans/ppt/stock_index/_narration_stock_index" \
  "plans/ppt/stock_index/stock_index-配音版.mp4"
```

- 配音：**6 段／167.6 秒**（10.6／33.6／28.6／27.2／33.4／31.9 秒＋段間 0.4 秒），`voiceover.mp3` 1.3 MB；
  配音版 pptx 3.5 MB（每頁右下角喇叭，實測驗證 6 頁備註＋音訊都正確）。
- MP4：**1080×1920、30 fps、H.264＋AAC、165.4 秒（2 分 45 秒）、5.8 MB**；音量 mean −20.2 dB／max −1.1 dB。
  抽格驗證 5／25／55／85／115／150 秒（封面、夏普、第 6 頁）畫面正常、無喇叭圖示。
- 兩者依 `.gitignore` 不進版控（`plans/ppt/**/*-配音版.pptx`／`*.mp4`／`_narration_*/`／`*-narration-script.md`）。
- 原手稿留下的痕跡：頁碼原本沿用 `why_design` 的 `01/06`～`06/06` 且缺 05（中間是 5 頁）；
  補上第 6 頁後**頁碼自然回到 `01/06`～`06/06`**。兩段被拖到畫布外的文字框：
  「安聯台灣科技基金」四點已搬成第 6 頁；「夏普等級」已做成第 5 頁上的三個等級籤。

## stock_index_2（2026-11-04 新增，直式 9:16）— K 線／均線／RSI／ATR

`stock_index` 的姊妹作：封面＋**K 線圖／均線（MA）／RSI／ATR** 各一頁＋第 6 頁「但是，不要單獨用」。
內容**摘用 `策略說明.md` 附錄 B**（技術分析的核心指標的白話解讀／典型用法／關鍵提醒），並補附錄 D（RSI）、
附錄 E（ATR）、附錄 H（MA vs EMA）的公式與門檻。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/stock_index_2/stock_index_2.pptx` | **主檔**（6 頁；每頁備忘稿＝講稿）|
| `plans/ppt/make_stock_index_2.py` | 產生器：版面元件直接 import `make_stock_index`（卡／圖卡／重點列／講稿格式），四張圖 matplotlib 現畫 |
| `plans/ppt/stock_index_2/stock_index_2-解說腳本.md` | 由備忘稿反推的講稿（6 段／**610 字**／約 **2 分 41 秒**），配音的輸入 |

- ⚠️ **來源**：使用者給的 GitHub 連結（`dinchentech/tw-autotrader` 的 `策略說明.md` 附錄 B）**目前回 404**
  （私有或已改名），所以摘用的是本 repo 內同一份血緣的 `策略說明.md`（附錄 B 在第 1942 行、D 在 1971、E 在 1990、H 在 2066）。
- **四張圖用同一檔合成股票的 95 個交易日**（`make_stock_index_2.py::series()`，三段 regime：上升 → 回檔 → 波動放大上攻），
  所以各頁的價格走勢是同一條，只是窗口／面板不同。K 線頁取近 26 日，其餘三頁用滿 95 日。
- 圖案重點：
  ① K 線：紅漲綠跌蠟燭（台股慣例）＋反白虛線框標出「長紅」那根，四邊直接標**最高／收盤／開盤／最低**
     （深色圓角底避免壓在 K 線上讀不清）。
  ② 均線：收盤＋MA5／MA20／MA60，程式找出**黃金交叉／死亡交叉**並標點。
  ③ RSI：上＝價格、下＝RSI(14)；70／30 帶底色與標籤（50 中軸只留虛線，y 軸刻度已有 50）。
  ④ ATR：上＝價格、下＝ATR(14) ÷ 股價；畫出本專案兩條門檻 **0.5%（ma_cross）／1.0%（breakout）**。
- 圖示：`why_icons.py` 新增 `candle`（K 線）／`ma_lines`（均線）／`pulse`（心率＝RSI）／`range`（振幅＝ATR）／
  `bars`（成交量）／`thermo`（情緒溫度計＝KD）。
- 講稿 6 段 **161 秒標示／610 字**（13／30／30／30／31／27），3.6–4.0 字/秒估 **154～171 秒**（一樣壓在 180 秒內）。
  `【講師提示】`放不進畫面的細節：台股紅漲綠跌、本專案均線全用 MA 且 ma_cross 是 MA9×MA21、
  RSI 兩個週期（5 日 vs 約 14 日）別混淆、ATR 的兩種 TR 口徑（breakout 不含跳空）。
- 重出：`MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_stock_index_2.py`
- 驗證：LibreOffice → PDF → gs 抽頁逐頁目視（6 頁無重疊、無溢出到頁碼下方）。

### 配音版與 MP4（2026-11-04 產出）

```bash
cd ~/tw-selfselect
bash plans/generate_narration.sh build \
  "plans/ppt/stock_index_2/stock_index_2.pptx" "plans/ppt/stock_index_2/stock_index_2-解說腳本.md"
HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
  "plans/ppt/stock_index_2/stock_index_2-講稿版.pptx" \
  "plans/ppt/stock_index_2/_narration_stock_index_2" \
  "plans/ppt/stock_index_2/stock_index_2-配音版.mp4"
```

- 配音：**6 段／153.7 秒**（12.0／26.0／25.9／31.2／28.0／28.3 秒＋段間 0.4 秒），`voiceover.mp3`；
  配音版 pptx 每頁右下角喇叭，產生時已驗證 6 頁備註＋音訊都正確。
- MP4：**1080×1920、30 fps、H.264＋AAC、151.5 秒（2 分 31 秒）、5.6 MB**；音量 mean −19.5 dB／max −1.2 dB。
  抽格 5／20／45／80／110／140 秒（封面、K 線、ATR、第 6 頁）畫面正常、無喇叭圖示。
- 兩者依 `.gitignore` 不進版控（`plans/ppt/**/*-配音版.pptx`／`*.mp4`／`_narration_*/`／`*-narration-script.md`）。

## strategy_mp4（2026-11-04 新增）— 策略動畫（`docs/*-animation.html`）＋旁白

把 `docs/` 底下那幾支**策略動畫 HTML** 輸出成 MP4 並配旁白。第一支是 **MA CROSS**。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/strategy_mp4/ma_cross-配音版.mp4` | **成品**：1920×1080、25 fps、H.264＋AAC 44.1 kHz 立體聲、**65.96 秒**、3.1 MB |
| `plans/ppt/strategy_mp4/ma_cross-靜音版.mp4` | 只有畫面的母帶（要換旁白/配樂就從這支重混） |
| `plans/ppt/strategy_mp4/ma_cross-講稿.md` | 四段旁白（對齊動畫四幕）＋時間軸 |
| `docs/ma_cross-animation.html` | 動畫原檔（`SCENE_DURATIONS = [10, 18, 18, 18]` ⇒ 64 秒四幕）|

- ⚠️ **使用者原本放的 `MA-CROSS.MP4` 內容其實是「布林通道」動畫**（分頁標題 `docs/bollinger-animation.html`、
  畫面「布林通道／統計學的價格走廊」「瘋狂頂點 SELL」），不是 MA 交叉 ⇒ 已改名為 **`bollinger-錄影版.mp4`**（保留原檔），
  MA CROSS 另從 `docs/ma_cross-animation.html` 重新輸出（下表第二組）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/strategy_mp4/bollinger-配音版.mp4` | **成品**：1920×1080、25 fps、H.264＋AAC 44.1 kHz、**66.0 秒**、4.4 MB |
| `plans/ppt/strategy_mp4/bollinger-靜音版.mp4` | 只有畫面的母帶 |
| `plans/ppt/strategy_mp4/bollinger-講稿.md` | 四段旁白（對齊四幕：10／16／18／20 秒） |
| `plans/ppt/strategy_mp4/bollinger-錄影版.mp4` | 使用者原本的螢幕錄影（1920×1032、含瀏覽器分頁，只作對照） |

- **布林通道旁白**（實測 8.86／15.84／13.87／15.22 秒，貼在 0／10／26／44 秒，都在該幕窗內）：
  ① 散戶為什麼買高賣低：恐懼時拋售、貪婪時追高 ② 中軌 MA20 是平均成本、上下軌 ±2σ、95.4% 價格在通道內
  ③ 價格 < 下軌＋RSI < 30＝黃金冰點（均值回歸買點，多數人反而停損）④ 價格 > 上軌＋RSI > 70＝瘋狂頂點（該賣）。
  驗證：`silencedetect` 8.53→10.44 秒為段間空白、抽格 30／50 秒分別對到 BUY／SELL 幕；音量 mean −20.4 dB／max −2.8 dB。
- 流程（三步）：
  ```bash
  # ① 動畫 HTML → 影片（Playwright；這裡的 chromium 裝在 TMP，不進版控）
  #    ⚠️ 要在 HTML 補 window.__ready（第一帧設 true），否則 render-video.js 抓不到 t=0、會從動畫中段開始
  NODE_PATH=$PWD/TMP/pw/node_modules PLAYWRIGHT_BROWSERS_PATH=$PWD/TMP/pw/browsers \
    node ~/.agents/skills/huashu-design/scripts/render-video.js \
    TMP/mac/render/ma_cross.html --duration=66 --width=1920 --height=1080
  # ② 旁白逐段 TTS（每段長度要落在該幕的秒數內：10／18／18／18）
  node ~/.agents/skills/huashu-design/scripts/tts-doubao.mjs --text "…" --out TMP/mac/audio/s1.mp3
  # ③ 依幕起點貼上旁白（adelay）+ 增益，影片串流直接 copy
  ffmpeg -y -i ma_cross.mp4 -i s1.mp3 -i s2.mp3 -i s3.mp3 -i s4.mp3 \
    -filter_complex "[1:a]adelay=0:all=1[a1];[2:a]adelay=10000:all=1[a2];[3:a]adelay=28000:all=1[a3];[4:a]adelay=46000:all=1[a4];\
      [a1][a2][a3][a4]amix=inputs=4:normalize=0:dropout_transition=0,volume=3.5dB,alimiter=limit=0.97[a]" \
    -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -ar 44100 -ac 2 -movflags +faststart ma_cross-配音版.mp4
  ```
- 旁白（4 段，實測 8.45／17.62／16.22／15.65 秒，貼在 0／10／28／46 秒，都在該幕窗內；段間留 1～2 秒空白）：
  ① 開場「波段行情來的時候，最怕被甩轎」② 兩條均線 MA9 快／MA21 慢＋ATR 過濾假訊號
  ③ 黃金交叉＝買：MA9 突破 MA21＋ATR÷股價 ≥ 0.5% ④ 死亡交叉＝賣＋「順勢而為」總結。
- 驗證：抽格 5／14／30／50 秒確認畫面與旁白同步（14 秒＝第 2 幕、30 秒＝第 3 幕 BUY）；
  `silencedetect` 確認 8.06→10.28 秒是段間空白；音量 mean −20.2 dB／max −2.7 dB。
- 重出成本：Playwright chromium（`TMP/pw/browsers`，約 300 MB，只在第一次要）＋ TTS 四段約 20 秒＋混音 1 秒。

### 2026-11-04 修正：`bollinger-animation.html` 的買賣點畫錯（使用者回報「賣點比買點早」）

- **兩個原因**：① `generatePriceData()` 用 `Math.random()` ⇒ 每次載入都是新的走勢，買賣點位置亂跳、影片與網頁不是同一條；
  ② `BUY_IDX`／`SELL_IDX` **只判斷「跌破下軌／突破上軌」，沒判斷 RSI**（畫面上的 condition-chip 明明寫了 RSI < 30／> 70），
  而且兩者各自往前找「第一個」命中 ⇒ 只要第一次突破上軌發生在第一次跌破下軌之前，就會變成**先賣後買**。
- **修法**：① 改用固定種子 PRNG（`mulberry32`，`PRICE_SEED = 476100`）⇒ 同一條走勢可重現；
  ② 買賣點改成「通道＋RSI」兩個條件都成立；③ 時序強制**先買後賣**（找到 BUY 之後才找 SELL）。
  以種子 476100 實測：BUY 在 i=59（回檔段低點、RSI 1）、SELL 在 i=88（本波最高點、RSI 89、賣後走低）；
  同一條資料用**舊邏輯**會選到 SELL(i=22) / BUY(i=59)，就是使用者看到的「先賣後買」。
- 影片已重出（`bollinger-配音版.mp4`／`bollinger-靜音版.mp4`，66.0 秒；旁白與時間軸不變）。
- 已 push：`main` 2ba9527 → `503bce7`，並同步到 `gh-pages`（a5c2059 → ed19103）⇒
  線上 `https://dinchentech.github.io/tw-selfselect/docs/bollinger-animation.html` 已確認是修正版。

### 其餘三支動畫也改成固定種子（2026-11-04 第二輪，`main` 503bce7）

`ma_cross`／`breakout`／`vwap` 原本也是 `Math.random()`（每次重整走勢都不同，影片與網頁不是同一條）：

| 動畫 | 預設種子 | 實測訊號（頁面載入值） |
|---|---:|---|
| `ma_cross-animation.html` | 20261104 | 黃金交叉 **i=55**（ATR 1.07%）、死亡交叉 **i=120**（ATR 1.01%） |
| `breakout-animation.html` | 14 | BUY **i=64**（突破段）、SELL **i=105**（跌破段），ATR 皆 ≥1% |
| `vwap-animation.html` | 6 | BUY **i=44**（下偏離、RSI 0）、SELL **i=91**（上偏離、RSI 100） |

- 一律加 `mulberry32` PRNG；`generateHighLow()`／`calcVWAP()` 的雜訊與成交量權重也吃同一個 PRNG。
- `vwap` 的買賣點**改成先買後賣**（與 bollinger 同一個 bug：各自找第一個命中會畫成先賣後買）。
- 除錯方式：console 執行 `window.__SEED = 12345` 再重整即可試不同種子（出貨用預設值）。
- 種子怎麼挑：`TMP/mac/test_seeds.cjs`（Playwright 逐個種子載入頁面、讀 `BUY_IDX`／`SELL_IDX`／金叉死叉索引，
  再要求訊號落在正確段落＋條件成立）；四支頁面載入皆無 JS 錯誤。
- **MA CROSS 影片因資料改變已重出**（`ma_cross-配音版.mp4` 66.0 秒／3.2 MB；旁白與時間軸不變，金叉在 34 秒、死叉在 58 秒抽格驗證）。
- **四支策略動畫都有配音版了**（2026-11-04 第三輪）：`breakout` 與 `vwap` 比照同一套流程補上。

| 影片 | 長度 | 旁白分段（貼在 0／10／28／46 秒） | 大小 |
|---|---:|---|---:|
| `ma_cross-配音版.mp4` | 66.0 s | 8.45／17.62／16.22／15.65 | 3.2 MB |
| `bollinger-配音版.mp4` | 66.0 s | 8.86／15.84／13.87／15.22 | 4.5 MB |
| `breakout-配音版.mp4` | 66.0 s | 9.22／15.84／14.66／14.26 | 4.3 MB |
| `vwap-配音版.mp4` | 66.0 s | 9.07／16.82／17.21／15.48 | 5.4 MB |

- 四支都是 1920×1080／25 fps／H.264＋AAC 44.1 kHz 立體聲、音量 mean −20.1～−20.4 dB／max −2.7～−2.8 dB；
  每支另附 `-靜音版.mp4`（母帶）與 `-講稿.md`（四段旁白＋時間軸）。
- `breakout` 旁白：飆股特性 → 唐奇安通道（20 日高／低＋ATR 過濾）→ 突破天花板買（ATR ≥ 1%）→ 跌破地板賣。
- `vwap` 旁白：恐慌殺低 → VWAP 是法人成本、±1.5σ 偏離帶＋RSI(5) → 跌破 −1.5σ 且 RSI < 30 買 → 漲過 +1.5σ 且 RSI > 70 賣。
- 抽格驗證：breakout 34 秒＝BUY 突破點、vwap 34 秒＝BUY（RSI 0）／52 秒＝SELL（RSI 100），買點都在賣點左邊。

### 2026-11-04 第四輪：breakout 的賣點對準山頂（使用者：「買入點跟賣出點對的不是很準」）

- 診斷：**標記程式沒錯，是走勢形狀的問題**。原本 68–78% 是「高檔盤整」、之後才慢慢跌破 20 日最低，
  所以山頂會提前十幾根、賣點落在離山頂很遠的右下方（舊種子 14：山頂 i=91、賣點 i=105、比山頂低 1.1%）。
  買點本身是準的（i=64 正好是價格穿過「20 日最高」那一根）。
- 改法：① 68–78% 改成「一路衝高到波段高點」（不再先盤頭）；② 78–86% 改成更陡的急殺
  ⇒「跌破 20 日最低」自然貼在山頂右側。③ 重新挑種子：**14 → 23**。
- 實測（種子 23）：BUY **i=64**（突破當根、ATR 1.05%）、SELL **i=103**（山頂 i=101 之後 **2 根**、只回落 **1.3%**、ATR 1.0%）。
- 影片重出：`breakout-配音版.mp4`／`breakout-靜音版.mp4`（66.0 秒／4.4 MB，旁白不變）。
- 已 push：`main` 571cf71、`gh-pages` ee8c633，線上頁面已驗證是種子 23 版。

### 2026-11-04 第五輪：vwap 的買點貼近低點（使用者同意）

- 舊種子 6：買點 i=44，但價格之後一路陰跌到 **i=73** 才見底（差了 29 根，看起來像買在半山腰）。
- 改種子 **6 → 18288**（掃 20 萬個種子，以「買點離低點最近」排序）：
  **BUY i=44**（低點 i=52、只高 0.86%）、**SELL i=96**（山頂 i=99，是山頂的 **99.8%**、山頂前 3 根）。
- 條件（跌破 VWAP−1.5σ＋RSI<30／漲過 +1.5σ＋RSI>70）與「先買後賣」時序都沒改，只換一條走勢。
- 影片重出：`vwap-配音版.mp4`／`vwap-靜音版.mp4`（66.0 秒／5.4 MB，旁白不變）。
- 已 push：`main` b008018、`gh-pages` 134c3fb，線上已驗證。
- 挑種子工具：`TMP/mac/find_vwap_seed.cjs`／`find_breakout_seed.cjs`（純數學掃種子，不開瀏覽器）。

## kmap（2026-11-04 新增，直式 9:16）— 怎麼看 K 線

6 頁直式短片：封面／**紅綠蠟燭**（開高低收、實體與影線）／**三個單根型態**（長紅・長綠・錘子線）／
**兩根一組的型態**（十字星・多頭吞噬・空頭吞噬）／**同一根位置不同**（型態是機率，要看位置與確認）／
**所以你不用自己看**（K 線交給程式與 AI）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/kmap/kmap.pptx` | **主檔**（6 頁；每頁備忘稿＝講稿）|
| `plans/ppt/make_kmap.py` | 產生器（版面元件沿用 `make_stock_index`，四張示意圖 matplotlib 現畫）|
| `plans/ppt/kmap/kmap-解說腳本.md` | 由備忘稿反推的講稿（6 段／**544 字**／約 **2 分 48 秒**）|
| `plans/ppt/kmap/kmap-配音版.mp4` | **成品**：1080×1920、30 fps、H.264＋AAC 44.1 kHz、**135.2 秒（2 分 15 秒）**、6.7 MB |

- 四張圖：① 一根 K 線標開／高／低／收＋實體、上影線、下影線（紅 K／綠 K 各一）② 長紅／長綠／錘子線
  ③ 十字星／多頭吞噬／空頭吞噬（吞噬用虛線框標「今天的範圍」）④ 低檔錘子 vs 高檔錘子（同型態不同位置）。
- 講稿 6 段 **137.4 秒**（12.8／26.2／25.6／31.0／18.8／20.7），3.6–4.0 字/秒估 138–153 秒，實際配音 137.4 秒 ⇒
  **影片 135.2 秒，在 3 分鐘內**。`【講師提示】`放不進畫面的補充（台股紅漲綠跌、黑 K＝綠 K、本專案不看單根型態做決策）。
- 最後一頁的結論就是重點：**使用者不用看 K 線**——程式每天算均線／型態／ATR／RSI，選股與進出場自動判斷，
  使用者只看 Telegram 通知與儀表板。
- 重出：`MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_kmap.py`
- 配音＋MP4（同 stock_index 的兩行）：
  ```bash
  bash plans/generate_narration.sh build "plans/ppt/kmap/kmap.pptx" "plans/ppt/kmap/kmap-解說腳本.md"
  HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
    "plans/ppt/kmap/kmap-講稿版.pptx" "plans/ppt/kmap/_narration_kmap" "plans/ppt/kmap/kmap-配音版.mp4"
  ```
- 驗證：LibreOffice→PDF 逐頁目視（6 頁無重疊）；MP4 抽格 8／30／60／90／120 秒對到 P1／P2／P4／P5／P6；
  音量 mean −19.7 dB／max −1.1 dB。

## what_for（2026-11-05 新增，直式 9:16）— 為什麼收使用授權費（29 杯咖啡）

使用者手做的 6 頁直式短片，回答「TW-SelfSelect 為什麼收使用授權費」：封面（一個帳戶＝29 杯星巴克中杯咖啡）／
**Open source 不等於 Freeware**（免費看程式、真錢上實盤才收費）／**82 檔、14,115 行＋AI 跳不過的實盤實測**／
**8 個月時年獲利 40%，但回撤 40 幾% ⇒ 放棄那一版**（現在版本年化 30% 左右、不集中中小股、不易滑價）／
**目前版本 vs 0050 比較圖**／**花 29 杯咖啡？**（會用 WSL＋裝 GCP ⇒ 先試跑 2～3 個月，滿意才下單）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/what_for/what_for.pptx` | **主檔**（6 頁，使用者手做、沒有產生器腳本）|
| `plans/ppt/what_for/what_for-解說腳本.md` | 旁白講稿（6 段／約 **2 分 36 秒**；本次新增）|
| `plans/ppt/what_for/_narration_what_for/` | 豆包 TTS 產物（`audio/`＋`audio_44k/`＋`timeline.json`＋`voiceover.mp3`）|
| `plans/ppt/what_for/what_for-講稿版.pptx` | 備註＝講稿（流水線產物）|
| `plans/ppt/what_for/what_for-配音版.pptx` | 每頁右下角喇叭｜`what_for-配音版.mp4`＝1080×1920 影片 |

- **編輯史**：這份是從 `why_design.pptx` 複製改文字來的，原備忘稿還留著 why_design 的舊旁白（「為什麼我要開發這一套股票系統」等）；
  2026-11-05 配音時已用新講稿整批覆寫（`build` 會蓋掉備註，所以改文字要改講稿再重跑，不要只改 PowerPoint 備註）。
- 講稿 6 段，**配音實測 163.4 秒**（10.03／27.05／26.78／28.63／50.42／18.26 秒＋段間 0.4 秒），
  `_narration_what_for/voiceover.mp3` 1.3 MB；配音版 pptx 3.8 MB（6 頁備註＋音訊驗證通過）。
- MP4：**1080×1920、30 fps、H.264＋AAC 44.1 kHz 立體聲、161.2 秒（2 分 41 秒）、6.8 MB**；
  音量 mean −23.6 dB／max −4.6 dB。抽格 4／14／42／69／98／149 秒對到 P1～P6、無喇叭圖示。
- 第 5 頁比較圖的數字與 README 主表一致（**停泊口徑、2022-01-01～2026-10-23**）：
  目前版本 **+283.1%／MDD −33.4%／夏普 1.18**、0050 **+231.4%／−34.0%／1.21** ⇒ 講稿就照這三個數字唸
  （夏普 1.18 對 1.21 略輸，不回避）。第 4 頁上半插畫上的 `REVENUE +14.8%`／`SHARPE 1.65` 是示意圖、不是本專案數據，講稿沒提它。
- **主檔第 5 頁錯字已修（2026-11-05）**：「對於一個單純的投資**著**」→「投資**者**」（使用者裁定「改，並重出」）。
  改完走 `revoice`（沿用既有音檔、不重跑 TTS）＋重出 MP4，兩行：
  ```bash
  bash plans/generate_narration.sh revoice "plans/ppt/what_for/what_for.pptx" "plans/ppt/what_for/what_for-解說腳本.md"
  HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
    "plans/ppt/what_for/what_for-講稿版.pptx" "plans/ppt/what_for/_narration_what_for" \
    "plans/ppt/what_for/what_for-配音版.mp4"
  ```
  影片長度不變（161.2 秒），抽格 98 秒已確認畫面是「投資者」。原檔備份在 `TMP/whatfor_build/what_for.pptx.bak`。
- 配音＋MP4（第一次）：
  ```bash
  bash plans/generate_narration.sh build \
    "plans/ppt/what_for/what_for.pptx" "plans/ppt/what_for/what_for-解說腳本.md"
  # ⚠️ 第 1 個參數給「講稿版」——配音版會把右下角喇叭圖示渲進畫面；直式要 RENDER_SCALE=2.45
  HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
    "plans/ppt/what_for/what_for-講稿版.pptx" "plans/ppt/what_for/_narration_what_for" \
    "plans/ppt/what_for/what_for-配音版.mp4"
  ```
  `ppt_to_mp4.sh` 預設吃 `_narration_*/audio/`（TTS 原生 24 kHz 單聲道）；要 44.1 kHz 立體聲就照上面把
  `audio_44k/` 當 `audio/` 餵進去（本次做法：`TMP/wf_narr/` 內放 `timeline.json`＋指向 `audio_44k/` 的 `audio` 連結）。

## for_who（2026-11-05 新增，直式 9:16）— 「適合甚麼人」＋6 張示意圖

⚠️ **目錄叫 `for_who/`、主檔叫 `for_whom.pptx`**（使用者命名，兩者不對稱，找檔案時別找錯）。
使用者手做的 6 頁直式短片（版型沿用 `what_for`：深藍漸層底＋橘紅走勢線），原本**只有文字、上半頁大片空白**；
本輪補上 **6 張現畫示意圖 ＋ 旁白配音 ＋ MP4**。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/for_who/for_whom.pptx` | **主檔**（6 頁；已嵌入 6 張示意圖，shape 名稱 `ART-forwhom-pN`）|
| `plans/ppt/for_who/make_for_whom_art.py` | **產生器**：Pillow 現畫 6 張圖 → 寫 `art/pN.png` → 嵌回主檔（可重複執行，會先刪同名 shape）|
| `plans/ppt/for_who/art/p1–p6.png` | 產出的示意圖（1019×660～1072 px、透明底；200 px = 1 吋）|
| `plans/ppt/for_who/for_whom-解說腳本.md` | 旁白講稿（6 段／約 2 分 32 秒估算）|
| `plans/ppt/for_who/for_whom-講稿版.pptx` | 備註＝講稿（流水線產物）|
| `plans/ppt/for_who/for_whom-配音版.pptx` | 每頁右下角喇叭（3.4 MB）|
| `plans/ppt/for_who/for_whom-配音版.mp4` | **成品**：1080×1920、30 fps、H.264＋AAC 44.1 kHz、**130.8 秒（2 分 11 秒）**、5.2 MB |

### 六張圖各是什麼（都是「帶資訊」的示意圖，不是裝飾）

| 頁 | 圖 | 內容 |
|---|---|---|
| 1 | 適用條件清單 | 兩張卡：「你必須會的」3 列（WSL 終端機／GCP 雲端／DSH 指揮 AI，橘框）＋「你不必會的」3 列（懂股票／懂策略／寫程式，右下角紅 ✕ 徽章）|
| 2 | WSL → GCP | 左：終端機視窗（`$ ls`／`cd tw-selfselect`／`python selfselect_trader.py`）＋「WSL ＝ 本機的 Linux」；右：雲朵＋VM＋「固定 IP 35.229.x.x」徽章；中間 `ssh` 箭頭；底部「常用到的只是檔案與目錄指令」|
| 3 | 你說話 → AI 改 → 程式 | 左：你的指令泡泡「把每月選股改成 3 檔」；中：DSH／AI 磁磚；右：`selfselect_trader.py` 檔卡（`TOP_N = 5` → `TOP_N = 3` 綠字）＋「AI 改好，自己跑完測試」；底部「82 檔／14,115 行：你不需要自己動它」|
| 4 | 每月選股流程 | FinMind／TWSE → 每月自動選股（N 檔）→「有合乎標準的股票？」→ 是：買進 N 檔／否：保留現金·買 0050 |
| 5 | 四種策略迷你走勢 | 2×2 面板：均線交叉（快線穿慢線）／布林通道（跌破下軌再回月線）／VWAP 回歸（低於偏離帶）／突破（漲過 20 日高），各標「⇒ 買」；底部「程式依各股現況挑 1 種——買入時就決定」|
| 6 | 費用 | 咖啡杯＋兩條比例長條：**授權 29 杯（一次性，滿格）** vs **GCP 月費 < 1 杯**（1/29 寬的綠條）；底部「沒有訂閱費、沒有顧問費」|

- **畫法**：`PIL` 現畫、透明底 PNG；色票沿用 `make_why_design.py` 家族（`ACCENT #FF5A4D`、`ORANGE #F2A454`、
  `BLUE #7CACDE`、`TEAL #56BEA0`），圖示磁磚語言沿用 `why_icons.py`（深藍磁磚＋細框＋禁止類紅 ✕ 徽章）。
  畫布 200 px ＝ 1 吋 ⇒ **圖裡設 10 pt 就是投影片上實際 10 pt**，嵌入時用原吋數（不縮放）。
- **字級（2026-11-05 第二輪，使用者「圖的字太小了加大些」）**：圖內標籤 **16 pt**（原 11.5）、卡／面板標題 **14 pt**（原 10.5）、
  說明與圖說 **12.5–13.5 pt**（原 10）、主數字 **17–19 pt**（原 12）、終端機 mono **12.5 pt**（原 9.5）；
  最小不低於 12 pt。放大字級同時把磁磚（0.42→0.46 吋）、方框、面板（2.32×1.92→2.38×2.16 吋）一起放大，
  並重排 P2（終端機改成整排寬＋雲端卡移到下方，ssh 箭頭往卡片指）、P3（中間標籤與檔案卡分開）、
  P4（方框與間距壓縮）。**改字級時務必重看溢位**：這輪踩到三個坑——堆疊卡片右緣超出畫布、
  P4 底部兩格被畫布切掉、P3 的 `DSH／AI` 標籤壓到卡片左緣。
- 擺放位置（吋，左上角）：P1 `(0.55, 0.40)`／P2 `(0.55, 0.70)`／P3 `(0.55, 0.90)`／P4 `(0.55, 0.66)`／
  P5 `(0.55, 1.92)`／P6 `(0.55, 0.92)`——都落在各頁文字上方的空白區；P5 的標題在 1.24 吋、下方卡片在 6.86 吋，
  所以圖放 1.92（高 4.78 吋）。
- 逐頁目視驗證方式：`soffice → PDF → pypdfium2 轉 PNG`（LibreOffice 對 PNG 透明底處理正確，與 Pillow 合成的預覽一致）。

### 重出

```bash
cd ~/tw-selfselect
# ① 畫圖＋嵌回主檔（會先備份 for_whom.pptx → TMP/forwhom_build/for_whom.pptx.bak，只備份第一次）
.venv/bin/python plans/ppt/for_who/make_for_whom_art.py          # 或 `draw` 只畫、`embed` 只嵌
# ② 旁白沒動只改版面 ⇒ revoice（2 秒、不呼叫 TTS）；要重配音就把 revoice 換成 build
bash plans/generate_narration.sh revoice "plans/ppt/for_who/for_whom.pptx" "plans/ppt/for_who/for_whom-解說腳本.md"
# ③ 出片（⚠️ 第 1 個參數給「講稿版」；44.1 kHz 音源從 audio_44k 餵）
HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
  "plans/ppt/for_who/for_whom-講稿版.pptx" "plans/ppt/for_who/_narration_for_whom" \
  "plans/ppt/for_who/for_whom-配音版.mp4"
```

- 配音：**6 段／133.0 秒**（13.25／30.65／21.58／25.03／26.42／13.85 秒＋段間 0.4 秒）；
  `_narration_for_whom/voiceover.mp3` 1.3 MB；配音版 pptx 3.4 MB（6 頁備註＋音訊驗證通過；2026-11-05 第二輪加大圖內字級後重出，配音未重跑）。
- MP4 音量：mean −23.4 dB／max −4.7 dB；抽格 5／25／55／79／105／125 秒對到 P1～P6、無喇叭圖示。
- **數字口徑**：講稿只講畫面上有的東西（14,115 行／4 種策略／29 杯／0050），沒有新增未經查證的數字；
  P4 的「停泊」與 P5 的 4 策略路由，細節寫在【講師提示】不進配音。

## about_backtest（2026-11-05 新增，直式 9:16）— 回測怎麼看：**4 件**會騙你的事

主檔是使用者從 `for_who/for_whom.pptx` 複製過來當版型的（深藍漸層底＋K 線背景**原樣保留**），
內容原先是「適合甚麼人」⇒ 本輪**重寫 6 頁文案＋每頁一張現畫示意圖**，並補上旁白配音與 MP4（1080×1920）。

| 檔案 | 用途 |
|---|---|
| `plans/ppt/about_backtest/about_backtest.pptx` | **主檔**（6 頁；圖的 shape 名稱 `ART-abt-pN`，文字 `TXT-*`、紅線條 `ACCENT-bar`）|
| `plans/ppt/about_backtest/make_about_backtest.py` | **產生器**：畫 6 張圖 → 寫 `art/pN.png` → **清掉非背景的所有 shape 再重畫文字＋嵌圖**（可重複執行）|
| `plans/ppt/about_backtest/art/p1–p6.png` | 產出的示意圖（1019×650～980 px、透明底；200 px = 1 吋 → 以原吋嵌入，不縮放）|
| `plans/ppt/about_backtest/about_backtest-解說腳本.md` | 旁白講稿（6 段；**為控制在 3 分鐘內精簡過一輪**，實測配音 **169.8 秒／2 分 50 秒**）|
| `plans/ppt/about_backtest/about_backtest-講稿版.pptx` | 備註＝講稿（流水線產物，2,963 KB；畫面來源用這份，因為沒有喇叭圖示）|
| `plans/ppt/about_backtest/about_backtest-配音版.pptx` | 每頁備註區嵌音訊（6 頁驗證通過、5,450 KB）|
| `plans/ppt/about_backtest/about_backtest-配音版.mp4` | **成品**：1080×1920、30 fps、H.264＋AAC **44.1 kHz 立體聲**、**167.6 秒（2 分 48 秒）**、6.6 MB |
| `plans/ppt/about_backtest/_narration_about_backtest/` | 豆包 TTS 產物（`audio/`＋`audio_44k/`＋`timeline.json`＋`voiceover.mp3`）|
| `TMP/abt_build/about_backtest.pptx.bak` | 原檔備份（第一次執行時自動複製，只備份一次）|

### 六頁內容與圖

| 頁 | 標題 | 圖 | 數字來源 |
|---|---|---|---|
| 1 | 回測怎麼看（封面） | 回測曲線（平滑）vs 實盤曲線（鋸齒、位置較低）＋末端「落差」箭頭；下方 2×2 導覽磁磚 **1／2／3／4**（第 2 項「前向驗證」佔 P3、P4 兩頁，圖底註「對應頁次：P2／P3-P4／P5／P6」） | — |
| 2 | 倖存者偏差 | 左「今天的股市 610 檔還活著」vs 右「回測的宇宙裡沒有 62 檔（每根 K 棒打紅 ✕）」；紅框列出 2016-01 市值前 5 名（6452 康友-KY／2325 矽品／1704 榮化／3474 華亞科／2311 日月光）；底部兩張對照卡 | `cairn/backtest-data-pitfalls.md` §七 |
| 3 | 前向驗證 Forward test | 6 輪時間軸：藍＝擴張式訓練段（2016→前一年）、橘＝OOS 那一年、右欄列出各年 OOS 報酬、紅線標「不能往右看」 | `results/walk_forward/wf_presets_2020_2025.md` |
| 4 | 我們的前向驗證結果 | 上：六年分年柱狀（橘＝策略／藍＝0050；勝負「4 勝 2 負」寫在投影片文字，圖上不放徽章以免字太小）；下：同段期間只換一個參數的鄰居表（最佳 +1323.6% ⇒ 換一個參數掉 382～959pp） | 同上（含彙總段與鄰居表）|
| 5 | 滑價：回測沒有這一段 | 左：一根 K 棒，① 收盤價＝回測成交、② 較高的實盤成交（未知），箭頭標價差；右：手續費 0.1425% ✓／證交稅 0.3% ✓／滑價 0 ✕ ＋ 紅框算式「24 倍/年 × 0.15% ≈ 每年 3.6%」 | `scripts/backtest_plan2_monthly_3group.py` 的 `COMMISSION`／`tax_rate`（**沒有**滑價項）|
| 6 | 買不到：實盤會、回測不會 | 左紅欄 6 個 ✕（漲跌停鎖死／停牌／量太小／零股整張／限價單掛不到／T+2）；右綠欄 7 個 ✓（手續費＋稅、年線濾網、下市宇宙 672、PER／營收資格、暖機空池、股災防護＋硬停損）；底「仍未計：滑價、平倉成本」 | 見 `core/backtest_rules.py`、`core/scoring.py`、`cairn/backtest-data-pitfalls.md` |

- **口徑**：全部引用 2026-11-05 的快照（宇宙 672＝610＋62、月營收 645/672、PER 672/672、`aggressive`＝池150＋營收＋上限2）。
  改回測口徑或補資料後，**圖與文字要一起改**（數字寫死在 `PAGES`／`FIGURES` 兩處，同一支腳本裡）。
- **重出**：

```bash
cd ~/tw-selfselect
# ① 畫面＋文案（改了字級／圖／文字才需要）
.venv/bin/python plans/ppt/about_backtest/make_about_backtest.py         # 畫圖＋改文案＋嵌圖
.venv/bin/python plans/ppt/about_backtest/make_about_backtest.py draw    # 只畫圖（→ art/，會回報文字超出方框）
.venv/bin/python plans/ppt/about_backtest/make_about_backtest.py embed   # 只改文案＋嵌圖

# ② 配音（改旁白才需要，會呼叫 TTS；只改版面用 revoice）
bash plans/generate_narration.sh build \
  "plans/ppt/about_backtest/about_backtest.pptx" "plans/ppt/about_backtest/about_backtest-解說腳本.md"

# ③ 出片（⚠️ 第 1 個參數給「講稿版」；音源要餵 audio_44k，見下方註）
mkdir -p TMP/abt_build/narr44 && cp plans/ppt/about_backtest/_narration_about_backtest/timeline.json TMP/abt_build/narr44/ \
  && ln -sfn "$PWD/plans/ppt/about_backtest/_narration_about_backtest/audio_44k" TMP/abt_build/narr44/audio
HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
  "plans/ppt/about_backtest/about_backtest-講稿版.pptx" "TMP/abt_build/narr44" \
  "plans/ppt/about_backtest/about_backtest-配音版.mp4"
```

- **⚠️ 音源一定要餵 `audio_44k`，而且 `timeline.json` 不能是舊的副本**：`build` 產的 `audio/` 是 TTS 原檔
  （24 kHz 單聲道），直接餵會得到 24 kHz 單聲道、音量差約 3 dB（2026-11-05 實際踩到並重出）；
  另外 `narr44/timeline.json` 若用 `cp` 複製，**重配音後它還是舊的** ⇒ 每頁停留秒數會與新配音錯位
  （同一天踩到：畫面上寫 195.2s、實際 192.4s）。⇒ 兩個都用 `ln -s` 指到 `_narration_about_backtest/` 的本尊。
- **長度控制（2026-11-05 使用者「請控制在 3 分鐘內」）**：這份 6 頁原始配音 192.4 秒（3 分 12 秒），
  精簡後 **169.8 秒（2 分 50 秒）**。做法是**刪掉圖上已經有的數字與重複的鋪陳**，不是加快語速：
  P2 砍「回測裡看不到它們」與池 20 的兩個數字（圖上有）、P4/P5 合併句子、P6 右欄清單縮短。
  量測口徑：實際語速 3.1–4.2 字/秒（含數字的句子最慢）⇒ **1 秒 ≈ 3.5 字**，要砍 10 秒就是砍 35–40 字。
- **改旁白只有兩種情況**：改 `.md` ⇒ `build` 重配音（秒數會變、要重出 MP4）；只改版面／備註格式 ⇒
  `revoice`（沿用既有音檔、不呼叫 TTS）。若使用者直接在 `-講稿版.pptx` 的備註改稿，
  **先把他的文字抄回 `.md`**（`.md` 才是 TTS 的輸入），再 `build`，否則下一次重配音會蓋掉他的版本。

- **圖內字級（2026-11-05 第二輪，使用者「圖型內的字還是太小加大些」）**：整體放大一級——
  刻度／註腳 **14 pt**、說明與清單 **14.5–16 pt**、面板標題 **19 pt**、主數字 **18–21 pt**（原 10.5–19）。
  同時把方框、行距與**畫布高度**一起放大（P1 4.90→5.25、P2 3.70→4.70、P3 3.62→4.20、P4 4.40→4.90、
  P5 3.25→3.85、P6 4.60→5.01 吋），投影片上的圖高跟著改（`PAGES[*]["art"]`），文字起點自動下移。
  放大後塞不下的句子一律**改寫更短**（例如 P2 改成「修正前 → 修正後」兩行、P4 拿掉「4 勝 2 負」徽章
  改由投影片文字承擔），不是縮字級。
- **驗證**：`soffice → PDF → pypdfium2 轉 PNG` 逐頁目視（`TMP/abt_build/pdf/p*.png`）。
  兩輪共修掉六個缺陷（見 `cairn/teaching-material-pipeline.md` §教訓 6–11）：文字框換行造成疊字、
  `mono` 字型沒有中文（變豆腐）、清 shape 用 `is` 比對把背景一起刪掉（整頁白底）、圖內文字超出右緣、
  `✕` 沒有字面（要用 `×`）、畫布底邊把最後一行切掉。

## W7（2026-10-30 新增，講稿版）

主題是 **v1.1.x 之後的選股方式**：新加的 `zscore`（現行預設）與 AI 選股，以及回測結果、參數、實作流程與改進方向。

- 產生器：`plans/ppt/make_w7.py`（沿用 W6 的母版與版型，刪光範例頁後用 python-pptx 重畫 18 頁＋講稿備註）。
  重新產生：`.venv/bin/python plans/ppt/make_w7.py`
- 講解腳本：`TW-SELFSELECT台股買賣自動化系統-W7-解說腳本.md`（由 `notes_to_script.py` 從備註反推，19 頁／約 43 分 30 秒）。
- 2026-10-30 追加：S14 定義 D1／D2；S7 加「產業上限」同一天名單對照實例；S16「產業上限已接進實盤、待定預設值」措辭更正；
  新增 S19「選股很重要，但代價是風險」——v1.0 legacy（+207.9%／MDD −36.0%／夏普 0.69）vs v1.1 預設（+1323.6%／−40.2%／1.15），
  提醒「風險與獲利的取捨由使用者決定」。
- **2026-10-31 全篇改版**：預設選股口徑由 `revenue` 改為 `aggressive`（使用者裁定），S3／S6／S7／S8／S9／S10／S11／S16／S18／S19 的
  數字與措辭同步（+762.4%／−53.7% → +1323.6%／−40.2%／夏普 1.15），並補上「2022-2026 輸或打平 0050」的警語；講稿與配音全部重出。
- 內容與數字口徑：2016-2025、正常組、含成本、`PROFILE=default`（停泊 0050＋大盤年線），資料快照
  宇宙 672 檔、PER 672/672、月營收 645/672；三個 preset（current +411.1%／revenue +762.4%／aggressive +1323.6%）與 0050（+477.6%）。
- 配音版／MP4（2026-10-30 產出、2026-10-31 因預設改 aggressive 重製）：`…-W7-配音版.pptx`（每頁右下角喇叭）
  ＋ `…-W7-配音版.mp4`（1920×1080、**1,177 秒／19 分 37 秒**；TTS 配音總長 19.7 分鐘）。兩者依 `.gitignore` 不進版控。
  重建：`bash plans/generate_narration.sh build <講稿版.pptx> <解說腳本.md>` → `HOME=$PWD/TMP/lohome bash plans/ppt_to_mp4.sh <配音版.pptx> plans/ppt/_narration_…`

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
| W7 | 19 | 19 分 42 秒 | 1,177 s |

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
| `plans/generate_narration.sh` | 主流水線：`extract` 抽逐頁文字 → `build` 講稿＋配音＋產生講稿版／配音版 → `revoice` 沿用既有音檔只重做備註／嵌入（不呼叫 TTS） |
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

# 3b. 只改版面／標題、旁白沒動 → 沿用既有音檔重做講稿版＋配音版（不呼叫 TTS，約 2 秒）
./generate_narration.sh revoice "ppt/git_contain/git_contain.pptx" "ppt/git_contain/git_contain-解說腳本.md"

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
