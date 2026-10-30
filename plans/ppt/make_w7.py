#!/usr/bin/env python3
"""make_w7.py · 產生 `TW-SELFSELECT台股買賣自動化系統-W7-講稿版.pptx`

主題：**v1.1 之後的 zscore（預設）＋ AI 選股**
1. 新增加的 zscore（預設）＋ AI 選股方式與回測結果
2. zscore 有哪些重要參數
3. 如何用 AI 選股
4. 可能的改進方式

做法：沿用 W6 講稿版的同一份簡報母版（版型、字型、頁碼都由模板提供），
      先刪光範例頁，再用 python-pptx 產生新頁＋講稿備註（`⏱ 建議時間`／`【講師提示】`）。

用法：
    .venv/bin/python plans/ppt/make_w7.py            # 產生（覆寫）
    OUT=…/W7.pptx .venv/bin/python plans/ppt/make_w7.py
"""
from __future__ import annotations

import os
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = ROOT / "plans/ppt/TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx"
OUT = Path(os.environ.get("OUT", ROOT / "plans/ppt/TW-SELFSELECT台股買賣自動化系統-W7-講稿版.pptx"))

INK = RGBColor(0x1F, 0x24, 0x2B)          # 主文字
ACCENT = RGBColor(0xC0, 0x39, 0x2B)       # 強調（紅）
OK = RGBColor(0x1E, 0x7B, 0x45)           # 正向（綠）
MUTED = RGBColor(0x5B, 0x63, 0x6D)        # 次文字
HDR_FILL = RGBColor(0x22, 0x2A, 0x35)     # 表頭底色
ZEBRA = RGBColor(0xF3, 0xF5, 0xF7)        # 斑馬紋

TITLE_BOX = (Inches(0.75), Inches(0.42), Inches(11.85), Inches(0.72))   # 內頁標題
BODY_TOP = Inches(1.32)


def _clear_slides(prs):
    xml_slides = prs.slides._sldIdLst
    for sld in list(xml_slides):
        rId = sld.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        prs.part.drop_rel(rId)
        xml_slides.remove(sld)


def _layout(prs, name):
    for l in prs.slide_layouts:
        if l.name.strip().lower() == name.strip().lower():
            return l
    raise KeyError(name)


def _notes(slide, minutes, body, tip=""):
    tf = slide.notes_slide.notes_text_frame
    tf.clear()
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = f"⏱ 建議時間：{minutes}"
    r.font.size = Pt(12)
    r.font.bold = True
    for line in body.strip().split("\n\n"):
        para = tf.add_paragraph()
        run = para.add_run()
        run.text = line.strip()
        run.font.size = Pt(12)
    if tip:
        para = tf.add_paragraph()
        run = para.add_run()
        run.text = f"【講師提示】{tip.strip()}"
        run.font.size = Pt(12)
        run.font.bold = True


def _title_slide(prs, kicker, title, subtitle, minutes, notes, tip):
    s = prs.slides.add_slide(_layout(prs, "Title Only"))
    for ph in list(s.placeholders)[1:]:          # 只留標題
        ph._element.getparent().remove(ph._element)
    t = s.shapes.title
    t.left, t.top, t.width, t.height = (Inches(0.9), Inches(1.5), Inches(11.5), Inches(3.6))
    t.text = ""
    p = t.text_frame.paragraphs[0]
    r = p.add_run(); r.text = kicker
    r.font.size = Pt(24); r.font.bold = True; r.font.color.rgb = ACCENT
    p2 = t.text_frame.add_paragraph()
    r2 = p2.add_run(); r2.text = title
    r2.font.size = Pt(40); r2.font.bold = True; r2.font.color.rgb = INK
    box = s.shapes.add_textbox(Inches(0.9), Inches(5.45), Inches(11.5), Inches(1.1))
    tf = box.text_frame; tf.word_wrap = True
    run = tf.paragraphs[0].add_run(); run.text = subtitle
    run.font.size = Pt(18); run.font.color.rgb = MUTED
    _notes(s, minutes, notes, tip)
    return s


def _content_slide(prs, title, minutes, notes, tip="", page=None):
    s = prs.slides.add_slide(_layout(prs, "Title Only"))
    for ph in list(s.placeholders)[1:]:          # 只留標題，其餘自己畫
        ph._element.getparent().remove(ph._element)
    t = s.shapes.title
    t.left, t.top, t.width, t.height = TITLE_BOX
    t.text = title
    for para in t.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(26); run.font.bold = True; run.font.color.rgb = INK
    # 頁碼（左下，與 W1–W6 一致的位置感）
    n = page if page is not None else len(prs.slides)
    num = s.shapes.add_textbox(Inches(0.32), Inches(0.5), Inches(0.7), Inches(0.4))
    r = num.text_frame.paragraphs[0].add_run(); r.text = str(n)
    r.font.size = Pt(12); r.font.color.rgb = MUTED
    _notes(s, minutes, notes, tip)
    return s


def _bullets(slide, items, left, top, width, height, size=17, gap=6):
    """items: [(text, level, emphasis)] → 一個無邊框文字框。"""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for text, level, emphasis in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_after = Pt(gap)
        run = p.add_run()
        bare = text[:1] in "0123456789📌→"          # 已經有編號或圖示就不再疊項目符號
        run.text = ("" if bare else ("• " if level == 0 else "– ")) + text
        run.font.size = Pt(size if level == 0 else size - 2)
        run.font.bold = emphasis
        run.font.color.rgb = ACCENT if emphasis else INK
    return box


def _table(slide, rows, left, top, width, height, col_w=None, size=13, hdr_size=13):
    nrow, ncol = len(rows), len(rows[0])
    shape = slide.shapes.add_table(nrow, ncol, left, top, width, height)
    tbl = shape.table
    if col_w:
        total = sum(col_w)
        for i, w in enumerate(col_w):
            tbl.columns[i].width = Emu(int(width * w / total))
    for r, row in enumerate(rows):
        tbl.rows[r].height = Inches(0.36 if r == 0 else 0.34)
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = ""
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            run = p.add_run()
            run.text = str(val)
            run.font.size = Pt(hdr_size if r == 0 else size)
            run.font.bold = (r == 0)
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if r == 0 else INK
            if r == 0:
                cell.fill.solid(); cell.fill.fore_color.rgb = HDR_FILL
            elif r % 2 == 0:
                cell.fill.solid(); cell.fill.fore_color.rgb = ZEBRA
    return shape


