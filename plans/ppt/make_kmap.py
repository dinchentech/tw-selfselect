#!/usr/bin/env python3
"""make_kmap.py · 「K 線怎麼看」直式 9:16 六頁（`plans/ppt/kmap/kmap.pptx`）

內容：① 紅綠蠟燭怎麼看（開高低收、實體與影線）② 幾個重要型態（長紅／長綠／錘子／十字星／
多頭吞噬／空頭吞噬）③ 型態要看位置與確認 ④ 本系統使用者**不用自己看 K 線**，由程式／AI 代勞。

視覺語言沿用 `make_stock_index.py`（深藍黑漸層、紅重點、6.20×11.02 吋直式），
示意圖全部 matplotlib 現畫（不引用外部圖檔）。講稿備註格式用 `⏱ 建議時間：`＋`【講師提示】`，
可直接接 `notes_to_script.py` → `generate_narration.sh build` 配音，再 `ppt_to_mp4.sh` 出直式 MP4。

重跑：
    MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_kmap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "plans/ppt")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from matplotlib.patches import Rectangle              # noqa: E402
from pptx import Presentation                         # noqa: E402
from pptx.enum.text import PP_ALIGN                   # noqa: E402
from pptx.util import Inches, Pt                      # noqa: E402

import make_stock_index as S                          # noqa: E402  版面元件
import make_why_design as W                           # noqa: E402  背景與共用視覺
from why_icons import icon as draw_icon               # noqa: E402

OUT = Path(ROOT / "plans/ppt/kmap/kmap.pptx")
TOTAL = 6

UP = W.ACCENT                    # 台股：紅＝漲
DOWN = S.GREEN                   # 綠＝跌


def _candle(ax, x, o, h, l, c, *, width=0.62, glow=False, alpha=1.0):
    """畫一根 K 棒（台股：紅漲綠跌）。"""
    color = S._hex(UP if c >= o else DOWN)
    ax.plot([x, x], [l, h], color=color, lw=1.6, solid_capstyle="butt", alpha=alpha, zorder=3)
    y0, height = min(o, c), abs(c - o)
    ax.add_patch(Rectangle((x - width / 2, y0), width, max(height, 0.02),
                           facecolor=color, edgecolor=color, linewidth=1.0,
                           alpha=alpha, zorder=4))
    if glow:
        ax.add_patch(Rectangle((x - width / 2 - 0.10, min(o, c) - 0.10), width + 0.20,
                               max(height, 0.02) + 0.20, facecolor="none",
                               edgecolor=S._hex(W.TEXT), lw=1.2, ls=(0, (2, 2)), zorder=6))


def _tag(ax, xy, text, *, ha="center", va="center", color=None, size=13.0, xytext=(0, 0),
         arrow=False):
    kw = dict(boxstyle="round,pad=0.22", facecolor="#0A1424", edgecolor="none", alpha=0.9)
    props = dict(ha=ha, va=va, fontproperties=None, fontsize=size,
                 color=S._hex(color or W.TEXT), bbox=kw)
    if arrow:
        props["arrowprops"] = dict(arrowstyle="-", color=S._hex(W.MUTED), lw=1.0,
                                   shrinkA=1, shrinkB=3)
    ax.annotate(text, xy, xytext=xytext, textcoords="offset points" if not arrow else "data",
                **props)


# ── 圖① 一根 K 線：開高低收＋實體／影線 ────────────────────────────────
def basics_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    path = W.BUILD / "kmap_basics.png"
    fig = S._fig()
    ax = fig.add_axes([0.125, 0.09, 0.855, 0.84])
    S._bare(ax)

    bars = [
        (1, 100.0, 102.2, 98.9, 101.6),      # 紅
        (2, 101.6, 102.4, 99.4, 100.1),      # 綠
        (3, 100.1, 101.8, 99.6, 101.2),      # 紅
        (4, 101.2, 105.0, 99.8, 104.4),      # 紅（標註）
    ]
    for x, o, h, l, c in bars:
        _candle(ax, x, o, h, l, c, glow=(x == 4), width=0.56)

    o, h, l, c = bars[3][1:]
    tag = dict(boxstyle="round,pad=0.22", facecolor="#0A1424", edgecolor="none", alpha=0.92)
    lead = dict(arrowstyle="-", color=S._hex(W.MUTED), lw=1.0, shrinkA=1, shrinkB=3)

    def lab(xy, text, xytext, ha, va, *, color=None, size=13, font=None):
        ax.annotate(text, xy, xytext=xytext, textcoords="data", ha=ha, va=va,
                    fontproperties=font or reg, fontsize=size,
                    color=S._hex(color or W.TEXT), bbox=tag, arrowprops=lead)

    # 右側欄：開高低收（上下錯開，避免標籤互疊）
    for y, text, ty in ((h, "最高", h + 0.30), (c, "收盤", c - 0.20),
                        (o, "開盤", o - 0.20), (l, "最低", l - 0.35)):
        lab((4.34, y), text, (6.55, ty), "left", "center", size=13.5, font=bold)
    # 近欄：實體／上影線／下影線
    lab((4.34, (o + c) / 2), "實體", (4.72, (o + c) / 2), "left", "center", size=12.5, font=bold)
    lab((4.34, (h + c) / 2), "上影線", (5.30, h + 0.55), "left", "center", size=12, color=W.SOFT)
    lab((4.34, (l + o) / 2), "下影線", (5.30, l - 0.85), "left", "center", size=12, color=W.SOFT)

    ax.text(0.015, 0.975, "紅 K：收盤 > 開盤（漲）", transform=ax.transAxes, ha="left",
            va="top", fontproperties=bold, fontsize=13.5, color=S._hex(UP), bbox=tag)
    ax.annotate("綠 K：收盤 < 開盤（跌）", (2, bars[1][3]), xytext=(0, -18),
                textcoords="offset points", ha="center", va="top", fontproperties=bold,
                fontsize=13.5, color=S._hex(DOWN), bbox=tag,
                arrowprops=dict(arrowstyle="-", color=S._hex(DOWN), lw=1.0, shrinkB=4))

    ax.set_xlim(0.3, 9.4)
    ax.set_ylim(95.8, 108.4)
    ax.set_xticks([])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_ylabel("股價（元）", fontproperties=reg, fontsize=12.5, color=S._hex(W.MUTED), labelpad=3)

    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖② 三個型態：長紅／長綠／錘子線 ──────────────────────────────────
def patterns_a_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    path = W.BUILD / "kmap_patterns_a.png"
    fig = S._fig()
    ax = fig.add_axes([0.04, 0.06, 0.92, 0.88])
    S._bare(ax)
    ax.set_facecolor("none")
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])

    # 長紅
    _candle(ax, 1.0, 100.0, 103.6, 99.6, 103.2, width=0.52)
    # 長綠
    _candle(ax, 4.0, 103.2, 103.6, 99.4, 100.0, width=0.52)
    # 錘子線：小實體在頂端＋長下影線
    _candle(ax, 7.0, 102.4, 103.0, 98.2, 102.8, width=0.52)

    for x, name, hint, color in (
            (1.0, "長紅", "買方一路壓著打\n實體越長越強", UP),
            (4.0, "長綠", "賣方全面勝出\n小心繼續破底", DOWN),
            (7.0, "錘子線", "盤中殺很深又被拉回\n下方有人接", W.TEXT)):
        ax.text(x, 96.6, name, ha="center", va="top", fontproperties=bold, fontsize=16,
                color=S._hex(color))
        ax.text(x, 95.4, hint, ha="center", va="top", fontproperties=reg, fontsize=11.5,
                color=S._hex(W.SOFT), linespacing=1.45)

    ax.annotate("實體長", (1.27, 101.6), xytext=(1.9, 101.6), textcoords="data", ha="left",
                va="center", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED),
                arrowprops=dict(arrowstyle="-", color=S._hex(W.MUTED), lw=0.9, shrinkB=4))
    ax.annotate("小實體", (7.27, 102.6), xytext=(7.9, 104.2), textcoords="data", ha="left",
                va="center", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED),
                arrowprops=dict(arrowstyle="-", color=S._hex(W.MUTED), lw=0.9, shrinkB=4))
    ax.annotate("長下影線", (7.0, 100.2), xytext=(6.2, 98.6), textcoords="data", ha="right",
                va="center", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED),
                arrowprops=dict(arrowstyle="-", color=S._hex(W.MUTED), lw=0.9, shrinkB=4))

    ax.set_xlim(-0.2, 9.0)
    ax.set_ylim(93.6, 105.6)
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖③ 三個型態：十字星／多頭吞噬／空頭吞噬 ───────────────────────────
def patterns_b_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    path = W.BUILD / "kmap_patterns_b.png"
    fig = S._fig()
    ax = fig.add_axes([0.04, 0.06, 0.92, 0.88])
    S._bare(ax)
    ax.set_facecolor("none")
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])

    # 十字星
    _candle(ax, 1.0, 101.6, 103.4, 99.8, 101.65, width=0.52)
    # 多頭吞噬：前天長綠，今天更長的紅完全包住
    _candle(ax, 3.6, 103.0, 103.4, 100.4, 100.6, width=0.46)
    _candle(ax, 4.4, 100.2, 103.8, 100.0, 103.4, width=0.46, glow=True)
    # 空頭吞噬：前天長紅，今天更長的綠包住
    _candle(ax, 6.6, 100.4, 103.4, 100.0, 103.0, width=0.46)
    _candle(ax, 7.4, 103.6, 103.9, 99.9, 100.3, width=0.46, glow=True)

    for x, name, hint, color in (
            (1.0, "十字星", "開收幾乎一樣\n多空拉鋸、方向不明", W.TEXT),
            (4.0, "多頭吞噬", "長紅包住昨天的長綠\n由空翻多", UP),
            (7.0, "空頭吞噬", "長綠包住昨天的長紅\n由多翻空", DOWN)):
        ax.text(x, 96.5, name, ha="center", va="top", fontproperties=bold, fontsize=16,
                color=S._hex(color))
        ax.text(x, 95.4, hint, ha="center", va="top", fontproperties=reg, fontsize=11.5,
                color=S._hex(W.SOFT), linespacing=1.45)

    ax.set_xlim(-0.2, 9.0)
    ax.set_ylim(94.6, 105.0)
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖④ 同一個型態、不同位置：低檔錘子 vs 高檔錘子 ─────────────────────
def position_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    path = W.BUILD / "kmap_position.png"
    fig = S._fig()

    def panel(rect, xs, price, hammer_idx, after, label, color):
        ax = fig.add_axes(rect)
        S._bare(ax)
        for i, (x, (o, h, l, c)) in enumerate(zip(xs, price)):
            _candle(ax, x, o, h, l, c, width=0.46, glow=(i == hammer_idx))
        # 之後走勢：一根箭頭
        ax.annotate("", xy=(xs[hammer_idx] + 1.5, after), xytext=(xs[hammer_idx] + 0.55, price[hammer_idx][3]),
                    arrowprops=dict(arrowstyle="-|>", color=S._hex(color), lw=2.2))
        ax.text(0.5, 0.94, label, transform=ax.transAxes, ha="center", va="top",
                fontproperties=bold, fontsize=14, color=S._hex(color))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0.3, len(xs) + 0.6)
        lo = min(p[2] for p in price)
        hi = max(p[1] for p in price)
        pad = (hi - lo) * 0.35
        ax.set_ylim(min(lo, after) - pad, max(hi, after) + pad)

    xs = list(range(1, 6))
    # 低檔：下跌 → 錘子 → 反轉向上
    low = [(104, 104.6, 102.8, 103.0), (103.0, 103.2, 101.4, 101.8),
           (101.8, 102.0, 100.0, 100.4), (100.4, 101.0, 98.2, 100.6), (100.6, 102.6, 100.2, 102.2)]
    # 高檔：上漲 → 錘子 → 續跌
    high = [(100, 100.6, 99.4, 100.2), (100.2, 102.0, 100.0, 101.8),
            (101.8, 103.6, 101.6, 103.4), (103.4, 104.0, 101.8, 103.8), (103.8, 104.0, 101.6, 101.9)]

    panel([0.06, 0.10, 0.42, 0.78], xs, low, 3, 103.6, "低檔錘子 → 反轉向上", UP)
    panel([0.52, 0.10, 0.42, 0.78], xs, high, 3, 100.6, "高檔錘子 → 可能只是洗盤", DOWN)

    fig.text(0.5, 0.015, "同一個型態，位置不同、意思就不同；再看隔天有沒有確認",
             ha="center", va="bottom", fontproperties=reg, fontsize=11.5, color=S._hex(W.SOFT))
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 內容 ─────────────────────────────────────────────────────────────
COVER_TITLE = "K 線怎麼看"
COVER_SUB = "紅綠蠟燭・重要型態・你其實不用自己看"

P2_DEF = ["一根 K 線＝一段時間的開盤、最高、最低、收盤。",
          "收盤 > 開盤畫紅 K（漲）；收盤 < 開盤畫綠 K（跌）。"]
P2_ROWS = [("candle", "實體越長＝當天多空力量差距越大", ("實體",)),
           ("range", "影線＝盤中被拉回或撐住的位置（上影線＝壓力、下影線＝支撐）", ("壓力", "支撐"))]
P2_CALL = ["型態只是結果：", "先看它是紅是綠、實體多長、影線多長。"]

P3_DEF = ["三種最常見的單根型態：長紅、長綠、錘子線。"]
P3_ROWS = [("arrow_up", "長紅：買方壓著打，常是攻擊訊號", ("長紅",)),
           ("valley", "長綠：賣方全面勝出，小心續跌", ("長綠",)),
           ("warn", "錘子線：殺很深又被拉回，下方有人接", ("錘子線",))]
P3_CALL = ["錘子線要看下一根：", "隔天收紅才算真的接住了。"]

P4_DEF = ["兩根一組的型態：十字星、多頭吞噬、空頭吞噬。"]
P4_ROWS = [("divide", "十字星：開收幾乎相同，多空拉鋸、方向不明", ("十字星",)),
           ("arrow_up", "多頭吞噬：長紅包住昨天的長綠 ⇒ 由空翻多", ("多頭吞噬",)),
           ("valley", "空頭吞噬：長綠包住昨天的長紅 ⇒ 由多翻空", ("空頭吞噬",))]
P4_CALL = ["吞噬要「包住」：", "今天的高低點整個蓋過昨天。"]

P5_DEF = ["同一個型態，位置不同、意思就不同；而且型態是機率，不是保證。"]
P5_ROWS = [("scale", "跌深出現錘子＝有人接；漲高出現錘子＝可能只是洗盤", ("跌深", "漲高")),
           ("chart_x", "只有型態、沒有量與趨勢配合 ⇒ 雜訊居多", ("雜訊",))]
P5_CALL = ["先問三件事：", "在哪個位置？量有沒有出來？下一根有沒有確認？"]

P6_ROWS = [("gear_check", "程式每天算：均線、型態、ATR、RSI", ("程式",)),
           ("robot", "選股與進出場自動判斷、自動下單", ("自動",)),
           ("person", "你只要看 Telegram 通知與儀表板", ("Telegram",))]
P6_CALL = ["K 線交給程式看就好——", "你不需要盯盤，也不用背型態。"]

SECONDS = {1: 10, 2: 34, 3: 32, 4: 32, 5: 30, 6: 30}

SPOKEN = {
    1: ["K 線是股市最古老、也最直覺的圖。",
        "這一節講三件事：紅綠蠟燭怎麼看、幾個重要型態，以及為什麼你其實不用自己盯。"],
    2: ["一根 K 線有四件事：開盤、最高、最低、收盤。收盤比開盤高就畫紅色，叫紅 K；收盤比開盤低就畫綠色，叫綠 K。",
        "中間那條粗線叫實體，越長代表當天多空力量差距越大；上下的細線叫影線，代表盤中被拉回或撐住的位置。"],
    3: ["三個常見型態。長紅：實體很長、一路走高，代表買方壓著打；長綠反過來，賣方全面勝出，小心續跌。",
        "錘子線：實體在頂端、下影線很長，代表盤中殺很深又被拉回，下方有人接——但要等下一根收紅才算真的接住。"],
    4: ["兩根一組的型態。十字星：開盤收盤幾乎一樣，代表多空拉鋸、方向不明。",
        "多頭吞噬：一根長紅完全包住前一天的長綠，由空翻多；空頭吞噬反過來，長綠包住長紅，由多翻空。",
        "重點是「昨天被今天吃掉」——不是隨便兩根長紅長綠湊在一起就算。"],
    5: ["但型態要看位置。同樣一根錘子線，跌深的時候是有人接，漲高的時候可能只是洗盤。",
        "而且型態是機率，不是保證。所以看型態之前，先問三件事：在哪個位置？量有沒有出來？下一根有沒有確認？"],
    6: ["所以我們的做法是：你不需要看 K 線。程式每天幫你算均線、型態、ATR、RSI，選股與進出場都自動判斷。",
        "你只要看 Telegram 通知跟儀表板就好，不會被單根 K 線嚇到，也不會追高殺低。"],
}
TIPS = {
    2: "台股紅漲綠跌（美股相反：綠漲紅跌）。「黑 K」是台股對綠 K 的舊稱，兩者同義。",
    3: "型態名稱在不同書上略有差異；本頁用最通俗的講法，重點是「實體長度」與「影線長度」怎麼讀。",
    4: "吞噬型態的判定用「今天的高低點整個包住昨天」；十字星在台股常寫成「開收同價」，實際上只要開收差距極小就算。",
    5: "本專案實盤不看單根型態做決策：型態只是路由（順勢／逆勢）的輔助，真正的進出場是策略＋ATR 門檻。",
    6: "選股走每月 D1 自動選股、D2 進場；進出場由四支固定策略（突破／均線交叉／布林／VWAP）＋ATR 過濾決定，"
       "使用者只需要看 Telegram 通知與儀表板。",
}


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W.SLIDE_W, W.SLIDE_H

    bgs = {
        1: W.background("kmap_cover", 601, glow_xy=(0.44, 0.26), glow_r=0.72, glow_s=0.20),
        2: W.background("kmap_s2", 613, glow_xy=(0.86, 0.64), glow_s=0.14),
        3: W.background("kmap_s3", 627, glow_xy=(0.12, 0.68), glow_r=0.70, glow_s=0.14),
        4: W.background("kmap_s4", 641, glow_xy=(0.52, 0.62), glow_s=0.12, glow_r=0.62),
        5: W.background("kmap_s5", 653, glow_xy=(0.18, 0.40), glow_s=0.15, glow_r=0.70),
        6: W.background("kmap_s6", 667, glow_xy=(0.74, 0.22), glow_s=0.13, glow_r=0.66),
    }

    # ① 封面
    s = W._bg_slide(prs, bgs[1])
    W._accent_bar(s, Inches(2.71), Inches(6.62))
    _b, tf = W._textbox(s, S.MARGIN, Inches(6.84), S.CONTENT_W, Inches(2.34))
    W._rich_para(tf.paragraphs[0], COVER_TITLE, ("K 線",), size=Pt(36), bold=True,
                 align=PP_ALIGN.CENTER, line=1.30, space_after=Pt(8))
    W._rich_para(tf.add_paragraph(), COVER_SUB, (), size=Pt(17), bold=True,
                 align=PP_ALIGN.CENTER, line=1.34, space_after=Pt(0), color=W.WHITE)
    icons = ("candle", "warn", "gear_check", "person")
    tile, gap = 0.56, 0.52
    x0 = (6.2014 - (tile * len(icons) + gap * (len(icons) - 1))) / 2
    for i, name in enumerate(icons):
        pic = s.shapes.add_picture(str(draw_icon(name, W.BUILD / "icons", question_glyph=None)),
                                   Inches(x0 + i * (tile + gap)), Inches(9.46),
                                   width=Inches(tile), height=Inches(tile))
        pic.line.fill.background()
    S._notes(s, SECONDS[1], SPOKEN[1],
             "三頁講「怎麼看」、兩頁講「怎麼用」：紅綠蠟燭 → 單根型態 → 兩根型態 → 位置與確認 → 交給程式。")
    W._page_no(s, 1, TOTAL)

    # ② 紅綠蠟燭
    s = W._bg_slide(prs, bgs[2])
    S._title(s, "紅綠蠟燭", "一根 K 線＝開、高、低、收")
    S._chart(s, basics_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.38)), P2_DEF,
                 label="定義", phrase_marks=("紅 K", "綠 K"), size=Pt(15))
    S._icon_row(s, (S.MARGIN, Inches(7.10), S.CONTENT_W, Inches(1.72)), P2_ROWS,
                size=Pt(16.5), row_gap=0.30)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P2_CALL,
               ("紅是綠", "實體", "影線"))
    S._notes(s, SECONDS[2], SPOKEN[2], TIPS[2])
    W._page_no(s, 2, TOTAL)

    # ③ 單根型態
    s = W._bg_slide(prs, bgs[3])
    S._title(s, "三個單根型態", "長紅・長綠・錘子線")
    S._chart(s, patterns_a_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.16)), P3_DEF,
                 label="定義", phrase_marks=("長紅", "長綠", "錘子線"), size=Pt(15.5))
    S._icon_row(s, (S.MARGIN, Inches(6.92), S.CONTENT_W, Inches(1.96)), P3_ROWS,
                size=Pt(16), row_gap=0.24)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P3_CALL,
               ("下一根",))
    S._notes(s, SECONDS[3], SPOKEN[3], TIPS[3])
    W._page_no(s, 3, TOTAL)

    # ④ 兩根型態
    s = W._bg_slide(prs, bgs[4])
    S._title(s, "兩根一組的型態", "十字星・多頭吞噬・空頭吞噬")
    S._chart(s, patterns_b_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.16)), P4_DEF,
                 label="定義", phrase_marks=("十字星", "吞噬"), size=Pt(15.5))
    S._icon_row(s, (S.MARGIN, Inches(6.92), S.CONTENT_W, Inches(1.96)), P4_ROWS,
                size=Pt(16), row_gap=0.24)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P4_CALL,
               ("包住",))
    S._notes(s, SECONDS[4], SPOKEN[4], TIPS[4])
    W._page_no(s, 4, TOTAL)

    # ⑤ 位置與確認
    s = W._bg_slide(prs, bgs[5])
    S._title(s, "同一根，位置不同", "型態是機率，不是保證")
    S._chart(s, position_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.30)), P5_DEF,
                 label="重點", phrase_marks=("位置不同", "機率"), size=Pt(15.5))
    S._icon_row(s, (S.MARGIN, Inches(7.04), S.CONTENT_W, Inches(1.84)), P5_ROWS,
                size=Pt(16), row_gap=0.26)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P5_CALL,
               ("位置", "量", "確認"))
    S._notes(s, SECONDS[5], SPOKEN[5], TIPS[5])
    W._page_no(s, 5, TOTAL)

    # ⑥ 交給程式
    s = W._bg_slide(prs, bgs[6])
    S._title(s, "所以，你不用自己看", "K 線交給程式與 AI")
    S._icon_row(s, (S.MARGIN, Inches(1.96), S.CONTENT_W, Inches(4.60)), P6_ROWS,
                size=Pt(18), row_gap=0.52, icon_in=0.54)
    _b, tf = W._textbox(s, S.MARGIN, Inches(6.86), S.CONTENT_W, Inches(1.60))
    W._rich_para(tf.paragraphs[0], "你看到的會是：", ("你看到的會是",), size=Pt(15), bold=True,
                 line=1.30, space_after=Pt(6), color=W.MUTED)
    W._rich_para(tf.add_paragraph(), "一則 Telegram 通知（買什麼、為什麼、停損在哪）", (),
                 size=Pt(15), line=1.42, space_after=Pt(4))
    W._rich_para(tf.add_paragraph(), "加上每天收盤後更新的儀表板", (), size=Pt(15),
                 line=1.42, space_after=Pt(0))
    S._callout(s, (Inches(0.34), Inches(8.62), Inches(5.52), Inches(1.18)), P6_CALL,
               ("程式",))
    S._notes(s, SECONDS[6], SPOKEN[6], TIPS[6])
    W._page_no(s, 6, TOTAL)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"✅ 產生 {path.relative_to(ROOT)}（{path.stat().st_size / 1024 / 1024:.2f} MB，{TOTAL} 頁）")
    print(f"   中間產物：{W.BUILD.relative_to(ROOT)}/（背景 ×6、示意圖 ×4、圖示）")
