---
type: project_topic
status: active
summary: "W1–W6 教學投影片的產製管線（講稿版／配音版／MP4／解說腳本）與反覆踩到的坑：使用者存檔覆蓋修改、tab 排版錯位、sz 單位、螢光筆是 run 屬性、一份簡報混兩套口徑；2026-11-05 補 python-pptx 整頁重建的 5 個新坑（背景被刪、mono 無中文、文字框折行疊字、圖文字超右緣、白底預覽誤判、缺字面、字級與畫布要一起放大、畫布底邊切字）"
tags: [教材, PPT, 影片, 配音, LibreOffice]
contains: [procedure, lesson, experience, open_question]
created: "2026-10-29"
updated: "2026-11-06"
related: [backtest-data-pitfalls.md]
authoring_mode: ai_generated
---
# 教材產製（W1–W6 投影片 → 配音 → MP4）

## 背景

`plans/ppt/` 有六份教材（W1–W6），從母專案 tw-autotrader 複製改寫成 tw-selfselect 的內容；
2026-10-26～28 之間反覆「改數字／改版面 → 重配音 → 重出 MP4」，三天內 23 則 LOG 條目。
工程細節（頁數、時長、相對母檔的變更清單）以 `plans/ppt/README.md` 為權威；本檔只留**判斷與陷阱**。

## 當前結論（產製模型）

每份教材有三個版本，方向是單向的：**講稿版 →（配音）→ 配音版 →（轉檔）→ MP4**。

| 檔案 | 角色 | 誰會改 |
|---|---|---|
| `…-W*-講稿版.pptx` | 文字與版面的**唯一真相**（含逐頁備註＝講稿） | 人（PowerPoint）＋助理（python-pptx） |
| `…-W*-解說腳本.md` | 由備註產生的逐頁講稿文件 | 由 `notes_to_script.py` 重生成，不手改 |
| `…-W*-配音版.pptx` | 每頁嵌入音訊的放映版 | **只由建置流程產生**，助理只做同步性修改 |
| `…-W*-配音版.mp4` | 成品影片 | 由 `ppt_to_mp4.sh` 產生 |

- 改文字／改數字 ⇒ 一定回到講稿版改，再 `generate_narration.sh build` 重配音（旁白長度會變）。
- 只改畫面（字型、版面、螢光筆、換圖）⇒ 講稿版改完，把差異同步進配音版、只重轉 MP4（不重跑 TTS）。
- 抽幀／版面驗證一律 `soffice → PDF → PNG` 目視，不看 PowerPoint 畫面。

## 實踐指南

```bash
# 1) 重配音（講稿版＋解說腳本 → 配音版，旁白寫回備註區音訊）
bash plans/generate_narration.sh build \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-解說腳本.md

# 2) 轉 MP4（無 root／沙箱下 LibreOffice 會寫 $HOME/.config，故改 HOME）
#    ⚠️ `build` 產的 audio/ 是 TTS 原檔（24 kHz 單聲道）；其他教材的 MP4 都是 44.1 kHz 立體聲
#    ⇒ 出片要餵 audio_44k：做一個只含 timeline.json ＋ audio→audio_44k 連結的目錄再傳給腳本
#       （2026-11-05 about_backtest 實測：餵 audio/ 會得到 24 kHz 單聲道，音量也差 3 dB）
HOME=$PWD/TMP/lohome bash plans/ppt_to_mp4.sh \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-配音版.pptx \
  plans/ppt/_narration_TW-SELFSELECT_________-W6-___

# 3) 改完備註要重生成解說腳本
.venv/bin/python plans/ppt/notes_to_script.py --force
```

- 動 PPTX 前先備份到 `TMP/`（例：`TMP/W5_講稿版_before_tabfix_all.pptx`），出事才有對照。
- 判斷「配音版有沒有同步」的客觀方法：逐頁比對嵌入音訊 md5（與 `_narration_*` 目錄的 `audio_44k` 比），
  並確認 pptx 內有 `<Default Extension="mp3">`。數字對不上就是同步失敗。

## 教訓（反覆踩到的坑：1–5 是前五輪，6–13 是 2026-11-05 整頁重建與字級放大）

