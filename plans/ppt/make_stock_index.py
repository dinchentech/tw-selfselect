#!/usr/bin/env python3
"""make_stock_index.py · 「常見股票指標」直式 9:16 五頁（年化／本益比／回撤／夏普）

沿用 `make_why_design.py` 的視覺語言（深藍黑漸層背景、紅色重點、6.20×11.02 吋直式），
四張示意圖用 matplotlib 現畫 ⇒ 沒有外部圖檔、沒有版權問題、可重複產生
（中間產物放 `TMP/whybuild/`，與 why_design 共用）。

文字：使用者手稿**逐字保留**（年化／本益比／回撤／夏普 的定義與高低情境），
只做三件事：①加上現畫示意圖 ②把長段落拆成「定義卡＋重點列＋結論卡」
③把各頁備註改成 `plans/ppt/notes_to_script.py` 吃得下的講稿格式
（`⏱ 建議時間：`＋旁白段落＋`【講師提示】`）⇒ 可直接接 `generate_narration.sh build` 配音。

重跑：
    MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_stock_index.py
預覽：
    HOME=$PWD/TMP/lohome soffice -env:UserInstallation=file://$PWD/TMP/lohome/lo \\
        --headless --convert-to pdf --outdir TMP/x plans/ppt/stock_index/stock_index.pptx
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

import numpy as np                                    # noqa: E402
from pptx import Presentation                         # noqa: E402
from pptx.dml.color import RGBColor                   # noqa: E402
from pptx.enum.shapes import MSO_SHAPE               # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN       # noqa: E402
from pptx.util import Inches, Pt                      # noqa: E402

import make_why_design as W                           # noqa: E402  共用視覺元件
from why_icons import icon as draw_icon               # noqa: E402

OUT = Path(ROOT / "plans/ppt/stock_index/stock_index.pptx")
TOTAL = 6
MARGIN, CONTENT_W = W.MARGIN, W.CONTENT_W

AMBER = RGBColor(0xF0, 0xA6, 0x3C)
BLUE = RGBColor(0x4C, 0x8F, 0xD1)
GREEN = RGBColor(0x4F, 0xC3, 0x8A)

# 圖幅＝投影片上的實際吋數 ⇒ 圖裡的 pt 就等於看得到的 pt
CHART_W, CHART_H = 5.22, 3.40


def _hex(rgb: RGBColor) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _fonts():
    from matplotlib import font_manager as fm
    import matplotlib.pyplot as plt

    reg, bold = W._cjk_fonts()
    fm.fontManager.addfont(str(reg))
    fm.fontManager.addfont(str(bold))
    # 刻度標籤（格式化字串）走 rcParams ⇒ 也要指定 CJK，否則「年」會缺字
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "DejaVu Sans"]
    return fm.FontProperties(fname=str(reg)), fm.FontProperties(fname=str(bold))


def _fig():
    from matplotlib import pyplot as plt

    fig = plt.figure(figsize=(CHART_W, CHART_H), dpi=220)
    fig.patch.set_alpha(0.0)
    return fig


def _bare(ax):
    ax.set_facecolor("none")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_hex(RGBColor(0x2C, 0x4B, 0x74)))
        ax.spines[side].set_linewidth(0.9)
    ax.tick_params(colors=_hex(W.MUTED), labelsize=13, length=0)
    ax.grid(True, color=_hex(RGBColor(0x2C, 0x4B, 0x74)), lw=0.6, ls=(0, (2, 4)), alpha=0.55)
    ax.set_axisbelow(True)


# ── 圖 ①：年化＝複利（同樣 10 年，5% / 20% / 40% 的倍數差）────────────────
def cagr_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    path = W.BUILD / "si_cagr.png"
    fig = _fig()
    ax = fig.add_axes([0.145, 0.150, 0.815, 0.825])
    _bare(ax)
    ax.set_yscale("log")

    years = np.arange(0, 11)
    rows = ((0.05, W.MUTED, "5%"), (0.20, W.ACCENT, "20%"), (0.40, AMBER, "40%"))
    for rate, color, label in rows:
        mult = (1 + rate) ** years
        ax.plot(years, mult, color=_hex(color), lw=2.6, solid_capstyle="round")
        ax.scatter([10], [mult[-1]], s=40, color=_hex(color), zorder=5)
        ax.annotate(f"{label} ⇒ ×{mult[-1]:.1f}", (10, mult[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", ha="left",
                    fontproperties=bold, fontsize=14, color=_hex(color))

    ax.set_xlim(-0.3, 16.4)
    ax.set_ylim(0.9, 42)
    ax.set_xticks(range(0, 11, 2))
    ax.set_yticks([1, 2, 5, 10, 20, 30])
    ax.set_yticklabels([f"×{v}" for v in (1, 2, 5, 10, 20, 30)])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)} 年"))

    fig.text(0.145, 0.040, "年化 =（期末 ÷ 期初）^(1 ÷ 年數) − 1",
             fontproperties=reg, fontsize=11.5, color=_hex(W.SOFT))
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖 ②：本益比＝市場願意給幾倍獲利（EPS 5 元固定，股價 50 vs 150）────────
def pe_png() -> Path:
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    reg, bold = _fonts()
    path = W.BUILD / "si_pe.png"
    fig = _fig()
    ax = fig.add_axes([0.05, 0.12, 0.93, 0.76])
    ax.set_facecolor("none")
    ax.axis("off")
    ax.set_xlim(0, 216)
    ax.set_ylim(-0.70, 2.30)

    bars = ((1, 5, 50, "10 倍", W.SLATE), (0, 5, 150, "30 倍", W.ACCENT))
    for y, eps, price, mul, color in bars:
        ax.add_patch(Rectangle((0, y - 0.20), eps, 0.40, facecolor=_hex(GREEN),
                               edgecolor="#EAF6EF", linewidth=1.2, alpha=0.92))
        ax.add_patch(Rectangle((eps, y - 0.20), price - eps, 0.40, facecolor=_hex(color),
                               edgecolor="none", alpha=0.30 if color is W.ACCENT else 0.22))
        ax.plot([0, price], [y, y], color=_hex(color), lw=2.4, solid_capstyle="butt")
        ax.text(price + 4, y, f"股價 {price} 元", va="center", ha="left",
                fontproperties=bold, fontsize=16, color=_hex(W.TEXT))
        ax.text(eps + 8, y + 0.24, f"本益比 {mul}", va="bottom", ha="left",
                fontproperties=bold, fontsize=15, color=_hex(color))

    ax.annotate("", xy=(5, 2.10), xytext=(-9, 2.10),
                arrowprops=dict(arrowstyle="-|>", color=_hex(GREEN), lw=1.6))
    ax.text(8, 2.14, "綠＝公司真的賺到的（EPS 5 元）　紅／灰＝市場多付的倍數",
            va="bottom", ha="left", fontproperties=reg, fontsize=11.5, color=_hex(W.SOFT))
    fig.text(0.05, 0.030, "同一檔股票、每年都賺 5 元；價格差 3 倍",
             fontproperties=reg, fontsize=11.5, color=_hex(W.SOFT))
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖 ③：回撤＝從峰值掉多少（上：淨值＋峰值線；下：水下曲線）──────────────
def drawdown_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    path = W.BUILD / "si_dd.png"

    rng = np.random.default_rng(7)
    n = 260
    step = rng.normal(0.0022, 0.0125, n)
    step[118:168] = rng.normal(-0.0092, 0.011, 50)      # 一段像樣的空頭，讓最大回撤看得見
    eq = 1_000_000 * np.cumprod(1 + step)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1
    t = np.arange(n) / 12                               # 約 21 個月
    i_peak = int(np.argmax(peak * (dd == dd.min())))     # 回撤最深的當下
    i_trough = int(np.argmin(dd))
    mdd = float(dd.min())

    fig = _fig()
    ax = fig.add_axes([0.185, 0.455, 0.775, 0.485])
    _bare(ax)
    ax.plot(t, eq / 1e4, color=_hex(W.TEXT), lw=1.9)
    ax.plot(t, peak / 1e4, color=_hex(W.MUTED), lw=1.2, ls=(0, (3, 3)))
    ax.fill_between(t, eq / 1e4, peak / 1e4, color=_hex(W.ACCENT), alpha=0.16, lw=0)
    ax.axvline(t[i_trough], color=_hex(W.ACCENT), lw=0.9, ls=(0, (2, 3)), alpha=0.7)
    ax.set_xticks([])
    ax.set_ylabel("淨值（萬元）", fontproperties=reg, fontsize=12.5, color=_hex(W.MUTED), labelpad=4)
    ax.text(t[i_peak], peak[i_peak] / 1e4, "  歷史峰值", va="bottom", ha="left",
            fontproperties=reg, fontsize=12, color=_hex(W.MUTED))

    ax2 = fig.add_axes([0.185, 0.175, 0.775, 0.225], sharex=ax)
    _bare(ax2)
    ax2.fill_between(t, 0, dd * 100, color=_hex(W.ACCENT), alpha=0.30, lw=0)
    ax2.plot(t, dd * 100, color=_hex(W.ACCENT), lw=1.6)
    ax2.scatter([t[i_trough]], [mdd * 100], s=34, color=_hex(W.ACCENT), zorder=5)
    ax2.annotate(f"最大回撤 −{abs(mdd) * 100:.0f}%", (t[i_trough], mdd * 100),
                 xytext=(1.4, mdd * 100 * 1.34), textcoords="data", va="center", ha="left",
                 arrowprops=dict(arrowstyle="-", color=_hex(W.ACCENT), lw=0.9,
                                 shrinkA=2, shrinkB=4, alpha=0.75),
                 fontproperties=bold, fontsize=16, color=_hex(W.ACCENT))
    ax2.axhline(0, color=_hex(RGBColor(0x2C, 0x4B, 0x74)), lw=0.8)
    ax2.set_ylim(mdd * 100 * 1.55, mdd * 100 * -0.10)
    ax2.set_yticks([0, -20, -40])
    ax2.set_yticklabels(["0%", "−20%", "−40%"])
    ax2.set_xlabel("時間（月）", fontproperties=reg, fontsize=11.5, color=_hex(W.MUTED), labelpad=1)
    ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}"))

    fig.text(0.185, 0.022, "回撤 =（歷史峰值 − 當前淨值）÷ 歷史峰值 × 100%",
             fontproperties=reg, fontsize=11.5, color=_hex(W.SOFT))
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖 ④：夏普＝風險報酬圖上的斜率（超額報酬 ÷ 波動）─────────────────────
def sharpe_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = _fonts()
    path = W.BUILD / "si_sharpe.png"
    fig = _fig()
    ax = fig.add_axes([0.185, 0.215, 0.775, 0.765])
    _bare(ax)
    ax.set_xlim(0, 30)
    ax.set_ylim(0, 20)

    # (夏普, 顏色, 標籤, 標籤位置, 對齊)；0.5 那條貼右邊界 ⇒ 標籤往左長才不會被切掉
    for sr, color, label, anchor, ha, va in (
            (2.0, GREEN, "SR 2.0", (9.2, 18.4), "left", "top"),
            (1.0, BLUE, "SR 1.0", (18.4, 18.4), "left", "top"),
            (0.5, W.MUTED, "SR 0.5", (28.6, 14.3), "right", "bottom")):
        x_end = min(29.4, 18.4 / sr)
        ax.plot([0, x_end], [0, sr * x_end], color=_hex(color), lw=1.2, ls=(0, (3, 4)),
                alpha=0.85)
        ax.annotate(label, anchor, xytext=(0, 0), textcoords="offset points",
                    ha=ha, va=va, fontproperties=reg, fontsize=13, color=_hex(color))

    pts = ((15, 8, W.ACCENT, "A：波動 15%、超額 8%\n　　　⇒ 夏普 0.53", (16.2, 12.4)),
           (8, 8, BLUE, "B：波動 8%、超額 8%\n　　　⇒ 夏普 1.00", (11.0, 2.6)))
    for sig, exc, color, label, xytext in pts:
        ax.scatter([sig], [exc], s=70, color=_hex(color), zorder=6,
                   edgecolor=_hex(RGBColor(0x06, 0x0E, 0x1A)), linewidth=1.4)
        ax.annotate(label, (sig, exc), xytext=xytext, textcoords="data",
                    arrowprops=dict(arrowstyle="-", color=_hex(color), lw=0.9,
                                    shrinkA=0, shrinkB=6), fontproperties=bold,
                    fontsize=12.5, color=_hex(color), va="center", linespacing=1.45)

    ax.set_xticks([0, 5, 10, 15, 20, 25, 30])
    ax.set_yticks([0, 5, 10, 15, 20])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.set_xlabel("報酬率標準差（波動）", fontproperties=reg, fontsize=12.5,
                  color=_hex(W.MUTED), labelpad=4)
    ax.set_ylabel("超額報酬", fontproperties=reg, fontsize=12.5, color=_hex(W.MUTED), labelpad=4)

    fig.text(0.185, 0.030, "同一條虛線＝同樣的夏普：斜率越陡，換到的超額報酬越多",
             fontproperties=reg, fontsize=11.5, color=_hex(W.SOFT))
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 版面元件 ──────────────────────────────────────────────────────────
def _card_text(slide, box, text, *, size=Pt(16.5), phrase_marks=(), label=None,
               line=1.40):
    """定義卡：淡底圓角卡＋說明（text 可傳字串或字串清單＝多段；label 是左上角小紅字）。"""
    paras = [text] if isinstance(text, str) else list(text)
    left, top, w, h = box
    W._card(slide, box, alpha=70)
    inner_top = top
    if label:
        _b, tf = W._textbox(slide, left + Inches(0.24), top + Inches(0.16),
                            w - Inches(0.48), Inches(0.26))
        W._rich_para(tf.paragraphs[0], label, (label,), size=Pt(11), bold=True,
                     line=1.0, space_after=Pt(0), color=W.ACCENT)
        inner_top = top + Inches(0.46)
    _b, tf = W._textbox(slide, left + Inches(0.24), inner_top,
                        w - Inches(0.48), h - (inner_top - top) - Inches(0.16),
                        anchor=MSO_ANCHOR.MIDDLE if label is None else MSO_ANCHOR.TOP)
    for i, para_text in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        W._rich_para(para, para_text, phrase_marks, size=size, line=line, space_after=Pt(4))


def _callout(slide, box, lines, marks=(), *, size=Pt(16), accent=W.ACCENT):
    """結論卡：深紅底＋左側紅粗條（lines 可一或多段）。"""
    if isinstance(lines, str):
        lines = [lines]
    left, top, w, h = box
    W._card(slide, box, alpha=26, fill=RGBColor(0x2A, 0x10, 0x10))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.10),
                                 top + Inches(0.14), Inches(0.055), h - Inches(0.28))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False
    _b, tf = W._textbox(slide, left + Inches(0.34), top + Inches(0.10),
                        w - Inches(0.52), h - Inches(0.20), anchor=MSO_ANCHOR.MIDDLE)
    for i, text in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        W._rich_para(para, text, marks, size=size if i == 0 else size - Pt(1),
                     bold=False, line=1.36, space_after=Pt(2),
                     color=W.WHITE, mark_color=accent)


def _calc_card(slide, box):
    """夏普計算例：① 三個輸入 ② 算式與結果 ③ 白話結論（每個數字都標了來源）。"""
    left, top, w, h = box
    W._card(slide, box, alpha=64)
    _b, tf = W._textbox(slide, left + Inches(0.24), top + Inches(0.14),
                        w - Inches(0.48), Inches(0.26))
    W._rich_para(tf.paragraphs[0], "計算例", ("計算例",), size=Pt(11), bold=True,
                 line=1.0, space_after=Pt(0), color=W.ACCENT)
    _b, tf = W._textbox(slide, left + Inches(0.24), top + Inches(0.42),
                        w - Inches(0.48), Inches(0.30))
    W._rich_para(tf.paragraphs[0], P5_CALC_INPUTS, ("10%", "2%", "15%"), size=Pt(12.5),
                 line=1.0, space_after=Pt(0), color=W.SOFT)
    _b, tf = W._textbox(slide, left + Inches(0.24), top + Inches(0.74),
                        w - Inches(0.48), Inches(0.36))
    W._rich_para(tf.paragraphs[0], P5_CALC_LINE, ("0.53",), size=Pt(17), bold=True,
                 line=1.0, space_after=Pt(0))
    _b, tf = W._textbox(slide, left + Inches(0.24), top + Inches(1.12),
                        w - Inches(0.48), Inches(0.28))
    W._rich_para(tf.paragraphs[0], P5_CALC_NOTE, ("0.53",), size=Pt(12), line=1.0,
                 space_after=Pt(0), color=W.MUTED)


def _chips(slide, box, items):
    """橫排等級籤（夏普等級）。"""
    left, top, w, h = box
    gap = Inches(0.12)
    cw = int((w - gap * (len(items) - 1)) / len(items))
    for i, (head, sub, color) in enumerate(items):
        x = left + (cw + gap) * i
        W._card(slide, (x, top, cw, h), alpha=52, fill=RGBColor(0x0E, 0x1C, 0x30))
        _b, tf = W._textbox(slide, x, top + Inches(0.14), cw, Inches(0.34))
        W._rich_para(tf.paragraphs[0], head, (head,), size=Pt(15.5), bold=True,
                     align=PP_ALIGN.CENTER, line=1.0, space_after=Pt(0), mark_color=color)
        _b, tf = W._textbox(slide, x, top + Inches(0.52), cw, Inches(0.30))
        W._rich_para(tf.paragraphs[0], sub, (), size=Pt(11.5), align=PP_ALIGN.CENTER,
                     line=1.0, space_after=Pt(0), color=W.MUTED)


def _icon_row(slide, box, rows, *, size=Pt(18.5), row_gap=0.30, icon_in=0.50):
    W._icon_rows(slide, rows, box=box, size=size, row_gap=row_gap, icon_in=icon_in,
                 icon_gap=0.14)


def _title(slide, title, sub, *, marks=()):
    _b, tf = W._textbox(slide, MARGIN, Inches(0.72), CONTENT_W, Inches(0.62))
    W._rich_para(tf.paragraphs[0], title, marks, size=Pt(31), bold=True, line=1.0,
                 space_after=Pt(0), mark_color=W.ACCENT)
    _b, tf = W._textbox(slide, MARGIN, Inches(1.36), CONTENT_W, Inches(0.34))
    W._rich_para(tf.paragraphs[0], sub, (sub,), size=Pt(13), bold=True, line=1.0,
                 space_after=Pt(0), color=W.MUTED, mark_color=RGBColor(0xFF, 0x8A, 0x7D))
    W._accent_bar(slide, MARGIN, Inches(1.26), Inches(0.62), Inches(0.055))


def _chart(slide, png, *, top=Inches(1.86)):
    W._card(slide, (Inches(0.34), top, Inches(5.52), Inches(3.78)), alpha=74)
    pic = slide.shapes.add_picture(str(png), Inches(0.49), top + Inches(0.14),
                                   width=Inches(CHART_W))
    pic.line.fill.background()


def _notes(slide, seconds: int, body: list[str], tip: str = "") -> None:
    """備註＝講稿（`notes_to_script.py` 吃 `⏱ 建議時間：`；【講師提示】配音時會被剝掉）。"""
    lines = [f"⏱ 建議時間：{seconds} 秒", ""]
    lines += [p for p in body if p.strip()]
    if tip:
        lines += ["", f"【講師提示】{tip}"]
    slide.notes_slide.notes_text_frame.text = "\n".join(lines)


# ── 內容（使用者手稿逐字；`marks` 是要上紅色的詞）─────────────────────────
COVER_TITLE = "常見股票指標"
COVER_SUB = "年化，本益比，回撤，夏普"

P2_DEF = ("這是評估股票投資表現最常見的指標。它將投資一段期間（不論是幾個月或好幾年）的總報酬率，"
          "扣除時間因素後，換算成每年的平均複利回報率。")
P2_ROWS = [("percent", "一般 ETF 大盤年化約在 20% 左右", ("20%",)),
           ("arrow_up", "主動式基金年化可以高達 30~40%", ("30~40%",))]
P2_CALL = ["同樣 10 年：年化 20% ⇒ ×6.2", "年化 40% ⇒ ×28.9　（終值差 4.7 倍）"]

P3_DEF = ["本益比 = 股價 ÷ 每股盈餘（EPS）", "或 = 公司市值 ÷ 稅後淨利"]
P3_ROWS = [("arrow_up", "高：可能代表市場預期未來成長高，也可能股價偏貴。", ("偏貴",)),
           ("valley", "低：可能是便宜，也可能是產業衰退、獲利不穩。", ("衰退",))]
P3_CALL = ["同一檔每年都賺 5 元：", "市場給 10 倍＝50 元、給 30 倍＝150 元"]

P4_DEF = ("指資產淨值或策略淨值，從截至當時的歷史最高點（峰值）下跌到當前位置的幅度。"
          "回撤 =（歷史峰值 − 當前淨值）÷ 歷史峰值 × 100%")
P4_ROWS = [("valley", "最大回撤：指整個回測期間內，所有回撤中最大的一次。", ("最大的一次",)),
           ("warn", "即從某個峰值，跌到之後谷底的最大跌幅。", ("谷底",))]
P4_CALL = ["回撤 30% ⇒ 要漲 42.9% 才回本", "回撤 50% ⇒ 要漲 100% 才回本"]

P5_DEF = ["SR =（R_p − R_f）÷ σ_p",
          "夏普比率 =（投資組合報酬率 − 無風險利率）÷ 報酬率標準差"]
P5_CALC_INPUTS = "投資組合報酬 10%、無風險利率 2%、報酬率標準差 15%"
P5_CALC_LINE = "SR =（10% − 2%）÷ 15% = 0.53"
P5_CALC_NOTE = "每多承擔 1 單位波動風險，約換得 0.53 單位超額報酬"
P5_CHIPS = [("> 2.0", "優秀", GREEN), ("1.0 ~ 2.0", "良好", BLUE), ("0.5 ~ 1.0", "可接受", W.MUTED)]

# 第 6 頁：原稿那四點（原本被拖在畫布外，x 為負值）
P6_ROWS = [
    ("coins", "內扣費用（經理費、保管費）比 ETF 貴很多", ("貴很多",)),
    ("person", "「高淨值」帶來的心理恐懼 (700~800)", ("心理恐懼",)),
    ("warn", "風險高度集中，且「空頭來臨時經理人無法空手」", ("無法空手",)),
    ("scale", "規模太大造成的「大象轉身困難」", ("大象轉身困難",)),
]
P6_CALL = ["年化只算「報酬」——費用、心理、集中度、規模", "都不進公式，但會進你的帳戶。"]

SECONDS = {1: 12, 2: 32, 3: 34, 4: 28, 5: 32, 6: 33}

SPOKEN = {
    1: ["四個指標：年化、本益比、回撤、夏普。",
        "這一節就用它們，判斷股票貴不貴、策略好不好。"],
    2: ["先講年化。年化不是一年多賺多少，是把總報酬換算成每年的複利。",
        "三個月賺 50% 跟十年賺 50%，完全是兩件事。",
        "同樣一筆錢放十年：5% 變 1.6 倍、20% 變 6.2 倍、40% 變 28.9 倍。",
        "複利到後面，差的是倍數，不是趴數。"],
    3: ["本益比是股價除以每股盈餘，也就是市場願意用幾倍獲利買它。",
        "同一檔每年都賺 5 元：股價 50 元是 10 倍，股價 150 元是 30 倍。",
        "倍數高，可能是看好成長，也可能是偏貴；倍數低，可能是便宜，也可能在衰退。",
        "它只說市場給幾倍，沒說該不該買。"],
    4: ["回撤是從歷史最高點掉到現在，掉了多少。最大回撤，就是最痛的那一次。",
        "回撤 30%，要漲 42.9% 才回本；回撤 50%，要漲 100% 才回本。",
        "很多策略不是報酬不夠，是回撤太深，人在最低點就砍掉了。"],
    5: ["夏普問的是：為了這個報酬，你承受了多少波動。",
        "報酬 10%、無風險利率 2%，超額 8%；除以 15% 的波動，夏普 0.53。",
        "同樣 8% 的超額報酬：波動砍半，夏普就變 1.00。",
        "分級：0.5 到 1 可接受，1 到 2 良好，超過 2 優秀。"],
    6: ["主動式基金 30 到 40%，我拿安聯當例子，但要先算四個代價。",
        "內扣費用每年扣，比 ETF 貴很多；高淨值帶來的心理恐懼；",
        "風險集中，空頭來時經理人不能空手；規模太大，大象轉身困難。",
        "所以看到 40%，先問一句：扣掉這些，我還剩多少。"],
}
TIPS = {
    2: "一般 ETF 大盤年化約 20% 是使用者的經驗值；我們專案近年回測年化 +32.23%，但那是回測、不是保證。",
    4: "我們這一版：近四年回測最大回撤 −33.4%，長期回測 −53%～−57%，2022 單年 −24%。"
       "真錢上線前，先確認自己承受得住（README 的提醒）。",
    5: "我們目前版本（停泊 0050 口徑、2022-01～2026-10）夏普 1.18、0050 是 1.21 ⇒ 打平；"
       "所以我們的重點是總報酬更高，不是夏普贏 0050。",
    6: "安聯 40% 是使用者原稿的數字，本專案沒有查證；「每年扣 2%」是本頁的示意假設"
       "（台灣主動式基金內扣費用常見 1.5%～2.5%，實際要查公開說明書／年報的總費用率）。"
       "原稿註記的 (700~800) 指該基金單位淨值水位。",
}


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W.SLIDE_W, W.SLIDE_H

    bgs = {
        1: W.background("si_cover", 211, glow_xy=(0.42, 0.28), glow_r=0.72, glow_s=0.20),
        2: W.background("si_s2", 223, glow_xy=(0.86, 0.66), glow_s=0.14),
        3: W.background("si_s3", 237, glow_xy=(0.12, 0.70), glow_r=0.70, glow_s=0.14),
        4: W.background("si_s4", 251, glow_xy=(0.52, 0.66), glow_s=0.12, glow_r=0.62),
        5: W.background("si_s5", 263, glow_xy=(0.18, 0.42), glow_s=0.15, glow_r=0.70),
        6: W.background("si_s6", 277, glow_xy=(0.72, 0.20), glow_s=0.13, glow_r=0.66),
    }

    # ① 封面 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[1])
    W._accent_bar(s, Inches(2.71), Inches(6.62))
    _b, tf = W._textbox(s, MARGIN, Inches(6.98), CONTENT_W, Inches(2.20))
    W._rich_para(tf.paragraphs[0], COVER_TITLE, (COVER_TITLE,), size=Pt(34), bold=True,
                 align=PP_ALIGN.CENTER, line=1.34, space_after=Pt(6))
    W._rich_para(tf.add_paragraph(), COVER_SUB, (), size=Pt(27), bold=True,
                 align=PP_ALIGN.CENTER, line=1.34, space_after=Pt(0), color=W.WHITE)

    # 四個指標的圖示列（封面唯一的「圖案」）
    icons = ("percent", "divide", "valley", "gauge")
    tile, gap = 0.56, 0.52
    total_w = tile * len(icons) + gap * (len(icons) - 1)
    x0 = (6.2014 - total_w) / 2
    for i, name in enumerate(icons):
        pic = s.shapes.add_picture(str(draw_icon(name, W.BUILD / "icons", question_glyph=None)),
                                   Inches(x0 + i * (tile + gap)), Inches(9.42),
                                   width=Inches(tile), height=Inches(tile))
        pic.line.fill.background()
    _notes(s, SECONDS[1], SPOKEN[1],
           "四個指標由淺到深：年化講「複利」、回撤講「風險」、夏普講「風險調整後的報酬」、本益比講「貴不貴」。")
    W._page_no(s, 1, TOTAL)

    # ② 年化 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[2])
    _title(s, "年化", "CAGR・把總報酬換算成「每年複利」")
    _chart(s, cagr_png())
    _card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.58)), P2_DEF,
               label="定義", phrase_marks=("每年的平均複利回報率",))
    _icon_row(s, (MARGIN, Inches(7.34), CONTENT_W, Inches(1.52)), P2_ROWS)
    _callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P2_CALL,
             ("×6.2", "×28.9", "4.7 倍"))
    _notes(s, SECONDS[2], SPOKEN[2], TIPS[2])
    W._page_no(s, 2, TOTAL)

    # ③ 本益比 ---------------------------------------------------------
    s = W._bg_slide(prs, bgs[3])
    _title(s, "本益比", "P/E・市場願意用幾倍獲利買它")
    _chart(s, pe_png())
    _card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.30)), P3_DEF,
               label="定義", phrase_marks=("股價 ÷ 每股盈餘（EPS）",))
    _icon_row(s, (MARGIN, Inches(7.02), CONTENT_W, Inches(1.86)), P3_ROWS,
              size=Pt(17), row_gap=0.26)
    _callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P3_CALL,
             ("10 倍", "30 倍"))
    _notes(s, SECONDS[3], SPOKEN[3], "")
    W._page_no(s, 3, TOTAL)

    # ④ 回撤 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[4])
    _title(s, "回撤", "Drawdown・從歷史峰值掉了多少")
    _chart(s, drawdown_png())
    _card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.76)), P4_DEF,
               label="定義", phrase_marks=("歷史最高點（峰值）",))
    _icon_row(s, (MARGIN, Inches(7.52), CONTENT_W, Inches(1.34)), P4_ROWS,
              size=Pt(17))
    _callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P4_CALL,
             ("42.9%", "100%"))
    _notes(s, SECONDS[4], SPOKEN[4], TIPS[4])
    W._page_no(s, 4, TOTAL)

    # ⑤ 夏普 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[5])
    _title(s, "夏普比率", "Sharpe・每單位波動換到多少超額報酬")
    _chart(s, sharpe_png())
    _card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.58)), P5_DEF,
               label="定義", phrase_marks=("報酬率標準差",), size=Pt(15), line=1.34)
    _calc_card(s, (Inches(0.34), Inches(7.30), Inches(5.52), Inches(1.46)))
    _chips(s, (Inches(0.34), Inches(8.84), Inches(5.52), Inches(1.02)), P5_CHIPS)
    _notes(s, SECONDS[5], SPOKEN[5], TIPS[5])
    W._page_no(s, 5, TOTAL)

    # ⑥ 40%，但是（使用者原稿四點；原本被拖在畫布外）--------------------
    s = W._bg_slide(prs, bgs[6])
    _title(s, "40%，但是", "以安聯台灣科技基金為例・四個要一起算的代價", marks=("但是",))

    # 左上：40% 大字＋右側：費用的複利侵蝕（示意）
    W._card(s, (Inches(0.34), Inches(1.86), Inches(5.52), Inches(1.52)), alpha=70)
    _b, tf = W._textbox(s, Inches(0.56), Inches(1.94), Inches(1.95), Inches(0.86))
    W._rich_para(tf.paragraphs[0], "40%", ("40%",), size=Pt(46), bold=True, line=1.0,
                 space_after=Pt(0))
    _b, tf = W._textbox(s, Inches(0.56), Inches(2.90), Inches(2.10), Inches(0.30))
    W._rich_para(tf.paragraphs[0], "年化（過去績效）", (), size=Pt(12.5), line=1.0,
                 space_after=Pt(0), color=W.MUTED)
    divider = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(2.58), Inches(2.04),
                                 Inches(0.012), Inches(1.14))
    divider.fill.solid()
    divider.fill.fore_color.rgb = W.BORDER
    divider.line.fill.background()
    divider.shadow.inherit = False
    _b, tf = W._textbox(s, Inches(2.76), Inches(1.96), Inches(2.94), Inches(1.32))
    W._rich_para(tf.paragraphs[0], "每年扣 2% 內扣費用 ⇒", (), size=Pt(13), line=1.30,
                 space_after=Pt(3), color=W.SOFT)
    W._rich_para(tf.add_paragraph(), "十年終值 ×28.9 ⇒ ×25.1", ("×28.9", "×25.1"),
                 size=Pt(16), bold=True, line=1.30, space_after=Pt(3))
    W._rich_para(tf.add_paragraph(), "少 13%；費用每年扣，不是一次", (),
                 size=Pt(12), line=1.25, space_after=Pt(0), color=W.MUTED)

    _icon_row(s, (MARGIN, Inches(3.58), CONTENT_W, Inches(4.54)), P6_ROWS,
              size=Pt(17), row_gap=0.34)
    _callout(s, (Inches(0.34), Inches(8.62), Inches(5.52), Inches(1.18)), P6_CALL,
             ("報酬", "你的帳戶"))
    _notes(s, SECONDS[6], SPOKEN[6], TIPS[6])
    W._page_no(s, 6, TOTAL)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"✅ 產生 {path.relative_to(ROOT)}（{path.stat().st_size / 1024 / 1024:.2f} MB，{TOTAL} 頁）")
    print(f"   中間產物：{W.BUILD.relative_to(ROOT)}/（背景 ×5、示意圖 ×4、圖示）")
