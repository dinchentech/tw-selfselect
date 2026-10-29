---
type: project_topic
status: active
summary: "W1–W6 教學投影片的產製管線（講稿版／配音版／MP4／解說腳本）與五個反覆踩到的坑：使用者存檔覆蓋修改、tab 排版錯位、sz 單位、螢光筆是 run 屬性、一份簡報混兩套口徑"
tags: [教材, PPT, 影片, 配音, LibreOffice]
contains: [procedure, lesson, experience, open_question]
created: "2026-10-29"
updated: "2026-10-29"
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
HOME=$PWD/TMP/lohome bash plans/ppt_to_mp4.sh \
  plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-配音版.pptx \
  plans/ppt/_narration_TW-SELFSELECT_________-W6-___

# 3) 改完備註要重生成解說腳本
.venv/bin/python plans/ppt/notes_to_script.py --force
```

- 動 PPTX 前先備份到 `TMP/`（例：`TMP/W5_講稿版_before_tabfix_all.pptx`），出事才有對照。
- 判斷「配音版有沒有同步」的客觀方法：逐頁比對嵌入音訊 md5（與 `_narration_*` 目錄的 `audio_44k` 比），
  並確認 pptx 內有 `<Default Extension="mp3">`。數字對不上就是同步失敗。

## 教訓（反覆踩到的五個坑）

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

## 開放問題

1. 其餘 tab 排版的頁面要不要一併換真表格：W2-24、W3-15／17、W4-9、W5-10／13／20／22／23、W6-7。
2. W1 S13 的螢光筆在講稿版是「群組內文字」、配音版是 SmartArt ⇒ 無法用 run 複製同步；
   目前是「用講稿版當畫面來源、沿用既有旁白」出片，PowerPoint 內看仍與 MP4 略有差異。要完全一致就得重配音。
3. 教材數字每次改回測口徑都會過期；要不要加一個「數字來源檢查」步驟（把投影片上的數字對回 `results/`）。
