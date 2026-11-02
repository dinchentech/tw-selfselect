#!/usr/bin/env python3
"""make_why_design.py · 產生 `plans/ppt/why_design.pptx`

主題：**為什麼我要開發這套股票系統**（6 頁、直式 9:16 短視頻用）。

1. 封面：為什麼我要開發這一套股票系統（晶片圖）
2. 動機（金幣／成長儀表圖）　3. 不懂投資但把系統做出來（AI 圖）
4. 第一次挫敗：40% 報酬、回撤也 40 幾%（成長柱狀圖）
5. 目前版本 vs 0050 的比較圖（2022-01～2026-10：獲利／最大回撤／夏普）
   ＋ 重點句：「贏 0050 不是重點，有合乎標準的股就選、沒有就停泊 0050 ⇒ 獲利最高」
6. 有了 AI 還要自己弄這套系統嗎（2026-07 開始實測的日曆圖）

做法：
  - **使用者提供的 5 張科技插畫**（`plans/ppt/why_design/*.jpg`）當每頁上半部的主視覺橫幅：
    置中裁切、壓暗、底部漸層淡出接回深色背景；第 5 頁不放圖，留給真數據比較圖。
  - 其餘版面由本檔產生（深藍黑漸層＋光暈＋線條圖示列）；背景與圖示都用 Pillow 現畫。
  - **畫面上只放重點字**：部分句子改成只有旁白（寫進備註，可交給 TTS），
    對照表是 `ONSCREEN`（上畫面）／`SPOKEN`（只講）。
  - 文字逐字沿用使用者原稿（只加強點字顏色，不改字）。
  - 數字口徑：停泊 0050 口徑、2022-01-01～2026-10-23，取自 README「回測」主表
    （目前版本 +283.1%／MDD −33.4%／夏普 1.18；0050 +231.4%／−34.0%／1.21）。

用法：
    .venv/bin/python plans/ppt/make_why_design.py            # 產生（覆寫 why_design.pptx）
    OUT=…/why_design.pptx .venv/bin/python plans/ppt/make_why_design.py
    bash plans/ppt/why_to_mp4.sh                              # 再轉成短視頻 MP4
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from why_icons import icon as draw_icon

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(os.environ.get("OUT", ROOT / "plans/ppt/why_design.pptx"))
BUILD = Path(os.environ.get("BUILD", ROOT / "TMP/whybuild"))   # 中間產物（背景圖／主視覺／比較圖／字型）
BUILD.mkdir(parents=True, exist_ok=True)
IMG_DIR = ROOT / "plans/ppt/why_design"                         # 使用者提供的插畫

# ── 設計常數 ──────────────────────────────────────────────────────────
SLIDE_W, SLIDE_H = Emu(5670550), Emu(10080625)      # 6.201 x 11.024 inch（直式 9:16）
PX_W, PX_H = 1080, 1920
SLIDE_W_IN, SLIDE_H_IN = 6.2014, 11.0243

WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT = RGBColor(0xF2, 0xF6, 0xFB)                    # 主文字（近白）
SOFT = RGBColor(0xC9, 0xD6, 0xE6)                    # 次要白
MUTED = RGBColor(0x9F, 0xB0, 0xC6)                   # 說明文字
ACCENT = RGBColor(0xFF, 0x5A, 0x4D)                  # 重點紅（暗底提亮版）
SLATE = RGBColor(0x7C, 0x8D, 0xA6)                   # 對照組（0050）
CARD = RGBColor(0x0A, 0x14, 0x24)                    # 卡片底
BORDER = RGBColor(0x2C, 0x4B, 0x74)                  # 卡片描邊

FONT = "Noto Sans CJK TC"
CJK_BOLD_TTC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
CJK_REG_TTC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

MARGIN = Inches(0.62)
CONTENT_W = Inches(4.96)
ICON_IN = 0.42
ICON_GAP = 0.14

BG_STOPS = [(0.0, "#03060C"), (0.20, "#06101D"), (0.44, "#0A1626"),
            (0.70, "#060E1A"), (1.0, "#02040A")]

# 比較數字（README「回測」主表；2022-01-01～2026-10-23、停泊 0050 口徑）
PERIOD = "2022-01 ～ 2026-10"
METRICS = [
    ("總報酬", "越高越好", 283.1, 231.4, "＋", "%"),
    ("最大回撤", "越淺越好", 33.4, 34.0, "−", "%"),
    ("夏普比率", "越高越好", 1.18, 1.21, "", ""),
]
SERIES = (("目前版本", ACCENT), ("0050 買進持有", SLATE))

# 第 5 頁重點句（使用者 2026-11-01 裁定：重點是獲利最高，不是贏 0050）
CALLOUT = [
    ("單策略能不能贏 0050 不是重點", True),
    ("選股有合乎程式標準就買,", False),
    ("沒合適的時候就買0050", False),
    ("⇒ 使用者的獲利最高", False),
]


# ── 小工具 ────────────────────────────────────────────────────────────
def _hex(rgb):
    if isinstance(rgb, RGBColor):
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
    h = rgb.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _bg_color_at(frac: float) -> str:
    """背景漸層在指定高度（0~1）的顏色 ⇒ 讓主視覺圖的淡出邊界接得無痕。"""
    pos = [s[0] for s in BG_STOPS]
    j = max(0, min(len(pos) - 2, max(k for k, p in enumerate(pos) if p <= frac)))
    span = max(1e-9, pos[j + 1] - pos[j])
    f = min(1.0, max(0.0, (frac - pos[j]) / span))
    c0, c1 = np.array(_hex(BG_STOPS[j][1])), np.array(_hex(BG_STOPS[j + 1][1]))
    c = (c0 + (c1 - c0) * f).astype(int)
    return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"


def _alpha_fill(shape, rgb: RGBColor, alpha_pct: int) -> None:
    """把 shape 的實心填色改成帶透明度（python-pptx 沒有 alpha API）。"""
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb
    srgb = shape.fill.fore_color._xFill.find(qn("a:srgbClr"))
    srgb.append(srgb.makeelement(qn("a:alpha"), {"val": str(int(alpha_pct * 1000))}))


def _alpha_line(shape, alpha_pct: int = 35) -> None:
    srgb = shape.line.color._xFill.find(qn("a:srgbClr"))
    srgb.append(srgb.makeelement(qn("a:alpha"), {"val": str(int(alpha_pct * 1000))}))


def _send_to_back(slide, shape) -> None:
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2, shape._element)


# ── 背景圖（Pillow 現畫）──────────────────────────────────────────────
def _vgradient(stops: list[tuple[float, str]], w: int, h: int) -> np.ndarray:
    ys = np.linspace(0.0, 1.0, h)
    pos = [s[0] for s in stops]
    img = np.zeros((h, w, 3), dtype=np.float64)
    for i in range(h):
        t = ys[i]
        j = max(0, min(len(pos) - 2, int(np.searchsorted(pos, t)) - 1))
        span = max(1e-9, pos[j + 1] - pos[j])
        f = min(1.0, max(0.0, (t - pos[j]) / span))
        c0, c1 = np.array(_hex(stops[j][1])), np.array(_hex(stops[j + 1][1]))
        img[i, :, :] = (c0 + (c1 - c0) * f)[None, :]
    return img


def _add_glow(img: np.ndarray, cx: float, cy: float, r: float, color: str, strength: float) -> None:
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d2 = ((xx - cx * w) ** 2 + (yy - cy * h) ** 2) / (2 * (r * w) ** 2)
    img += np.exp(-d2)[:, :, None] * strength * np.array(_hex(color), dtype=np.float64)[None, None, :]


def _walk(n: int, seed: int, drift: float = 0.0, vol: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(drift, vol, n))


def _smooth(y: np.ndarray, k: int = 9) -> np.ndarray:
    return np.convolve(y, np.ones(k) / k, mode="same")


def background(name: str, seed: int, *, glow_xy=(0.5, 0.18), glow_r=0.8, glow_s=0.16,
               candles=True, trend=True, grid=True) -> Path:
    """直式背景：深藍黑漸層＋冷光暈＋K 線殘影＋走勢線光暈＋格線＋暗角＋噪點。"""
    path = BUILD / f"bg_{name}.jpg"
    img = _vgradient(BG_STOPS, PX_W, PX_H)
    _add_glow(img, glow_xy[0], glow_xy[1], glow_r, "#1B4A80", glow_s)
    _add_glow(img, 0.06, 0.70, 0.5, "#0F2C4E", glow_s * 0.75)
    _add_glow(img, 0.97, 0.92, 0.45, "#6E211A", glow_s * 0.5)

    overlay = Image.new("RGBA", (PX_W, PX_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    if grid:
        for y in range(0, PX_H, 96):
            d.line([(0, y), (PX_W, y)], fill=(120, 165, 220, 10), width=1)
        for x in range(0, PX_W, 96):
            d.line([(x, 0), (x, PX_H)], fill=(120, 165, 220, 7), width=1)

    if candles:
        rng = np.random.default_rng(seed)
        n = 26
        base = _smooth(_walk(n, seed, 0.35, 1.0), 5)
        base = (base - base.min()) / max(1e-9, float(np.ptp(base)))
        bw = PX_W / (n * 1.9)
        for i in range(n):
            cx = PX_W * 0.06 + i * PX_W * 0.88 / (n - 1)
            cy = PX_H * (0.66 + 0.24 * (1.0 - base[i]))
            hgt = PX_H * (0.010 + 0.030 * rng.random())
            up = rng.random() > 0.45
            col = (46, 210, 160, 30) if up else (235, 90, 80, 26)
            d.rectangle([cx - bw / 2, cy - hgt / 2, cx + bw / 2, cy + hgt / 2], fill=col)
            d.line([(cx, cy - hgt * 1.35), (cx, cy + hgt * 1.35)], fill=col, width=3)

    if trend:
        n = 64
        y = _smooth(_walk(n, seed + 7, -0.18, 1.0), 11)
        y = (y - y.min()) / max(1e-9, float(np.ptp(y)))
        pts = [(PX_W * (0.02 + 0.96 * i / (n - 1)),
                PX_H * (0.93 - 0.12 * y[i])) for i in range(n)]
        glow = Image.new("RGBA", (PX_W, PX_H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.line(pts, fill=(255, 90, 77, 85), width=15, joint="curve")
        overlay = Image.alpha_composite(overlay, glow.filter(ImageFilter.GaussianBlur(17)))
        d = ImageDraw.Draw(overlay)
        d.line(pts, fill=(255, 122, 107, 165), width=4, joint="curve")

    out = Image.alpha_composite(
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA"), overlay
    )

    yy, xx = np.mgrid[0:PX_H, 0:PX_W]
    dx = (xx - PX_W / 2) / (PX_W / 2)
    dy = (yy - PX_H / 2) / (PX_H / 2)
    vig = 1.0 - 0.40 * np.clip((dx ** 2 * 0.8 + dy ** 2 * 0.8) - 0.10, 0, None) ** 1.15
    arr = np.asarray(out.convert("RGB"), dtype=np.float64) * vig[:, :, None]
    rng = np.random.default_rng(seed + 31)
    arr += rng.normal(0, 1.8, arr.shape)

    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(
        path, quality=88, optimize=True, subsampling=1
    )
    return path


# ── 主視覺橫幅（使用者插畫 → 滿版裁切／壓暗／底部淡出）──────────────────
def hero_png(name: str, height_in: float, *, darken: float = 0.20, blur: float = 0.0,
             fade_in: float = 1.20, crop_zoom: float = 1.0, dpi: int = 165) -> Path:
    """把 16:9 插畫裁成 6.2×height 的橫幅：置中裁切（可再放大取景）→ 壓暗 → 底部漸層接回背景色。"""
    src = IMG_DIR / name
    out = BUILD / (f"hero_{src.stem}_{height_in:.2f}_{darken:.2f}_{blur:.1f}"
                   f"_{crop_zoom:.2f}.jpg")
    if out.exists():
        return out
    W, H = int(SLIDE_W_IN * dpi), int(height_in * dpi)
    im = Image.open(src).convert("RGB")
    if crop_zoom > 1.0:                                   # 先放大取景，再裁成橫幅比例
        sw0, sh0 = im.size
        cw, ch = int(sw0 / crop_zoom), int(sh0 / crop_zoom)
        im = im.crop(((sw0 - cw) // 2, (sh0 - ch) // 2, (sw0 + cw) // 2, (sh0 + ch) // 2))
    sw, sh = im.size
    target = W / H
    if sw / sh > target:                                   # 太寬 ⇒ 裁左右
        nw = int(round(sh * target))
        im = im.crop(((sw - nw) // 2, 0, (sw + nw) // 2, sh))
    else:                                                  # 太高 ⇒ 裁上下
        nh = int(round(sw / target))
        im = im.crop((0, (sh - nh) // 2, sw, (sh + nh) // 2))
    im = im.resize((W, H), Image.LANCZOS)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))

    arr = np.asarray(im, dtype=np.float64) * (1.0 - darken)
    fade_px = min(H, int(fade_in * dpi))
    tgt = np.array(_hex(_bg_color_at(height_in / SLIDE_H_IN)), dtype=np.float64)
    for i in range(fade_px):
        y = H - fade_px + i
        f = ((i + 1) / fade_px) ** 0.85
        arr[y, :, :] = arr[y, :, :] * (1 - f) + tgt[None, :] * f
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(
        out, quality=88, optimize=True, subsampling=1
    )
    return out


def _hero(slide, name: str, height_in: float, darken: float = 0.20, blur: float = 0.0,
          crop_zoom: float = 1.0):
    pic = slide.shapes.add_picture(
        str(hero_png(name, height_in, darken=darken, blur=blur, crop_zoom=crop_zoom)), 0, 0,
                                   width=SLIDE_W, height=Inches(height_in))
    pic.line.fill.background()
    return pic


# ── 比較圖（matplotlib 現畫）───────────────────────────────────────────
def _cjk_fonts():
    """matplotlib 讀不到 .ttc 裡的多個字面 ⇒ 先把「Noto Sans CJK TC」抽成獨立 .otf。"""
    from fontTools.ttLib import TTCollection

    out = {}
    for key, src in (("bold", CJK_BOLD_TTC), ("reg", CJK_REG_TTC)):
        dst = BUILD / f"NotoSansCJKtc-{key}.otf"
        if not dst.exists():
            coll = TTCollection(src)
            face = next(f for f in coll.fonts if f["name"].getDebugName(1) == "Noto Sans CJK TC")
            face.save(dst)
        out[key] = dst
    return out["reg"], out["bold"]


def comparison_png() -> Path:
    """三組橫條圖（每組自己一個尺度）。圖幅＝投影片上的實際尺寸（inch）⇒ 字級等於實際 pt。"""
    from matplotlib import font_manager as fm
    from matplotlib import pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    reg, bold = _cjk_fonts()
    fm.fontManager.addfont(str(reg))
    fm.fontManager.addfont(str(bold))
    f_reg = fm.FontProperties(fname=str(reg))
    f_bold = fm.FontProperties(fname=str(bold))

    W, H = 5.06, 4.08                                    # inch
    fig = plt.figure(figsize=(W, H), dpi=220)
    fig.patch.set_alpha(0.0)
    fx, fy = (lambda v: v / W), (lambda v: v / H)

    # ── 頂列：圖例（左）＋ 期間（右）
    def text_w(s: str, pt: float) -> float:
        """粗估文字寬度（inch）：CJK 全寬、拉丁約 0.55。"""
        return sum(pt / 72 * (1.0 if ord(c) > 0x2E80 else 0.55) for c in s)

    y_top = H - 0.18
    x = 0.04
    for label, color in SERIES:
        fig.add_artist(Rectangle((fx(x), fy(y_top - 0.062)), fx(0.15) - fx(0), fy(0.125),
                                 transform=fig.transFigure, facecolor=_hex(color), edgecolor="none"))
        fig.text(fx(x + 0.21), fy(y_top), label, va="center", ha="left",
                 fontproperties=f_reg, fontsize=10,
                 color=_hex(TEXT) if color is ACCENT else _hex(MUTED))
        x += 0.21 + text_w(label, 10) + 0.26
    fig.text(fx(W - 0.04), fy(y_top), PERIOD, va="center", ha="right",
             fontproperties=f_reg, fontsize=10, color=_hex(MUTED))
    fig.add_artist(Line2D([fx(0.04), fx(W - 0.04)], [fy(H - 0.36)] * 2, transform=fig.transFigure,
                          color=_hex(BORDER), lw=0.9, alpha=0.75))

    # ── 三個面板（標題在上、兩條橫條在下；每組自己一個尺度）
    panel_h, gap, top = 1.06, 0.16, H - 0.44
    for i, (label, hint, mine, base, sign, unit) in enumerate(METRICS):
        bottom = top - (i + 1) * panel_h - i * gap
        ax = fig.add_axes([fx(0.04), fy(bottom), fx(W - 0.08), fy(panel_h)])
        ax.set_facecolor("none")
        ax.axis("off")
        vals = (mine, base)
        mx = max(vals)
        ax.set_xlim(0, mx * 1.28)
        ax.set_ylim(-0.55, 2.30)

        ax.text(0, 2.26, label, va="top", ha="left", fontproperties=f_bold,
                fontsize=13.5, color=_hex(SOFT))
        ax.text(mx * 1.28, 2.26, hint, va="top", ha="right", fontproperties=f_reg,
                fontsize=9, color=_hex(MUTED))
        for j, v in enumerate(vals):
            y = 1 - j
            ax.barh(y, v, height=0.46, color=_hex((ACCENT, SLATE)[j]), edgecolor="none")
            txt = f"{sign}{v:.1f}{unit}" if unit else f"{v:.2f}"
            ax.text(v + mx * 0.035, y, txt, va="center", ha="left", fontproperties=f_bold,
                    fontsize=14.5, color="#FFFFFF" if j == 0 else _hex(MUTED))

    path = BUILD / "cmp_chart.png"
    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 版面元件 ──────────────────────────────────────────────────────────
def _bg_slide(prs, img: Path):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    pic = s.shapes.add_picture(str(img), 0, 0, width=SLIDE_W, height=SLIDE_H)
    _send_to_back(s, pic)
    return s


def _card(slide, box, *, fill: RGBColor = CARD, alpha: int = 74, radius: float = 0.05,
          border: bool = True):
    left, top, w, h = box
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    sh.adjustments[0] = radius
    _alpha_fill(sh, fill, alpha)
    if border:
        sh.line.color.rgb = BORDER
        sh.line.width = Pt(1.0)
        _alpha_line(sh, 34)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def _accent_bar(slide, left, top, w=Inches(0.78), h=Inches(0.08), color=ACCENT):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    sh.adjustments[0] = 0.5
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def _rich_para(para, text: str, marks: tuple[str, ...] = (), *, size=Pt(24), bold=False,
               color: RGBColor = TEXT, mark_color: RGBColor = ACCENT,
               align=PP_ALIGN.LEFT, line=1.34, space_after=Pt(16)):
    para.alignment = align
    para.line_spacing = line
    para.space_after = space_after

    spans: list[tuple[int, int]] = []
    for m in marks:
        start = 0
        while (idx := text.find(m, start)) >= 0:
            spans.append((idx, idx + len(m)))
            start = idx + len(m)
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    pieces: list[tuple[str, bool]] = []
    cursor = 0
    for a, b in merged:
        if a > cursor:
            pieces.append((text[cursor:a], False))
        pieces.append((text[a:b], True))
        cursor = b
    if cursor < len(text):
        pieces.append((text[cursor:], False))

    for chunk, hot in pieces:
        run = para.add_run()
        run.text = chunk
        run.font.name = FONT
        run.font.size = size
        run.font.bold = bold or hot
        run.font.color.rgb = mark_color if hot else color
    return para


def _textbox(slide, left, top, w, h, *, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    return box, tf


def _page_no(slide, n: int, total: int = 6):
    box, tf = _textbox(slide, 0, Inches(10.40), SLIDE_W, Inches(0.32), anchor=MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = f"{n:02d} / {total:02d}"
    run.font.name = FONT
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor(0x5E, 0x71, 0x89)


def _measure_lines(text: str, size_pt: float, width_in: float, font_path: Path,
                   safety: float = 0.99) -> int:
    """粗算這段文字在指定寬度下會折幾行（LibreOffice 會在中西文之間多留空隙 ⇒ 留 1% 餘裕）。"""
    from PIL import ImageFont

    font = ImageFont.truetype(str(font_path), int(size_pt * 4))
    limit = width_in * 72 * 4 * safety
    lines, cur = 1, 0.0
    for ch in text:
        w = font.getlength(ch)
        if cur + w > limit and cur > 0:
            lines += 1
            cur = w
        else:
            cur += w
    return lines


def _icon_rows(slide, rows, *, box, size, line=1.40, row_gap=0.26, icon_in=ICON_IN,
               icon_gap=ICON_GAP):
    """一列＝[圖示磁磚][文字]，整組垂直置中在 box 裡；每列各自一個 textbox（不吃自動換行）。"""
    left, top, w, h = box
    text_x = left + Inches(icon_in) + Inches(icon_gap)
    text_w_in = (left + w - text_x) / 914400
    line_h = size.pt * line / 72

    reg, bold = _cjk_fonts()
    heights = [max(icon_in, _measure_lines(t, size.pt, text_w_in, reg) * line_h) + 0.02
               for _, t, _ in rows]
    total = sum(heights) + row_gap * (len(rows) - 1)
    y = top + int(((h / 914400) - total) / 2 * 914400)

    for i, (glyph, text, marks_i) in enumerate(rows):
        pic = slide.shapes.add_picture(str(draw_icon(glyph, BUILD / "icons", question_glyph=bold)),
                                       left, y + int((line_h - icon_in) / 2 * 914400),
                                       width=Inches(icon_in), height=Inches(icon_in))
        pic.line.fill.background()
        _box, tf = _textbox(slide, text_x, y, Inches(text_w_in), Inches(heights[i]))
        _rich_para(tf.paragraphs[0], text, marks_i, size=size, line=line, space_after=Pt(0))
        y += int(heights[i] * 914400) + int(row_gap * 914400)


def _join_sentences(items: list[str]) -> str:
    """串成旁白稿：句子之間補「。」，但遇到 ? ！ 句尾不重複加。"""
    out = ""
    for raw in items:
        item = raw.strip()
        if not item:
            continue
        if out and out[-1] not in "。！？…?!":
            out += "。"
        out += item
    if out and out[-1] not in "。！？…?!":
        out += "。"
    return out


def _notes(slide, seconds: int, spoken: list[str], onscreen: list[str]) -> None:
    """旁白稿寫進備註：畫面上沒有的句子只靠語音（可交給 TTS 念）。"""
    joined = _join_sentences(spoken)
    lines = [f"⏱ 約 {seconds} 秒", f"【旁白】{joined}"]
    if onscreen:
        lines.append(f"【畫面】只放 {len(onscreen)} 行：{'／'.join(onscreen)}")
    hidden = [x for x in spoken if not any(x in o or o in x for o in onscreen)]
    if hidden:
        lines.append(f"【只有語音、不上畫面】{'／'.join(hidden)}")
    slide.notes_slide.notes_text_frame.text = "\n".join(lines)


# ── 內容（使用者原稿，逐字）───────────────────────────────────────────
COVER = "為什麼我要開發這一套股票系統"
SLIDE5_LEAD = "現在這是目前版本跟0050於2022到目前的獲利/最大回撤/夏普的比較圖"

# 主視覺：使用者提供的插畫（檔名, 橫幅高度吋, 壓暗, 模糊）
HEROES = {
    1: ("image_1f450dfb.jpg", 6.10, 0.16, 0.0, 1.45),   # 玻璃晶片（30 年硬體；放大取景）
    2: ("image_b44847b2.jpg", 4.40, 0.22, 0.0, 1.0),    # 金幣＋成長儀表（投資／ETF 20%）
    3: ("image_d9a4591d.jpg", 4.40, 0.22, 0.0, 1.0),    # AI 機器人＋程式碼（AI 幫忙）
    4: ("image_99066f06.jpg", 4.95, 0.55, 1.4, 1.0),    # 成長柱狀（高獲利）—壓暗＋模糊，避免讀到圖上的示意數字
    6: ("image_8fcf184f.jpg", 5.30, 0.20, 0.0, 1.0),    # 2026/07 日曆＋LIVE TESTING（實測）
}

# 上畫面的句子（原稿逐字）；沒列到的句子只靠旁白
ONSCREEN = {
    2: ["我幹了超過30年硬體工程師", "我想拿一些錢去投資股票", "又覺得ETF一年賺不到20%有點少"],
    3: ["我不懂投資", "我不懂股票", "我完成了這套系統"],
    4: ["8個月時,我10年回測年獲利就有40%", "所以那一版就放棄了"],
    6: ["本系統自2026年7月開始上實測,並持續測試,隨時更新!"],
}
SPOKEN = {
    2: ["我幹了超過30年硬體工程師", "我想拿一些錢去投資股票", "我不想花幾萬塊去跟人學量化",
        "也不想花幾萬去拜股票大師", "又覺得ETF一年賺不到20%有點少"],
    3: ["我不懂投資", "我不懂股票", "但是呢基於我是資訊本科", "加上現在有AI的幫助", "我完成了這套系統"],
    4: ["8個月時,我10年回測年獲利就有40%",
        "但是呢這種高獲利選出的大多數是中小股回撤也高達40多%", "所以那一版就放棄了"],
    6: ["有了AI還要自己弄這套系統嗎?", "AI不能自行下單",
        "AI能寫程式但是寫出來的程式還是得上線實測才知問題",
        "本系統自2026年7月開始上實測,並持續測試,隨時更新!"],
}
# 備註裡「畫面上有什麼」的清單（第 6 頁的大標題也是畫面上的字，但不列入 icon 列）
NOTES_SCREEN = {6: ["有了AI還要自己弄這套系統嗎?",
                    "本系統自2026年7月開始上實測,並持續測試,隨時更新!"]}
ICONS_ONSCREEN = {
    2: ["chip", "coins", "gauge"],
    3: ["question", "chart_x", "gear_check"],
    4: ["arrow_up", "x_circle"],
    6: ["calendar"],
}
MARKS = {
    2: ("30年", "20%"),
    3: ("完成了這套系統",),
    4: ("40%", "40多%"),
    6: ("2026年7月", "隨時更新"),
}
SECONDS = {1: 8, 2: 22, 3: 16, 4: 20, 5: 26, 6: 20}


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    bgs = {
        1: background("cover", 11, glow_xy=(0.40, 0.30), glow_r=0.72, glow_s=0.20),
        2: background("s2", 23, glow_xy=(0.88, 0.68), glow_s=0.14),
        3: background("s3", 37, glow_xy=(0.10, 0.72), glow_r=0.70, glow_s=0.14),
        4: background("s4", 51, glow_xy=(0.52, 0.70), glow_s=0.12, glow_r=0.62),
        5: background("s5", 67, glow_xy=(0.18, 0.14), glow_s=0.14, candles=False),
        6: background("s6", 83, glow_xy=(0.50, 0.92), glow_r=0.95, glow_s=0.18),
    }

    # ① 封面 -----------------------------------------------------------
    s = _bg_slide(prs, bgs[1])
    _hero(s, *HEROES[1])
    _accent_bar(s, Inches(2.71), Inches(6.62))
    box, tf = _textbox(s, MARGIN, Inches(6.98), CONTENT_W, Inches(2.6))
    _rich_para(tf.paragraphs[0], "為什麼我要開發", size=Pt(35), bold=True,
               align=PP_ALIGN.CENTER, line=1.40, space_after=Pt(0))
    _rich_para(tf.add_paragraph(), "這一套股票系統", ("這一套股票系統",), size=Pt(35), bold=True,
               align=PP_ALIGN.CENTER, line=1.40, space_after=Pt(0))
    _notes(s, SECONDS[1], [COVER], [COVER])
    _page_no(s, 1)

    # ②③④⑥ 主視覺頁（上面大圖、下面只放重點幾行）--------------------
    def content(idx: int) -> None:
        s = _bg_slide(prs, bgs[idx])
        name, hero_h, darken, blur, zoom = HEROES[idx]
        _hero(s, name, hero_h, darken=darken, blur=blur, crop_zoom=zoom)

        if idx == 6:      # 這一頁多一個大標題
            box, tf = _textbox(s, MARGIN, Inches(hero_h + 0.40), CONTENT_W, Inches(1.6))
            _rich_para(tf.paragraphs[0], "有了AI還要", size=Pt(28), bold=True,
                       align=PP_ALIGN.CENTER, line=1.38, space_after=Pt(0))
            _rich_para(tf.add_paragraph(), "自己弄這套系統嗎?", ("自己弄這套系統",), size=Pt(28),
                       bold=True, align=PP_ALIGN.CENTER, line=1.38, space_after=Pt(0))
            _accent_bar(s, Inches(2.69), Inches(hero_h + 2.04), Inches(0.82), Inches(0.075))
            rows_top, rows_h = hero_h + 2.40, 1.90
        else:
            rows_top, rows_h = hero_h + 0.42, SLIDE_H_IN - hero_h - 1.50

        size = {3: Pt(24), 6: Pt(22)}.get(idx, Pt(23))
        rows = [(ic, t, MARKS[idx]) for ic, t in zip(ICONS_ONSCREEN[idx], ONSCREEN[idx])]
        _icon_rows(s, rows, box=(MARGIN, Inches(rows_top), CONTENT_W, Inches(rows_h)),
                   size=size, row_gap=0.52, icon_in=0.50, icon_gap=0.13)
        _notes(s, SECONDS[idx], SPOKEN[idx], NOTES_SCREEN.get(idx, ONSCREEN[idx]))
        _page_no(s, idx)

    content(2)
    content(3)
    content(4)

    # ⑤ 比較圖 --------------------------------------------------------
    s = _bg_slide(prs, bgs[5])
    box, tf = _textbox(s, MARGIN, Inches(1.24), CONTENT_W, Inches(1.16))
    _rich_para(tf.paragraphs[0], SLIDE5_LEAD, ("目前版本", "0050"), size=Pt(18),
               line=1.44, space_after=Pt(0), color=RGBColor(0xDD, 0xE7, 0xF2))

    _card(s, (Inches(0.34), Inches(2.52), Inches(5.52), Inches(4.48)), alpha=78)
    chart = comparison_png()
    pic = s.shapes.add_picture(str(chart), Inches(0.49), Inches(2.68), width=Inches(5.22))
    pic.line.fill.background()

    _card(s, (Inches(0.34), Inches(7.10), Inches(5.52), Inches(2.12)), alpha=26,
          fill=RGBColor(0x2A, 0x10, 0x10))
    _accent_bar(s, Inches(0.44), Inches(7.26), Inches(0.055), Inches(1.80))
    box, tf = _textbox(s, Inches(0.76), Inches(7.28), Inches(4.86), Inches(1.76),
                       anchor=MSO_ANCHOR.MIDDLE)
    for i, (line, hot) in enumerate(CALLOUT):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        _rich_para(para, line, (line,) if hot else ("⇒",), size=Pt(20) if hot else Pt(17),
                   bold=True, line=1.36, space_after=Pt(8),
                   color=WHITE, mark_color=ACCENT if hot else RGBColor(0xFF, 0x9A, 0x63))
    _notes(s, SECONDS[5], [
        SLIDE5_LEAD,
        "其實單策略能不能贏 0050 不是重點：選股有合乎程式標準就買，沒合適的時候就買 0050，這樣使用者的獲利最高",
    ], [SLIDE5_LEAD] + [t for t, _ in CALLOUT])
    _page_no(s, 5)

    content(6)

    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"✅ 產生 {p.relative_to(ROOT)}（{p.stat().st_size / 1024 / 1024:.1f} MB）")
    print(f"   中間產物：{BUILD.relative_to(ROOT)}/（背景 ×6、主視覺 ×5、比較圖 ×1、圖示）")
