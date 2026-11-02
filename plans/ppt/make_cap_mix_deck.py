#!/usr/bin/env python3
"""make_cap_mix_deck.py · 把 `make_cap_mix.py` 的統計畫成直式 9:16 PPT（`plans/ppt/cap_mix.pptx`）

沿用 `make_why_design.py` 的視覺語言（深藍黑漸層背景、紅重點、直立版型），
三張圖用 matplotlib 現畫：①分級占比甜甜圈 ②各級別策略堆疊條 ③逐年大型股占比。
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "plans/ppt")):
    if p not in sys.path:
        sys.path.insert(0, p)

from pptx.dml.color import RGBColor        # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR   # noqa: E402
from pptx.util import Inches, Pt           # noqa: E402

import make_why_design as W                # noqa: E402  共用視覺元件
from make_cap_mix import STRAT_LABEL, STRATS, TIERS   # noqa: E402

OUT = ROOT / "plans/ppt/cap_mix.pptx"
MARGIN = W.MARGIN
CONTENT_W = W.CONTENT_W

AMBER = RGBColor(0xF0, 0xA6, 0x3C)
BLUE = W.SLATE
TIER_COLOR = {"大型股": W.ACCENT, "中型股": W.SLATE, "小型股": AMBER}
STRAT_COLOR = {"breakout": W.ACCENT, "ma_cross": RGBColor(0xFF, 0x9A, 0x63),
               "bollinger": RGBColor(0x4C, 0x8F, 0xD1), "vwap": RGBColor(0x8F, 0xA6, 0xBE)}


def _hex(rgb: RGBColor) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _fonts():
    return W._cjk_fonts()


# ── 圖 ①：分級占比甜甜圈 ──────────────────────────────────────────────
def donut_png(st: dict) -> Path:
    from matplotlib import font_manager as fm
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    fm.fontManager.addfont(str(reg))
    fm.fontManager.addfont(str(bold))
    f_reg, f_bold = fm.FontProperties(fname=str(reg)), fm.FontProperties(fname=str(bold))

    path = W.BUILD / "capmix_donut.png"
    fig = plt.figure(figsize=(5.0, 3.6), dpi=220)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0.02, 0.02, 0.52, 0.96])
    vals = [st["tier_share"][t] for t in TIERS]
    labels = [f"{t} {v:.0%}" for t, v in zip(TIERS, vals)]
    colors = [_hex(TIER_COLOR[t]) for t in TIERS]
    wedges, _ = ax.pie(vals if sum(vals) > 0 else [1, 0, 0], colors=colors,
                       startangle=90, counterclock=False,
                       wedgeprops={"width": 0.30, "edgecolor": "#0A1424", "linewidth": 2})
    ax.text(0, 0.16, f"{st['n']}", ha="center", va="center", fontproperties=f_bold,
            fontsize=30, color="#FFFFFF")
    ax.text(0, -0.20, f"筆選股／{st['months']} 次", ha="center", va="center",
            fontproperties=f_reg, fontsize=10.5, color=_hex(W.MUTED))
    ax.set_aspect("equal")

    # 右側圖例（自己畫，字級才跟投影片一致）
    y = 0.80
    for t, v, n in zip(TIERS, vals, (st["tier_count"][t] for t in TIERS)):
        fig.add_artist(plt.Rectangle((0.58, y - 0.03), 0.03, 0.06, transform=fig.transFigure,
                                     facecolor=_hex(TIER_COLOR[t]), edgecolor="none"))
        fig.text(0.63, y, t, va="center", ha="left", fontproperties=f_bold, fontsize=13,
                 color="#EAF1F8")
        fig.text(0.98, y, f"{v:.1%}", va="center", ha="right", fontproperties=f_bold, fontsize=15,
                 color=_hex(W.TEXT) if v > 0 else _hex(W.MUTED))
        fig.text(0.63, y - 0.075, f"{n} 筆", va="center", ha="left", fontproperties=f_reg,
                 fontsize=9.5, color=_hex(W.MUTED))
        y -= 0.235
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖 ②：各級別 × 策略 堆疊條 ────────────────────────────────────────
def strat_png(st: dict) -> Path:
    from matplotlib import font_manager as fm
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    fm.fontManager.addfont(str(reg))
    fm.fontManager.addfont(str(bold))
    f_reg, f_bold = fm.FontProperties(fname=str(reg)), fm.FontProperties(fname=str(bold))

    path = W.BUILD / "capmix_strat.png"
    fig = plt.figure(figsize=(5.0, 3.6), dpi=220)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0.03, 0.14, 0.94, 0.70])
    ax.set_facecolor("none")
    ax.axis("off")
    ax.set_xlim(0, 1.50)
    ax.set_ylim(-0.95, len(TIERS) - 0.55)

    for i, t in enumerate(TIERS):
        y = (len(TIERS) - 1 - i)
        total = st["tier_count"][t]
        # 級別名（條的上方）
        ax.text(0, y + 0.30, f"{t}（{total} 筆）", va="bottom", ha="left",
                fontproperties=f_bold, fontsize=11.5, color="#EAF1F8")
        if total == 0:
            ax.text(0, y, "選股池（市值前 100 名）裡沒有這一級", va="center", ha="left",
                    fontproperties=f_reg, fontsize=10, color=_hex(W.MUTED))
            continue
        x = 0.0
        for s_ in STRATS:
            share = st["tier_x_strat"][t][s_]["share"]
            if share <= 0:
                continue
            ax.barh(y, share, left=x, height=0.30, color=_hex(STRAT_COLOR[s_]), edgecolor="none")
            if share >= 0.10:
                ax.text(x + share / 2, y, f"{share:.0%}", va="center", ha="center",
                        fontproperties=f_bold, fontsize=10.5, color="#0A1424")
            x += share
        ax.text(1.03, y, f"順勢 {st['tier_x_side'][t]['順勢']:.0%}", va="center", ha="left",
                fontproperties=f_reg, fontsize=10, color=_hex(W.MUTED))

    # 小字圖例
    x = 0.0
    for s_ in STRATS:
        fig.add_artist(plt.Rectangle((0.03 + x, 0.045), 0.017, 0.026, transform=fig.transFigure,
                                     facecolor=_hex(STRAT_COLOR[s_]), edgecolor="none"))
        fig.text(0.058 + x, 0.058, STRAT_LABEL[s_], va="center", ha="left",
                 fontproperties=f_reg, fontsize=9, color=_hex(W.SOFT))
        x += 0.225
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖 ③：逐年大型股占比 ─────────────────────────────────────────────
def yearly_png(st: dict) -> Path:
    from matplotlib import font_manager as fm
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    fm.fontManager.addfont(str(reg))
    fm.fontManager.addfont(str(bold))
    f_reg, f_bold = fm.FontProperties(fname=str(reg)), fm.FontProperties(fname=str(bold))

    path = W.BUILD / "capmix_yearly.png"
    fig = plt.figure(figsize=(5.0, 2.9), dpi=220)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0.06, 0.20, 0.90, 0.62])
    ax.set_facecolor("none")
    years = list(st["year_tier_share"])
    big = [st["year_tier_share"][y]["大型股"] for y in years]
    mid = [st["year_tier_share"][y]["中型股"] for y in years]
    ax.bar(range(len(years)), big, width=0.52, color=_hex(W.ACCENT), edgecolor="none", label="大型股")
    ax.bar(range(len(years)), mid, width=0.52, bottom=big, color=_hex(W.SLATE),
           edgecolor="none", label="中型股")
    for i, (b, m) in enumerate(zip(big, mid)):
        ax.text(i, b / 2, f"{b:.0%}", ha="center", va="center", fontproperties=f_bold,
                fontsize=11, color="#0A1424")
        if m > 0.07:
            ax.text(i, b + m / 2, f"{m:.0%}", ha="center", va="center", fontproperties=f_bold,
                    fontsize=10.5, color="#0A1424")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, fontproperties=f_reg, fontsize=10, color=_hex(W.MUTED))
    ax.set_ylim(0, 1.06)
    ax.set_yticks([0, .5, 1.0])
    ax.set_yticklabels(["0%", "50%", "100%"], fontproperties=f_reg, fontsize=9,
                       color=_hex(W.MUTED))
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#2C4B74")
    ax.tick_params(colors=_hex(W.MUTED), length=0)
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path



# ── 頁：逆勢（回歸）是怎麼被挑到的 ────────────────────────────────────
def _route_page(prs, bg, st: dict, page: int, total: int) -> None:
    r = st["route"]
    s = W._bg_slide(prs, bg)

    box, tf = W._textbox(s, MARGIN, Inches(1.10), CONTENT_W, Inches(1.1))
    W._rich_para(tf.paragraphs[0], "逆勢是怎麼被挑到的？", ("逆勢",), size=Pt(25), bold=True,
                 line=1.35, space_after=Pt(0))

    # ── 卡 A：順勢＝三條全綠
    W._card(s, (Inches(0.34), Inches(2.06), Inches(5.52), Inches(2.42)), alpha=76)
    box, tf = W._textbox(s, Inches(0.60), Inches(2.24), Inches(5.02), Inches(2.06))
    W._rich_para(tf.paragraphs[0], "順勢：三條全綠才算趨勢", ("三條全綠",), size=Pt(17),
                 bold=True, line=1.3, space_after=Pt(8))
    for line in ("① 收盤價 ＞ 20 日均線", "② 20 日均線 ＞ 60 日均線", "③ 20 日動能 ＞ 0"):
        W._rich_para(tf.add_paragraph(), line, (), size=Pt(15), line=1.35, space_after=Pt(5),
                     color=W.SOFT)
    W._rich_para(tf.add_paragraph(),
                 f"⇒ 全綠 {r['trend_n']} 筆：動能>5% 走突破 {r['breakout_n']}、均線交叉 {r['ma_cross_n']}",
                 ("突破", "均線交叉"), size=Pt(13), line=1.35, space_after=Pt(0), color=W.MUTED)

    # ── 卡 B：逆勢＝任一不綠，看價格站在 20 日線哪一邊
    W._card(s, (Inches(0.34), Inches(4.62), Inches(5.52), Inches(3.30)), alpha=76)
    box, tf = W._textbox(s, Inches(0.60), Inches(4.80), Inches(5.02), Inches(2.96))
    W._rich_para(tf.paragraphs[0], "逆勢：任一條不綠 ⇒ 看價格站在 20 日線哪一邊",
                 ("20 日線哪一邊",), size=Pt(16.5), bold=True, line=1.35, space_after=Pt(9))
    W._rich_para(tf.add_paragraph(), "■ 跌破 20 日線 → 布林回歸（回檔買低）",
                 ("布林回歸",), size=Pt(15), bold=True, line=1.35, space_after=Pt(2),
                 color=W.WHITE)
    W._rich_para(tf.add_paragraph(),
                 f"{r['bollinger_n']} 筆全部都在月線下方（距 20 日線中位 {r['bollinger_dist_median']:+.1%}）",
                 (), size=Pt(12.5), line=1.35, space_after=Pt(10), color=W.MUTED)
    W._rich_para(tf.add_paragraph(), "■ 站上 20 日線、但 20 日線仍在 60 日線下 → VWAP 偏離（等回檔到均價才買）",
                 ("VWAP 偏離",), size=Pt(15), bold=True, line=1.35, space_after=Pt(2),
                 color=W.WHITE)
    W._rich_para(tf.add_paragraph(),
                 f"{r['vwap_n']} 筆都在月線上方（中位 {r['vwap_dist_median']:+.1%}），"
                 f"其中 {r['vwap_ma20_below_ma60']} 筆是 20 日線仍在 60 日線下",
                 (), size=Pt(12.5), line=1.35, space_after=Pt(0), color=W.MUTED)

    # ── 重點條
    W._card(s, (Inches(0.34), Inches(8.08), Inches(5.52), Inches(1.62)), alpha=26,
            fill=RGBColor(0x2A, 0x10, 0x10))
    W._accent_bar(s, Inches(0.44), Inches(8.22), Inches(0.055), Inches(1.34))
    box, tf = W._textbox(s, Inches(0.76), Inches(8.24), Inches(4.86), Inches(1.30),
                         anchor=MSO_ANCHOR.MIDDLE)
    W._rich_para(tf.paragraphs[0], "逆勢不是猜低點，是「趨勢條件不成立」後的補位。",
                 ("不是猜低點",), size=Pt(17), bold=True, line=1.45, space_after=Pt(0),
                 color=W.WHITE)
    W._notes(s, 35, [
        "順勢的判法是三條全綠：收盤價高於 20 日均線、20 日均線高於 60 日均線、20 日動能為正；"
        f"三條全綠 {r['trend_n']} 筆，其中突破 {r['breakout_n']} 筆、均線交叉 {r['ma_cross_n']} 筆。",
        f"只要有一條不成立就走逆勢 {r['regime_n']} 筆：跌破 20 日線就買低（布林回歸 {r['bollinger_n']} 筆），"
        f"站在 20 日線上方但 20 日線還在 60 日線下面就用 VWAP 偏離（{r['vwap_n']} 筆）。",
    ], [])
    W._page_no(s, page, total)


# ── 版面 ──────────────────────────────────────────────────────────────
def build_deck(st: dict) -> Path:
    from pptx import Presentation

    prs = Presentation()
    prs.slide_width, prs.slide_height = W.SLIDE_W, W.SLIDE_H
    bgs = {
        1: W.background("cm1", 101, glow_xy=(0.35, 0.26), glow_r=0.75, glow_s=0.20, candles=False),
        2: W.background("cm2", 113, glow_xy=(0.85, 0.18), glow_s=0.14, candles=False),
        3: W.background("cm3", 127, glow_xy=(0.12, 0.24), glow_s=0.14, candles=False),
        4: W.background("cm4", 139, glow_xy=(0.55, 0.16), glow_s=0.13, candles=False),
        5: W.background("cm5", 151, glow_xy=(0.50, 0.90), glow_r=0.9, glow_s=0.16, candles=False),
        6: W.background("cm6", 163, glow_xy=(0.85, 0.86), glow_s=0.15, candles=False),
    }
    top_share = st["tier_share"]

    # ① 封面 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[1])
    W._accent_bar(s, Inches(2.71), Inches(3.05))
    box, tf = W._textbox(s, MARGIN, Inches(3.42), CONTENT_W, Inches(2.6))
    W._rich_para(tf.paragraphs[0], "我們的選股", size=Pt(36), bold=True,
                 align=PP_ALIGN.CENTER, line=1.38, space_after=Pt(0))
    W._rich_para(tf.add_paragraph(), "都是哪些股票？", ("哪些股票",), size=Pt(36), bold=True,
                 align=PP_ALIGN.CENTER, line=1.38, space_after=Pt(0))
    box, tf = W._textbox(s, MARGIN, Inches(6.30), CONTENT_W, Inches(0.9))
    W._rich_para(tf.paragraphs[0], "2022-01 ～ 2026-10 回測｜實盤口徑", size=Pt(15),
                 align=PP_ALIGN.CENTER, line=1.4, space_after=Pt(0), color=W.MUTED)

    # 三個大數字
    cards = (("大型股", f"{top_share['大型股']:.0%}", W.ACCENT),
             ("中型股", f"{top_share['中型股']:.0%}", W.SLATE),
             ("小型股", f"{top_share['小型股']:.0%}", W.MUTED))
    x = Inches(0.46)
    for label, val, color in cards:
        W._card(s, (x, Inches(7.60), Inches(1.60), Inches(1.62)), alpha=70)
        box, tf = W._textbox(s, x, Inches(7.78), Inches(1.60), Inches(1.26),
                             anchor=MSO_ANCHOR.MIDDLE)
        W._rich_para(tf.paragraphs[0], val, size=Pt(27), bold=True, color=color,
                     align=PP_ALIGN.CENTER, line=1.1, space_after=Pt(2))
        W._rich_para(tf.add_paragraph(), label, size=Pt(12), align=PP_ALIGN.CENTER,
                     line=1.2, space_after=Pt(0), color=W.SOFT)
        x += Inches(1.755)
    box, tf = W._textbox(s, MARGIN, Inches(9.55), CONTENT_W, Inches(0.6))
    W._rich_para(tf.paragraphs[0], f"{st['n']} 筆選股／{st['months']} 次選股日／{st['unique_sids']} 檔個股",
                 size=Pt(12.5), align=PP_ALIGN.CENTER, color=W.MUTED, space_after=Pt(0))
    W._notes(s, 20, [f"2022 年到現在的回測，我們一共選了 {st['n']} 筆、{st['unique_sids']} 檔股票。"
                     f"其中大型股 {top_share['大型股']:.0%}、中型股 {top_share['中型股']:.0%}。"], [])
    W._page_no(s, 1, 6)

    # ② 分級占比 -------------------------------------------------------
    s = W._bg_slide(prs, bgs[2])
    box, tf = W._textbox(s, MARGIN, Inches(1.10), CONTENT_W, Inches(1.2))
    W._rich_para(tf.paragraphs[0], "選股落在哪一級？", ("哪一級",), size=Pt(25), bold=True,
                 line=1.35, space_after=Pt(0))
    W._card(s, (Inches(0.34), Inches(2.42), Inches(5.52), Inches(4.10)), alpha=76)
    pic = s.shapes.add_picture(str(donut_png(st)), Inches(0.46), Inches(2.62), width=Inches(5.28))
    pic.line.fill.background()
    box, tf = W._textbox(s, MARGIN, Inches(6.78), CONTENT_W, Inches(2.6))
    W._rich_para(tf.paragraphs[0], TIER_RULE_LINE(st), size=Pt(14), line=1.5,
                 color=W.SOFT, space_after=Pt(10))
    W._rich_para(tf.add_paragraph(), "選股池＝每季市值前 100 名 ⇒ 151 名以後的小型股本來就買不到。",
                 ("小型股本來就買不到",), size=Pt(14), line=1.5, color=W.SOFT)
    W._notes(s, 25, [f"分級規則：{st['tier_rule']}。",
                     f"結果是大型股 {top_share['大型股']:.0%}、中型股 {top_share['中型股']:.0%}、"
                     f"小型股 {top_share['小型股']:.0%}。"], [])
    W._page_no(s, 2, 6)

    # ③ 各級別 × 策略 --------------------------------------------------
    s = W._bg_slide(prs, bgs[3])
    box, tf = W._textbox(s, MARGIN, Inches(1.10), CONTENT_W, Inches(1.2))
    W._rich_para(tf.paragraphs[0], "各級別用哪些策略？", ("哪些策略",), size=Pt(25), bold=True,
                 line=1.35, space_after=Pt(0))
    W._card(s, (Inches(0.34), Inches(2.30), Inches(5.52), Inches(4.30)), alpha=76)
    pic = s.shapes.add_picture(str(strat_png(st)), Inches(0.44), Inches(2.52), width=Inches(5.32))
    pic.line.fill.background()
    side = st["side_share_all"]
    W._card(s, (Inches(0.34), Inches(6.84), Inches(5.52), Inches(1.90)), alpha=26,
            fill=RGBColor(0x2A, 0x10, 0x10))
    W._accent_bar(s, Inches(0.44), Inches(7.00), Inches(0.055), Inches(1.58))
    box, tf = W._textbox(s, Inches(0.76), Inches(7.02), Inches(4.86), Inches(1.54),
                         anchor=MSO_ANCHOR.MIDDLE)
    W._rich_para(tf.paragraphs[0], f"全體：順勢 {side['順勢']:.0%}／回歸 {side['回歸']:.0%}",
                 ("順勢",), size=Pt(19), bold=True, line=1.35, space_after=Pt(6), color=W.WHITE)
    W._rich_para(tf.add_paragraph(), "大、中型的策略偏好幾乎一樣：都是突破為主。",
                 ("幾乎一樣",), size=Pt(15), line=1.4, space_after=Pt(0), color=W.WHITE)
    W._notes(s, 30, [f"策略是依個股型態路由。全體順勢 {side['順勢']:.0%}、回歸 {side['回歸']:.0%}；"
                     f"大型股順勢 {st['tier_x_side']['大型股']['順勢']:.0%}、"
                     f"中型股順勢 {st['tier_x_side']['中型股']['順勢']:.0%}。"], [])
    W._page_no(s, 3, 6)

    # ④ 逆勢怎麼被挑到 -------------------------------------------------
    _route_page(prs, bgs[5], st, 4, 6)

    # ⑤ 逐年 ----------------------------------------------------------
    s = W._bg_slide(prs, bgs[4])
    box, tf = W._textbox(s, MARGIN, Inches(1.10), CONTENT_W, Inches(1.2))
    W._rich_para(tf.paragraphs[0], "逐年有沒有變？", ("變",), size=Pt(25), bold=True,
                 line=1.35, space_after=Pt(0))
    W._card(s, (Inches(0.34), Inches(2.30), Inches(5.52), Inches(3.70)), alpha=76)
    pic = s.shapes.add_picture(str(yearly_png(st)), Inches(0.44), Inches(2.50), width=Inches(5.32))
    pic.line.fill.background()
    yts = st["year_tier_share"]
    box, tf = W._textbox(s, MARGIN, Inches(6.34), CONTENT_W, Inches(2.9))
    W._rich_para(tf.paragraphs[0], f"2024 年最偏大型股（{yts['2024']['大型股']:.0%}），"
                                   f"2023 年最平均（{yts['2023']['大型股']:.0%}）",
                 (), size=Pt(15), line=1.5, color=W.SOFT, space_after=Pt(10))
    W._rich_para(tf.add_paragraph(), "沒有一年選到小型股 —— 限制來自選股池，不是策略偏好。",
                 ("不是策略偏好",), size=Pt(15), line=1.5, color=W.SOFT)
    W._notes(s, 20, ["逐年看，大型股占比在 "
                     + "、".join(f"{y} {v['大型股']:.0%}" for y, v in yts.items())
                     + " 之間，沒有任何一年選到小型股。"], [])
    W._page_no(s, 5, 6)

    # ⑥ 口徑與限制 -----------------------------------------------------
    s = W._bg_slide(prs, bgs[6])
    W._card(s, (Inches(0.34), Inches(1.30), Inches(5.52), Inches(7.40)), alpha=76)
    box, tf = W._textbox(s, MARGIN, Inches(1.62), CONTENT_W, Inches(0.6))
    W._rich_para(tf.paragraphs[0], "這張圖是怎麼算的", ("怎麼算",), size=Pt(21), bold=True,
                 line=1.35, space_after=Pt(0))
    box, tf = W._textbox(s, MARGIN, Inches(2.30), CONTENT_W, Inches(6.1))
    lines = [
        f"期間 {st['window']}，選股 {st['months']} 次（跳過 {st['skipped_months']} 次）、{st['n']} 筆。",
        "口徑：實盤路徑 —— 池 100＋營收因子、過熱過濾開、型態路由（form）。",
        f"分級：{st['tier_rule']}（用歷史股本×當期收盤算全宇宙排名）。",
        "策略：突破／均線交叉（順勢）、布林回歸／VWAP（回歸），只用選股日之前的資料。",
        "限制：市值用權還原價、只涵蓋快取宇宙 672 檔；集中度只代表這 5 年、不是保證。",
    ]
    for i, line in enumerate(lines):
        p = tf.add_paragraph() if i else tf.paragraphs[0]
        W._rich_para(p, line, (), size=Pt(13.5), line=1.62, space_after=Pt(10), color=W.SOFT)
    W._notes(s, 25, [f"口徑：{st['window']}，實盤路徑（池 100＋營收因子、過熱過濾、型態路由），"
                     f"分級規則 {st['tier_rule']}。"], [])
    W._page_no(s, 6, 6)

    prs.save(OUT)
    return OUT


def TIER_RULE_LINE(st: dict) -> str:
    med = st["tier_cap_median_yi"]
    big = f"（中位數 {med['大型股']:.0f} 億）" if med.get("大型股") else ""
    mid = f"（中位數 {med['中型股']:.0f} 億）" if med.get("中型股") else ""
    return (f"大型＝市值前 50 名{big}、中型＝51～150 名{mid}、小型＝151 名以後。")