1. **使用者在 PowerPoint 開著舊版存檔，會整頁覆蓋助理的修改**（已發生兩次：W4 S25 標題與表格、W6 S9 整頁被還原成舊版）。
   ⇒ **每次重出前先比對「講稿版 vs 配音版」的文字差異**；發現被回退就先重建該頁再產片，不要直接跑產片流程。
   影片出完仍要抽幀檢查，不要因為「流程跑完」就當成功。
2. **tab 對齊的頁面在 LibreOffice 會左右錯位**：PowerPoint 與 LibreOffice 對 tab 落點與字寬的算法不同，
   `defTabSz` 設了也沒用（PowerPoint 內看是齊的，轉成 PNG 的影片錯位）。⇒ 一律改用**真表格**；
   已處理 W5 S12／S10／S13／S20／S22／S23 共 6 頁，其餘仍是 tab 排版的頁面見 §開放問題。
3. **自建 `a:r` 時 `a:rPr/@sz` 單位是 1/100 pt**（11pt ⇒ `sz="1100"`）。誤用 EMU（139700）⇒ LibreOffice 把表格列撐爆、
   出現黑色方塊。
4. **螢光筆不是文字屬性，而是 run 屬性 `<a:highlight>`**（OMML）。python-pptx 的 `.text` 完全看不到它；
   而且 **PowerPoint 存檔會重切 run** ⇒ 不能用 run 索引對應。同步手法：逐段落比對，該段在講稿版有任何高亮 run
   就把整段 run 由講稿版 `deepcopy` 重建到配音版（含表格儲存格）。
   同步配音版時要用 spTree 節點搬移保留每頁音訊 `pic`，否則旁白消失。
5. **一份簡報不能混兩套口徑**：W5 的 12–13 頁曾用「買訊隔日漲跌加總」（模式一），18–20 頁用「真實部位」（模式二），
   同一份簡報兩套算法，數字不可比。⇒ 改數字時先確認**這份簡報全篇是哪個口徑**，跨頁不一致就整批重跑
   （口徑本身見 `backtest-data-pitfalls.md`；母專案數字不可直接引用）。

### 2026-11-05 新增（`about_backtest` 首次用 python-pptx **整頁重建**時踩到）

6. **`slide.shapes` 每次存取都回新的 proxy 物件** ⇒「保留背景圖、刪掉其他 shape」寫成 `if sh is not bg` 會**把背景也刪掉**
   （整頁變白底，而文字是 `F2F6FB` 淺色 ⇒ 投影出來幾乎隱形，PDF 一看才發現）。要比對 `sh._element is bg._element`，
   或直接記住 `bg._element` 再比。
7. **`mono` 字型只給純 ASCII**：DejaVuSansMono 沒有 CJK 字面、也沒有 `②③` 這類圈號 ⇒ 中文與圈號全變豆腐
   （本輪：股票名「6452 康友-KY」、封面導覽的 ②③⑤⑥）。圈號改用**向量畫的圓＋阿拉伯數字**（`numdot()`）。
   `txt(mono=True)` 現在遇到非 ASCII 會直接印警告。
8. **文字框預設左右內縮各 0.1 吋，一行塞不下就被 LibreOffice 折成兩行** ⇒ 下一行沒跟著下移就**疊字**
   （本輪 P3 第一行壓在第二行上）。修法：`margin_left/right` 歸零、框加寬到 5.28 吋，並在寫入前用
   Pillow 載入 **同一支 Noto** 量寬度（本檔的 `_check_width`，門檻 5.24 吋）——LibreOffice 對 CJK 的字寬與它一致。
9. **圖內文字要留右緣**：標籤放在右側時 `x + 文字寬` 超過畫布就會被 PNG 直接切掉（本輪 p3 的 OOS 欄、p4 的 `+1323.6%`、
   p6 的「下市宇宙 672 檔（610＋62）」）。⇒ 一律傳 `fit=`（可用寬度）給 `txt()`，`draw` 會把超出的一行列出來。
