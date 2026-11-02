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