def _callout(slide, text, left, top, width, height, fill=RGBColor(0xFF, 0xF4, 0xE5), size=15):
    box = slide.shapes.add_textbox(left, top, width, height)
    box.fill.solid(); box.fill.fore_color.rgb = fill
    box.line.color.rgb = RGBColor(0xF0, 0xB4, 0x8A)
    tf = box.text_frame
    tf.word_wrap = True
    para = tf.paragraphs[0]
    run = para.add_run(); run.text = text
    run.font.size = Pt(size); run.font.color.rgb = INK
    return box


def build():
    prs = Presentation(str(TEMPLATE))
    _clear_slides(prs)

    # ── S1 封面 ───────────────────────────────────────────────
    _title_slide(
        prs, "TW-SELFSELECT-W7",
        "選股進化：zscore（預設）＋ AI 選股",
        "v1.1.x｜回測結果 · 重要參數 · AI 選股實作 · 可能的改進",
        "30 秒",
        "歡迎回來第七堂課。前面六週我們把策略、回測、選股、部署都跑完了；這一週要補的是"
        "上線後才長出來的兩個東西：一個新的評分方式 zscore（現在是預設），以及可以選用的 AI 選股模式。\n\n"
        "這一集不講理念，只講三件事：它怎麼算、參數在哪、怎麼用，以及我們測出來的結果跟代價。",
        "這一集數字都是 2016-2025、正常組、含成本回測；結尾一定要留時間講「誠實看數據」那兩頁。",
    )

    # ── S2 這一集要回答的四個問題 ───────────────────────────────
    s = _content_slide(prs, "這一集要回答的四個問題", "1 分鐘",
                       "先給大家一張地圖，四頁之後你就知道整集的骨架。\n\n"
                       "第一，新加的 zscore 和 AI 選股是什麼、回測結果如何。第二，zscore 有哪些重要參數可以調。"
                       "第三，AI 選股實際上怎麼操作。第四，還有哪些明顯的改進空間——這一段我會直接說我們還不夠好的地方。\n\n"
                       "最後那句總結請大家記住：換了評分、多了 AI 選項，但兩者都還沒站穩。從 2026-10-30 起我們才開始真正的實測，"
                       "之後會持續改進；所有最新數字、參數與更新都在 Git 專案上，講義拿到的是當天版本。",
                       "課程結束後把 Git 專案網址留給學員；提醒他們數字會更新，回測結論以 repo 內文件為準。")
    _bullets(s, [
        ("1. zscore（預設）＋ AI 選股 是什麼？回測結果如何？", 0, False),
        ("2. zscore 有哪些重要參數？哪些該調、哪些不要碰？", 0, False),
        ("3. AI 選股怎麼用？D1 手動、逾期自動 fallback 的流程", 0, False),
        ("4. 可能的改進方式：哪幾個缺口最該先補", 0, False),
        ("一句話總結：預設從 legacy 換成 zscore，並多了「AI 當選股員」這個選項；但兩者都還沒站穩", 0, True),
        ("自 2026-10-30 起開始實測、持續改進；最新更新請上 Git 專案：github.com/dinchentech/tw-selfselect", 0, False),
    ], Inches(0.9), BODY_TOP + Inches(0.1), Inches(11.5), Inches(4.1), size=18, gap=9)

    # ── S3 為什麼要改（1.0 → 1.1）──────────────────────────────
    s = _content_slide(prs, "為什麼要改？v1.0 的三個問題", "2 分鐘",
                       "v1.0 用的評分叫 legacy，是「動能＋技術面＋穩定度＋催化劑」的綜合分。實測有兩個問題："
                       "第一，它跟大盤比是明顯落後的（+61.4% vs 0050 的 +477.6%）。第二，它的分數不可解釋——"
                       "你看不出為什麼 A 比 B 高分。\n\n"
                       "第三個問題跟選股無關，是資料：宇宙裡沒有已下市個股、PER 快取只蓋四成、月營收只蓋一半。"
                       "資料不修，換什麼評分都是在假的資料上調參數。所以 v1.1 是「先修資料，再換評分」。",
                       "這一頁是動機頁，不要花超過兩分鐘；重點是讓學員接受「先修資料」的順序。")
    _table(s, [
        ["問題", "v1.0 的狀況", "v1.1 的做法"],
        ["評分不可解釋", "legacy 綜合分：看不出為什麼這檔分數高", "zscore：四個因子加權，每一項都能講清楚"],
        ["報酬落後大盤", "legacy·停泊 0050 ＝ +207.9%（0050 +477.6%）", "zscore·停泊 0050 ＝ +762.4%（含營收因子）"],
        ["資料有偏誤", "宇宙不含已下市股；PER 267/672、月營收 522/672", "補 62 檔下市股、PER 672/672、月營收 645/672"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.4), col_w=[1.4, 4.6, 4.6], size=14)
    _callout(s, "順序很重要：先修資料（宇宙／PER／營收），再比評分方式。資料沒補齊時，同一組參數換個時間跑，結果就會變。",
             Inches(0.75), Inches(5.35), Inches(11.85), Inches(0.95))

    # ── S4 zscore 是什麼 ─────────────────────────────────────
    s = _content_slide(prs, "zscore 是什麼：四個因子、一句話講完", "2 分 30 秒",
                       "zscore 的做法很樸素：同一批候選股裡，把每個因子換算成「相對強弱」（z 分數），再加權排序。\n\n"
                       "四個因子：63 日動能（權重 0.40）、20 日動能（0.25）、距離 52 週高還有多遠（0.20）、本益比（0.15，"
                       "而且是扣分——越貴越低分）。開營收因子時，把 63 日動能降到 0.25，多一個月營收年增率 0.15。\n\n"
                       "白話：它同時看「最近有沒有在漲」「有沒有接近一年高點」「貴不貴」，最後一個是「基本面有沒有變好」。",
                       "公式一定要配白話講；學員最容易卡在「z 分數是什麼」，用「同一班同學的排名」比喻最快。")
    _table(s, [
        ["因子", "意思", "預設權重", "開營收後"],
        ["z(63 日報酬)", "最近三個月的動能", "0.40", "0.25"],
        ["z(20 日報酬)", "最近一個月的動能", "0.25", "0.25"],
        ["z(距 52 週高)", "離一年高點多遠（越近越高分）", "0.20", "0.20"],
        ["z(負 PER)", "本益比越低越高分", "0.15", "0.15"],
        ["z(月營收 YoY)", "營收年增率（基本面成長）", "—", "0.15"],
    ], Inches(0.75), BODY_TOP, Inches(7.1), Inches(3.6), col_w=[2.0, 3.2, 1.3, 1.4], size=14)
    _bullets(s, [
        ("公式（預設）：0.40·z63 ＋ 0.25·z20 ＋ 0.20·z距高 ＋ 0.15·z(−PER)", 0, False),
        ("開營收因子：0.25·z63 ＋ 0.25·z20 ＋ 0.20·z距高 ＋ 0.15·z(−PER) ＋ 0.15·z(營收YoY)", 0, False),
        ("程式位置：core/scoring.py（回測與實盤共用同一份）", 0, False),
    ], Inches(8.1), BODY_TOP + Inches(0.1), Inches(4.5), Inches(3.2), size=15)
    _callout(s, "重點：四個因子都能用一句話解釋，這就是 zscore 相對 legacy 最大的價值——可解釋、可稽核、可重跑。",
             Inches(0.75), Inches(5.35), Inches(11.85), Inches(0.9), fill=RGBColor(0xE8, 0xF5, 0xEC))

    # ── S5 資格門檻：0 < PER ≤ 40 ────────────────────────────
    s = _content_slide(prs, "先過門檻才評分：0 < PER ≤ 40", "2 分鐘",
                       "zscore 有一個很多人會忽略的前置條件：本益比必須大於 0 且不超過 40，沒有 PER 的股票直接不列入。\n\n"
                       "這條規則本身合理——虧錢的公司 PER 是負的、太貴的不想追。但它有一個副作用："
                       "如果 PER 資料本身不完整，等於「先偷偷刪掉一批候選股」。我們就是這樣踩到的："
                       "PER 快取當時只有 267 檔，宇宙有 672 檔，等於六成候選股在評分前就不見了。\n\n"
                       "所以 v1.1 把 PER 補到 672 檔。這件事對回測結果的影響，比任何參數調整都大。",
                       "這頁是「資料正確性」的核心案例，建議花時間講清楚：門檻本身沒錯，錯的是資料覆蓋率。")
    _table(s, [
        ["情境", "會發生什麼", "怎麼查"],
        ["PER 快取完整（672/672）", "資格門檻只剔掉真正不合格的股票（PER > 40 或 ≤ 0）", "回測結尾印「完全查不到 PER 0 次」"],
        ["PER 快取只有 267 檔", "六成候選股在評分前被默默剔除，等於用殘缺的池子在選股", "回測結尾的 per_miss 次數變大"],
        ["實盤（v1.1 起）", "先讀 cache/stock_per/ 的磁碟快取，缺檔才打 FinMind", "選股輸出會印「有 PER N 檔」"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(2.9), col_w=[2.4, 6.2, 3.2], size=14)
    _callout(s, "記住這條線：任何「資格門檻」都要先確認資料覆蓋率，否則你調的不是策略，是資料缺口。",
             Inches(0.75), Inches(4.95), Inches(11.85), Inches(0.95), fill=RGBColor(0xFD, 0xEC, 0xEA))

    # ── S6 zscore 重要參數速查 ───────────────────────────────
    s = _content_slide(prs, "zscore 有哪些重要參數（速查）", "3 分鐘",
                       "這頁是操作頁，學員會截圖。分三類：\n\n"
                       "第一類「評分本身」：SCORING_MODEL 決定用 zscore 還是 legacy；權重寫在 core/scoring.py，"
                       "改了要一起改測試跟文件；PER_MAX 是資格門檻 40。\n\n"
                       "第二類「選股口徑」：SELFSELECT_PRESET 是總開關（current／revenue／aggressive），"
                       "它會一次設定池大小、營收因子、產業上限；SELFSELECT_POOL_N 是池大小、"
                       "SELFSELECT_FACTOR_REVENUE 與 SELFSELECT_MAX_PER_SECTOR 可以個別覆寫——"
                       "記住規則：SELFSELECT_ 前綴的明示值優先於 preset。\n\n"
                       "第三類「換股節奏與補位」：TOP_N、REBAL_MONTHS、FILL_MODE。",
                       "提醒學員：沒有 SELFSELECT_ 前綴的 POOL_N／FACTOR_REVENUE 是「回測旋鈕」，實盤不會讀。")
    _table(s, [
        ["變數", "預設", "作用／注意事項"],
        ["SELFSELECT_SCORING_MODEL", "zscore", "評分器：zscore／legacy（legacy 只剩對照用途）"],
        ["WEIGHTS / WEIGHTS_REVENUE", "0.40/0.25/0.20/0.15", "權重寫在 core/scoring.py；改動要同步測試與文件"],
        ["PER_MAX", "40", "資格門檻；沒有 PER 的股票不列入（見上一頁）"],
        ["SELFSELECT_PRESET", "revenue", "總開關：current／revenue（池100＋營收）／aggressive（池150＋營收＋產業上限2）"],
        ["SELFSELECT_POOL_N", "100", "候選池大小；優先於 preset 的池，不一致時 picker 會印警告"],
        ["SELFSELECT_FACTOR_REVENUE", "隨 preset", "月營收 YoY 是否入分數（明示值優先於 preset）"],
        ["SELFSELECT_MAX_PER_SECTOR", "0", "每產業最多幾檔；只有在池 150 實測有效"],
        ["SELFSELECT_TOP_N / REBAL_MONTHS", "5 / 1", "持有檔數／每 N 個月換股"],
        ["SELFSELECT_FILL_MODE", "proportional", "選不滿 N 檔時：平均分配 or 補滿（補滿要用動能遞補）"],
        ["UNIVERSE_DELISTED", "1", "宇宙是否併入 2016-2025 已下市 62 檔（實盤有 45 天新鮮度閘門）"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(5.0), col_w=[3.3, 1.9, 6.6], size=12, hdr_size=12)

    # ── S7 參數怎麼調 ───────────────────────────────────────
    s = _content_slide(prs, "參數怎麼調：一次只動一個", "2 分鐘",
                       "我們的實驗方式是「一次只動一個維度」，而且是同一段資料、同一批成本假設。\n\n"
                       "這張表是三個維度的掃描：池大小 20/50/100/150、營收因子開或關、產業上限兩個。總共十六組。"
                       "為什麼不用大網格一次掃到底？因為組合越多，你越容易挑到剛好漂亮的那一組——"
                       "那不是策略變好，是過度擬合。\n\n"
                       "右邊那條紅線是提醒：比較參數之前，先把資料補滿並記下快照，不然你會把「資料補齊」誤讀成「策略變好」。\n\n"
                       "最下面這張是實例，直接看名單差別：2024-11-29 那天，產業上限關掉時前五名有四檔是航運（2618、2603、2610、2609）——"
                       "那不叫分散五檔，那叫押一個產業。把上限設成 2 檔之後，航運只留 2 檔，補進 2059、3533，產業變成 1／2／2。",
                       "如果學員問「為什麼不做更細的網格」，就用過度擬合回答，並指向後面「誠實看數據」那頁。")
    _table(s, [
        ["維度", "掃過的範圍", "結論一句話"],
        ["池大小", "20 / 50 / 100 / 150", "單獨放大池沒有用（池 50 比池 20 差），要配評分方式"],
        ["營收因子", "關 / 開", "各池大小都是正貢獻；池 100 從 +411.1% → +762.4%"],
        ["產業上限", "無 / 2 檔", "只在池 150 有效（+940.9% → +1323.6%），池 20 反而略差"],
        ["資料快照", "月營收 515 → 645 檔", "同一格從 +1070.5% → +1323.6%，差 253 個百分點"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(2.9), col_w=[1.8, 3.6, 6.5], size=14)
    _callout(s, "調參數的紀律：一次只動一個、同一段資料、同一套成本、結果連資料快照一起記。",
             Inches(0.75), Inches(4.35), Inches(11.85), Inches(0.75))
    # 實例：同一天，產業上限關 / 開，名單怎麼變（2024-11-29、池 100、zscore＋營收因子）
    _table(s, [
        ["上限設定（2024-11-29 實例）", "選出的 5 檔", "產業分布"],
        ["0（不限）", "2345、2618、2603、2610、2609", "通信網路 1、航運 4 ← 等於押一個產業"],
        ["2 檔", "2345、2618、2603、2059、3533", "通信網路 1、航運 2、電子 2"],
    ], Inches(0.75), Inches(5.35), Inches(11.85), Inches(1.15), col_w=[3.0, 5.0, 3.8], size=12, hdr_size=12)

    # ── S8 回測結果①：legacy vs zscore ───────────────────────
    s = _content_slide(prs, "回測結果①：zscore 明顯勝過舊評分", "2 分鐘",
                       "先看最直接的對照：同樣的程式、同樣的池、同樣的成本，只換評分器。\n\n"
                       "legacy 閒置資金是 +61.4%，zscore 是 +129.4%，一倍多。若把閒置資金停泊 0050，"
                       "legacy +207.9%、zscore +762.4%——差距被放大了，因為停泊讓資金全程都在市場裡。\n\n"
                       "所以「AI 那套公式比較好」這句話，有一半其實是「評分方式」的功勞，不是模型的神秘能力。"
                       "這也是我們把它做成可選項、而且直接設成預設的原因。",
                       "這一頁只需要學員記住兩個數字：+207.9% → +762.4%（停泊口徑）。")
    _table(s, [
        ["評分器（正常組、2016-2025、含成本）", "總報酬", "年化", "最大回撤", "夏普"],
        ["legacy·閒置資金", "+61.4%", "+4.9%", "−22.0%", "0.42"],
        ["zscore·閒置資金", "+129.4%", "+8.7%", "−24.2%", "0.68"],
        ["legacy·停泊 0050", "+207.9%", "+11.9%", "−36.0%", "0.69"],
        ["zscore·停泊 0050（＝現行預設口徑）", "+762.4%", "+24.1%", "−53.7%", "0.95"],
        ["0050 買進持有（對照）", "+477.6%", "+19.2%", "−34.0%", "1.06"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.3), col_w=[5.6, 1.8, 1.5, 1.7, 1.2], size=14)

    # ── S9 回測結果②：三個 preset 的取捨 ──────────────────────
    s = _content_slide(prs, "回測結果②：三個口徑、三種代價", "2 分 30 秒",
                       "v1.1 把選股口徑做成三個選項，預設是中間那個 revenue。\n\n"
                       "current 是舊行為，報酬 +411.1%，還是輸 0050。revenue 是預設：池 100 加營收因子，"
                       "總報酬 +762.4% 首次超過 0050，但回撤 −53.7% 是三個裡最深的，夏普 0.95 還是低於 1.06。"
                       "aggressive 是池 150 加營收加產業上限，報酬 +1323.6%、回撤 −40.2%、夏普 1.15——"
                       "夏普首次超過 0050。\n\n"
                       "看起來 aggressive 最好，但它是在同一段歷史上十六組裡事後挑出來的，沒有做 walk-forward。"
                       "所以我們不把它設成預設，只提供開關。",
                       "務必強調「報酬贏 ≠ 策略贏」：回撤 −40~−54% 都大於 0050 的 −34%。")
    _table(s, [
        ["preset", "池", "營收因子", "產業上限", "總報酬", "最大回撤", "夏普"],
        ["current（舊行為）", "100", "關", "無", "+411.1%", "−52.4%", "0.75"],
        ["revenue（預設）", "100", "開", "無", "+762.4%", "−53.7%", "0.95"],
        ["aggressive", "150", "開", "2 檔", "+1323.6%", "−40.2%", "1.15"],
        ["0050 買進持有", "—", "—", "—", "+477.6%", "−34.0%", "1.06"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(2.5), col_w=[3.4, 1.1, 1.5, 1.4, 1.8, 1.8, 1.2], size=14)
    _bullets(s, [
        ("口徑：正常組、2016-01-01~2025-12-31、100 萬、TOP5、每月換股、停泊 0050＋大盤年線、含手續費與證交稅", 0, False),
        ("資料快照：宇宙 672 檔（610 存活＋62 已下市）、PER 672/672、月營收 645/672", 0, False),
        ("選哪一個由你決定：預設 revenue，想回舊行為設 current，想追最高歷史報酬設 aggressive", 0, True),
    ], Inches(0.75), Inches(4.15), Inches(11.85), Inches(1.7), size=14)

    # ── S10 回測結果③：池大小與因子 ───────────────────────────
    s = _content_slide(prs, "回測結果③：關鍵發現是營收因子，不是大池", "2 分 30 秒",
                       "這張表請看兩件事。\n\n"
                       "第一，橫著看營收因子：池 50 從 +291.1% 變 +441.7%、池 100 從 +411.1% 變 +762.4%、"
                       "池 150 從 +541.7% 變 +940.9%。也就是說，唯一能穩定把報酬推上去的是營收因子。\n\n"
                       "第二，直著看池大小：不開營收因子時，池 50 甚至比池 20 差。所以「池越大越好」是錯的，"
                       "池變大只是增加可選標的，必須同時換評分方式才有用。這也是為什麼 preset 是「池＋因子」綁在一起。",
                       "池 20 幾乎沒差（+395.1% → +407.1%），因為池 20 的股票本來就有營收快取；這點可以順帶說明資料覆蓋率的影響。")
    _table(s, [
        ["池大小", "營收因子關", "營收因子開", "差距"],
        ["20 檔", "+395.1%", "+407.1%", "+12.0 pp"],
        ["50 檔", "+291.1%", "+441.7%", "+150.6 pp"],
        ["100 檔", "+411.1%", "+762.4%", "+351.3 pp"],
        ["150 檔", "+541.7%", "+940.9%", "+399.2 pp"],
        ["150 檔＋產業上限 2", "+364.2%", "+1323.6%", "+959.4 pp"],
    ], Inches(0.75), BODY_TOP, Inches(7.2), Inches(2.9), col_w=[2.6, 1.9, 1.9, 1.6], size=14)
    _callout(s, "營收因子是「唯一能讓總報酬穩定超過 0050」的因子；池子變大只是把可選標的變多。",
             Inches(8.25), BODY_TOP + Inches(0.1), Inches(4.35), Inches(1.5), fill=RGBColor(0xE8, 0xF5, 0xEC))
    _bullets(s, [
        ("產業上限只在池 150 有效：把回撤從 −54.9% 壓回 −40.2%，夏普 0.98 → 1.15", 0, False),
        ("池 20 加上產業上限反而變差（+407.1% → +389.5%）：窄池硬性分散等於被迫買較弱的產業", 0, False),
    ], Inches(0.75), Inches(4.05), Inches(11.85), Inches(1.5), size=14)

    # ── S11 誠實看數據 ─────────────────────────────────────
    s = _content_slide(prs, "誠實看數據：贏了報酬，沒贏風險", "3 分鐘",
                       "這一頁請大家務必看完，因為它決定你要不要真的用預設。\n\n"
                       "第一，回撤：預設 revenue 是 −53.7%，0050 是 −34.0%。夏普 0.95 還低於 1.06。"
                       "也就是「用更大的回撤換更高的報酬」，不是穩健超額報酬。\n\n"
                       "第二，這是樣本內結果：aggressive 是十六組裡事後挑出來的最好一組，沒有做非重疊窗口或 walk-forward，"
                       "實盤很可能拿不到一樣的數字。\n\n"
                       "第三，結果對資料覆蓋率極度敏感：月營收快取從 515 檔補到 645 檔，同一格就從 +1070.5% 變 +1323.6%，差 253 個百分點。"
                       "所以我們現在講數字，一定連資料快照一起講。",
                       "這頁是整集最重要的道德頁：寧可講難聽，也不要讓學員以為撿到聖杯。")
    _table(s, [
        ["疑點", "實測數字", "怎麼看"],
        ["回撤更深", "預設 −53.7%（0050 −34.0%）", "報酬高是用更大的波動換來的"],
        ["風險調整沒贏", "夏普 0.95（0050 1.06）", "只有 aggressive 的 1.15 超過，但它是事後挑的"],
        ["樣本內偏誤", "16 組挑 1 組、單一 2016-2025 窗口", "沒有 walk-forward，不能外推"],
        ["資料敏感", "月營收 515→645 檔，同一格 +253 pp", "比較前必須凍結快照並記錄"],
        ["下市價偏樂觀", "康友-KY 以最後成交 56.6 計算（實務近歸零）", "地雷股的真實虧損被低估"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(4.1), col_w=[2.2, 5.0, 4.6], size=13)
    _callout(s, "結論一句話：選股、AI 選股、策略三者都還有很大的改進空間——這個預設不是「能贏大盤」的策略。",
             Inches(0.75), Inches(5.15), Inches(11.85), Inches(1.0), fill=RGBColor(0xFD, 0xEC, 0xEA), size=16)

    # ── S12 AI 選股是什麼 ───────────────────────────────────
    s = _content_slide(prs, "AI 選股不是「丟給 AI 自由發揮」", "2 分 30 秒",
                       "很多人聽到 AI 選股，想像的是把股票清單丟給 ChatGPT。我們的做法剛好相反：先把資料整理成"
                       "「只能看到當天之前資訊」的封包，再讓模型在封包裡挑，最後把它的答案連同引用的證據一起存檔。\n\n"
                       "封包裡有：價格動能、距 52 週高、PER、月營收年增率、（可選）法人與新聞，但新聞有截止時間。"
                       "模型必須用我們給的編號引用它看過的資料，不能自己發明新股票代號——不符合就直接判為不合法。\n\n"
                       "每一份封包、提示詞、回應、稽核檔都留 sha256，所以三個月後你還能回答「當初它為什麼挑這五檔」。",
                       "這一頁建立信任感：AI 選股的重點不是模型多聰明，而是可稽核、不可事後修改。")
    _table(s, [
        ["元件", "內容", "為什麼要"],
        ["PIT 封包", "只用 as_of 之前可得的價格／PER／營收（＋可選法人、新聞）", "避免用到未來資訊"],
        ["提示詞", "固定格式，要求引用 [R#] 編號、不得出現封包外的代號", "可稽核、可重現"],
        ["回應解析", "parse_selection() 驗證：數量、代號、引用是否存在", "防止模型亂編"],
        ["稽核檔", "pack.json／prompt.txt／response.json／audit.json（含 sha256）", "事後能追責與比較"],
        ["省時模式", "SELFSELECT_AI=1 讓 D1 由人來跑，逾期自動 fallback 規則選股", "不讓選股卡住"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.9), col_w=[1.8, 6.0, 4.0], size=13)

    # ── S13 資料紀律：1 天 lookahead 的教訓 ──────────────────
    s = _content_slide(prs, "資料紀律：那一天的 lookahead 我們栽過", "2 分 30 秒",
                       "這是真實的翻車。第一版封包的 as_of 是「當月第一個交易日的收盤」，"
                       "而引擎真正選股用的是「前一個交易日收盤」——等於模型比程式多看到了當天的價格，"
                       "而那天的價格正好是它的進場價。\n\n"
                       "結果就是漂亮的假數字：AI 停泊口徑 +651.7%。修正後重跑 117 份封包，變成 +349.4%，"
                       "跟程式同一口徑比才公平。\n\n"
                       "所以現在的規則是：封包 as_of 一律等於引擎的 sel_date（前一個交易日）；新聞截止 13:30；"
                       "月營收用公告時間或次月 10 日保守估。這三條都寫進測試了。",
                       "這頁可以用來教「回測偏誤怎麼發生的」，比抽象講解有效得多。")
    _table(s, [
        ["規則", "具體做法", "違反的後果"],
        ["封包時點", "as_of ＝ 引擎 sel_date（當月第一個交易日的「前一個」交易日收盤）", "多看到 1 天，報酬被高估（+651.7% → +349.4%）"],
        ["新聞截止", "只收 13:30 之前的新聞", "用到盤後消息，等於偷看"],
        ["月營收時點", "用 FinMind create_time，否則保守取次月 10 日", "營收公布前就用到，高估成長"],
        ["自動檢查", "assert_no_lookahead() 在建立封包時逐欄驗證", "錯誤會在產生封包時就爆，不會流進回測"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.3), col_w=[1.8, 5.8, 4.6], size=13)

    # ── S14 怎麼用 AI 選股（實作流程）───────────────────────────
    s = _content_slide(prs, "怎麼用 AI 選股：D1 五步、逾期自動接手", "3 分鐘",
                       "先定義名詞，不然後面會聽不懂。D1＝每個月的「選股第一日」，也就是該月第 1 個交易日；"
                       "盤後 13:36 起系統會跑選股、改寫 .env 的持股名單。D2＝第 2 個交易日，13:25–13:30 依訊號換股進場。"
                       "所以 D1 是「決定買什麼」的那天，D2 是「真的買」的那天。\n\n"
                       "實作流程五步。\n\n"
                       "第一步，.env 設 SELFSELECT_AI=1，期限預設 13:50。第二步，D1 你跑 "
                       "scripts/ai_pick_dsh.py --emit prompt，它會依當天資料產生封包與提示詞。"
                       "第三步，把提示詞貼給任何一個 LLM（在 DSH 裡切模型也可以），拿到 JSON。\n\n"
                       "第四步，用 --picks-file 把名單交回程式，它會驗證格式與代號，然後寫進 .env 的 PC_ 名單，"
                       "同時在 logs/selfselect_auto.json 記下 ai_applied=YYYY-MM。第五步，什麼都不做也行："
                       "期限前沒完成，系統就自動退回規則選股，而且不會反過來覆蓋你已套用的名單。",
                       "現場示範一次 --emit prompt 的輸出最有效；提醒學員不要把 AI 名單直接手改 .env，要用 --picks-file 走驗證。")
    _table(s, [
        ["步驟", "指令／設定", "產出"],
        ["① 開啟 AI 模式", "SELFSELECT_AI=1、SELFSELECT_AI_DEADLINE=13:50", "D1 選股會等人，不直接跑規則"],
        ["② 產生封包與提示詞", "python scripts/ai_pick_dsh.py --emit prompt --as-of <日期>", "prompt.txt＋pack.json（可用 --emit pack）"],
        ["③ 交給 LLM 判斷", "貼進 DSH 對話（可切模型），回傳 JSON 名單", "含 [R#] 引用的選股理由"],
        ["④ 交回程式", "… --picks-file mypicks.json（或 --apply-env 直接寫 .env）", "驗證通過才寫入 PC_ 名單"],
        ["⑤ 逾期 fallback", "期限前沒完成 ⇒ 自動用規則選股（不會覆蓋已套用的 AI 名單）", "logs/selfselect_auto.json 記 ai_applied"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(2.6), col_w=[2.0, 6.4, 3.4], size=13)
    _callout(s, "D1 ＝ 每月選股第一日（該月第 1 個交易日）：盤後 13:36 起選股、改寫 .env 的持股名單；AI 模式的期限是 13:50。\n"
                "D2 ＝ 第 2 個交易日：13:25–13:30 依訊號換股進場。⇒ D1 決定「買什麼」，D2 才真的「買」。",
             Inches(0.75), Inches(4.05), Inches(11.85), Inches(1.15), size=14)
    _bullets(s, [
        ("D1 沒完成也不會卡住：期限一過，系統自動用規則選股；已套用的 AI 名單不會被覆蓋", 0, False),
        ("名單沿用到下一個 D1：中間每天只依策略訊號進出，不會因為盤中波動改選股", 0, False),
    ], Inches(0.75), Inches(5.35), Inches(11.85), Inches(1.2), size=13)

    # ── S15 AI vs 程式實測 ──────────────────────────────────
    s = _content_slide(prs, "AI vs 程式：目前沒有證據說 AI 比較好", "3 分鐘",
                       "我們做了兩種比較。第一種是「LLM 親自判斷 vs 公式」：2024 年 12 個選股日，"
                       "用同一批封包讓 LLM 挑，結果與 z 分數公式幾乎打平，配對檢定全部不顯著。\n\n"
                       "第二種是「AI 名單 vs 程式選股」的整段回測：AI 名單停泊口徑 +348.2%，"
                       "程式（zscore）是 +762.4%——以目前版本，程式反而比較好。\n\n"
                       "要特別說清楚：AI 名單是用舊宇宙的封包產生的（少了 62 檔下市股、也沒有營收因子），"
                       "所以這個比較對 AI 稍微不利；要嚴格比，得重跑 117 份封包。誠實的結論是："
                       "目前沒有證據支持「讓 AI 挑」比公式好，但也還沒證明它比較差。",
                       "不要替 AI 加油也不要唱衰；把「樣本 12 天、全部不顯著」講清楚就是最好的教學。")
    _table(s, [
        ["比較", "樣本／口徑", "結果"],
        ["LLM 判斷 vs zscore 公式", "2024 年 12 個選股日、同一批 PIT 封包", "1／3／6／12 個月全部不顯著（差距 +0.45%~+1.68%）"],
        ["LLM 判斷 vs legacy 評分", "同上", "1 個月 +1.51%（t=1.96），其餘不顯著"],
        ["AI 名單整段回測（停泊 0050）", "2016-2025、池 20、含成本", "+348.2%（程式 zscore 同口徑 +762.4%）"],
        ["AI 名單（閒置資金）", "同上", "+106.5%（程式 +129.4%）"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.2), col_w=[3.6, 3.8, 4.4], size=13)
    _callout(s, "AI 名單是用「舊宇宙」的封包產生的 ⇒ 這個比較對 AI 略不利；要嚴格比得重跑 117 份封包。",
             Inches(0.75), Inches(5.1), Inches(11.85), Inches(0.9))

    # ── S16 可能的改進方式 ──────────────────────────────────
    s = _content_slide(prs, "可能的改進方式（依槓桿大小排序）", "3 分鐘",
                       "最後一段講改進。我按「改一個能拿到多少」排序，前三項是我們認為最該先做的。\n\n"
                       "第一，驗證強度：現在所有超過 0050 的結果都來自同一段 2016-2025，而且是在十六組裡挑出來的。"
                       "要做非重疊窗口加 walk-forward，否則不知道是真本事還是運氣。\n\n"
                       "第二，產業上限：程式已經接進實盤（變數 SELFSELECT_MAX_PER_SECTOR，preset aggressive 會開），"
                       "但預設是關的，而且回測有效的是「池 150」情境，實盤現在跑池 100，這格還沒實測過，預設值也還沒定。"
                       "第三，資料：上櫃下市股沒納入、法人只有 41 個交易日、新聞預設關閉、成本沒算滑價。\n\n"
                       "最後一項是因子本身：目前只有動能、評價、營收，缺品質（ROE）、低波動、法人籌碼。"
                       "但每加一個因子就要做一次 A/B，不然就是過度擬合。",
                       "這頁可以當作業：請學員挑一項，用同一段資料做一次 A/B，下次上課報告。")
    _table(s, [
        ["優先", "缺口", "下一步", "預期效果"],
        ["1", "驗證強度不足（樣本內挑選）", "非重疊窗口＋逐年 walk-forward，固定資料快照", "知道 +762% 是真本事還是運氣"],
        ["2", "產業上限尚未定調", "已接進實盤（SELFSELECT_MAX_PER_SECTOR／preset aggressive 會開），待決定預設值＋實測驗證", "回撤可壓低（池150：−54.9%→−40.2%）"],
        ["3", "資料缺口", "補上櫃（TPEX）下市股、法人歷史、可稽核新聞源", "宇宙與資訊量更接近實務"],
        ["4", "成本假設太樂觀", "加滑價與部分成交假設，用實盤成交紀錄回推", "報酬會下修，但更真實"],
        ["5", "因子太少", "品質（ROE）、低波動、法人籌碼，一次只加一個做 A/B", "可能提升夏普，不是提高報酬"],
        ["6", "出場機制單薄", "組合層級減碼（不是個股停損）", "壓回撤，換取夏普"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(4.3), col_w=[0.9, 3.4, 4.6, 3.0], size=13)

    # ── S17 版本與部署紀律 ──────────────────────────────────
    s = _content_slide(prs, "版本與部署紀律（v1.1.x 起）", "1 分 30 秒",
                       "這一頁是專案紀律，跟策略無關但很重要。\n\n"
                       "第一，只要程式有修改，版號就要加一：1.1.0、1.1.1、1.1.2、1.1.3。純文件修改不動版號；"
                       "大升版由我決定時再跳。\n\n"
                       "第二，部署由你自己手動跑 ./deploy_source.sh，任何自動化流程都不代跑。"
                       "換版後看啟動 banner 的版號與原始碼指紋就知道跑的是哪一版。\n\n"
                       "第三，儀表板發佈走 gh-pages 分支，main 只由人推——不然機器人每天推 commit，"
                       "你本機 push 就會被拒（我們真的遇過）。",
                       "這頁可以縮短；若時間不夠，只講「改程式就加版號、部署自己跑、main 只由人推」三句。")
    _table(s, [
        ["規則", "內容", "為什麼"],
        ["版號", "程式有修改 ⇒ APP_VERSION +1；大升版由使用者通知", "VM banner／Telegram／儀表板都顯示版本，換版可驗證"],
        ["部署", "deploy_source.sh 一律由使用者手動執行", "避免自動化在有持倉時重啟容器"],
        ["分支", "儀表板推 gh-pages；main 只由人推", "機器人推 main 會讓人手 push 被拒（非 fast-forward）"],
        ["資料快照", "報告要寫宇宙／PER／營收的覆蓋率", "換快照結果就會變，不寫就無法覆核"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(3.0), col_w=[1.6, 5.4, 4.8], size=13)

    # ── S18 總結與作業 ─────────────────────────────────────
    s = _content_slide(prs, "總結：三個數字、兩個動作、一個提醒", "2 分鐘",
                       "收尾。三個數字：預設口徑 +762.4%（0050 +477.6%）、回撤 −53.7%（0050 −34%）、夏普 0.95（0050 1.06）。"
                       "兩個動作：一是想回舊行為設 SELFSELECT_PRESET=current，二是想試 AI 選股設 SELFSELECT_AI=1 然後按五步流程跑一次。"
                       "一個提醒：這仍是樣本內結果，還沒有 walk-forward，先小額或紙上跑一段再說。\n\n"
                       "作業：挑一個改進項目做一次 A/B（例如把產業上限接進實盤），下次上課報告你的數字與口徑。\n\n"
                       "另外要說清楚這門課的節奏：從 2026-10-30 起才開始真正的實測與持續改進，"
                       "所以講義上的數字是「當天版本」，之後每一次程式修改都會升版號並更新到 Git 專案。"
                       "要看最新版、最新回測與最新的改進清單，一律以 Git 專案為準。",
                       "最後留 30 秒問答；把 Git 專案網址、README 的「改進空間」與 cairn/LOG 一起指給學員當延伸閱讀。")
    _bullets(s, [
        ("三個數字：+762.4%（0050 +477.6%）／回撤 −53.7%（−34.0%）／夏普 0.95（1.06）", 0, False),
        ("兩個動作：想回舊行為 SELFSELECT_PRESET=current；想試 AI 選股 SELFSELECT_AI=1 跑五步流程", 0, False),
        ("一個提醒：這是樣本內結果，沒有 walk-forward；先小額或紙上跑一段，再決定要不要當正式口徑", 0, True),
        ("作業：挑一個改進項目做 A/B（例：產業上限接進實盤），下次報告數字與口徑", 0, False),
        ("📌 自 2026-10-30 起開始實測、持續改進；最新更新請上 Git 專案：github.com/dinchentech/tw-selfselect", 0, False),
    ], Inches(0.9), BODY_TOP + Inches(0.2), Inches(11.5), Inches(3.9), size=18, gap=11)

    # ── S19 風險與獲利的抉擇（最後提醒）────────────────────────
    s = _content_slide(prs, "最後提醒：選股很重要，但代價是風險", "3 分鐘",
                       "這頁是整集的收尾提醒，也是最重要的一頁。\n\n"
                       "同樣的策略骨架、同樣的成本假設，v1.0 換到 v1.1 唯一的差別就是「選股變強了」——評分從 legacy 換成 zscore，"
                       "池子放大、再加上營收因子。結果是總報酬從 +207.9% 變成 +762.4%，將近 3.7 倍。這就是「選股很重要」。\n\n"
                       "但同一張表右邊兩欄請一起看：最大回撤從 −36.0% 變成 −53.7%，深了將近 18 個百分點；夏普只從 0.69 升到 0.95，"
                       "還是輸給 0050 的 1.06。換句話說，你拿到的不是「更穩的報酬」，而是「更刺激的報酬」。\n\n"
                       "所以最後這句要講清楚：風險與獲利之間怎麼取捨，是使用者自己的決定，不是策略作者能替你決定的。"
                       "保守的人留在 current（+411.1%、回撤 −52.4%），想追報酬的切 revenue 或 aggressive，但請先想清楚"
                       "「−53.7% 的時候你抱不抱得住」。",
                       "這一頁請放慢速度；可以現場問一句「如果你的帳戶從 100 萬掉到 46 萬，你會不會手動砍掉？」，讓學員自己回答。")
    _table(s, [
        ["同樣的策略骨架、同樣的成本", "總報酬", "最大回撤", "夏普"],
        ["v1.0：legacy 評分（池 20、無營收因子）", "+207.9%", "−36.0%", "0.69"],
        ["v1.1：zscore＋池 100＋營收因子（預設）", "+762.4%", "−53.7%", "0.95"],
        ["差別（v1.1 − v1.0）", "+554.5 pp（約 3.7 倍）", "回撤深 17.7 pp", "+0.26"],
        ["對照：0050 買進持有", "+477.6%", "−34.0%", "1.06"],
    ], Inches(0.75), BODY_TOP, Inches(11.85), Inches(2.7), col_w=[5.2, 2.2, 2.2, 1.6], size=14)
    _callout(s, "選股很重要：同樣的策略，v1.1 把選股加強後獲利大增（+207.9% → +762.4%）；但風險也一起放大（回撤 −36.0% → −53.7%）。\n"
                "要不要換？這是你的決定：保守留 current、追報酬切 revenue／aggressive——沒有免費的午餐。",
             Inches(0.75), Inches(4.35), Inches(11.85), Inches(1.35), fill=RGBColor(0xFD, 0xEC, 0xEA), size=15)
    _bullets(s, [
        ("先問自己一句：帳戶從 100 萬掉到 46 萬時，你抱不抱得住？抱不住就不要選高回撤的口徑", 0, True),
        ("任何口徑都可以先用小額／紙上跑一段，再決定要不要變成正式設定（SELFSELECT_PRESET 隨時可切回）", 0, False),
    ], Inches(0.75), Inches(5.85), Inches(11.85), Inches(1.1), size=14)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"已寫 {OUT}（{len(prs.slides.__iter__.__self__._sldIdLst)} 頁）")


if __name__ == "__main__":
    build()