10. **透明底 PNG 不要疊白底預覽**：淺色文字（`F2F6FB`）在白色上看起來像壞掉，實際是底色不同；
    要疊在**投影片同色**（約 `(13, 27, 48)`）或直接看 `soffice → PDF → PNG` 的成品，才不會誤修。
11. **缺字面也會變豆腐，而且不是 mono 的問題**：`✕`（U+2715）、`✗`（U+2717）、`✔`（U+2714）
    在 Noto Sans CJK **沒有字面**，`✓`（U+2713）與 `×`（U+00D7）有 ⇒ 打勾用 `✓`、打叉用 `×`，
    或用向量畫（本檔的 `mark_x()`／`mark_v()`）。`make_about_backtest.py` 現在會用 fontTools 的 cmap
    逐字檢查並在 `draw` 時警告。
12. **字級下限 14 pt，放大要連畫布一起長**（2026-11-05 使用者第二次反應「圖內的字還是太小」）：
    只放大字不放大框＝一定溢位；正確做法是字級、方框、行距、**畫布高度**、投影片上的圖高（`art` 吋數）
    一起改，塞不下就把句子**改短**或拆行，最後逐頁目視。圖文一律 `fit=` 標可用寬度，讓警告自己跳出來。
13. **畫布底邊要留一次字高**：最後一行 `y + 字高` 超過畫布高度就會被切掉（本輪 p2 卡片內文、p5 註解、
    p1 頁腳都差幾 px）——看縮圖看不出來，用 `y_max + 0.30 吋 < 畫布高` 檢查。


## 已知口徑落差：ATR（2026-11-06 已決——**不改**，等下次重出才一起改）

程式在 v1.1.33 把 ATR 口徑統一成「TR 含跳空（`prev_close`）＋ **Wilder 平滑**」（＝TA-Lib `TA_ATR`／
TradingView `ta.atr(14)`），`策略說明.md` §5.3／§5.4／附錄 E 已同步更正；但**教材仍停在舊口徑**。

使用者的決定（2026-11-06）：「重出那批 pptx／mp4 ⇒ 不改了」——即**接受這個落差、不為此重出成品**。
理由：重出要跑 `generate_narration.sh` ＋ `ppt_to_mp4.sh`（配音、抽格驗證），成本遠高於落差本身的影響
（教材講的是「有 ATR 過濾」這個概念，兩種口徑差在跳空與平滑，不影響教學主軸）。

**受影響清單（下次重出該批教材時照這張改，才不會又漏）**：

| # | 檔案 | 內容 |
|---|---|---|
| 1 | `plans/ppt/make_stock_index_2.py` | 附錄 E 文字：`ATR = TR 的 N 日移動平均`、以及「breakout 的 TR 不含跳空」的口徑提醒 |
| 2 | `plans/ppt/stock_index_2/stock_index_2-解說腳本.md` | §58 講師提示：同上 |
| 3 | `plans/ppt/README.md`（約 §320–325） | 「ATR 的兩種 TR 口徑（breakout 不含跳空）」 |
| 4 | `docs/breakout-animation.html` | `calcATR()` 已是**標準 TR**（含前收）但用 **SMA** ⇒ 只差平滑方式 |
| 5 | `plans/ppt/strategy_mp4/breakout-講稿.md`、`docs/breakout-animation.html` 的畫面上「ATR 1.05%」等數字 | 若平滑改成 Wilder，畫面數字會微幅變動 ⇒ 需重新挑種子 |

**不變的部分**：`策略說明.md`／`cairn/` 一律以程式碼為準（已更正），所以「文件比教材新」是預期狀態。

## 開放問題

1. 其餘 tab 排版的頁面要不要一併換真表格：W2-24、W3-15／17、W4-9、W5-10／13／20／22／23、W6-7。
2. W1 S13 的螢光筆在講稿版是「群組內文字」、配音版是 SmartArt ⇒ 無法用 run 複製同步；
   目前是「用講稿版當畫面來源、沿用既有旁白」出片，PowerPoint 內看仍與 MP4 略有差異。要完全一致就得重配音。
3. 教材數字每次改回測口徑都會過期；要不要加一個「數字來源檢查」步驟（把投影片上的數字對回 `results/`）。
