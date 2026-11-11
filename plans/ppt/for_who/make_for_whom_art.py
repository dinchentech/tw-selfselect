#!/usr/bin/env python3
"""make_for_whom_art.py · 給 `for_who/for_whom.pptx` 畫 6 張示意圖並嵌進主檔

背景：使用者手做的 6 頁直式短片（「TW-SelfSelect 適合甚麼人」）只有深藍漸層底＋文字，
上半頁大片空白 ⇒ 本腳本在每頁的空白區放一張**現畫的示意圖**（Pillow 畫，點陣 PNG），
沿用 `make_why_design.py` 的色票與 `why_icons.py` 的圖示語言（深藍底＋細線＋紅色重點），
沒有外部圖檔、沒有版權問題、可重複產生。

設計原則：圖要**帶資訊**，不是裝飾——
    P1 封面   適用條件檢查表（要會 3 項／不必會 3 項，不必會的打紅 ✕）
    P2 門檻一 WSL 終端機 →(ssh)→ GCP 雲端機器＋固定 IP，底下補「常用指令就是檔案與目錄」
    P3 門檻二 你出一句指令 → DSH／AI → 程式改好（左到右＝說話→AI→程式）
    P4 不用懂股票 FinMind／TWSE → 每月選 N 檔 → 有合乎標準的？是⇒買進／否⇒現金或 0050
    P5 不用懂策略 四個迷你走勢（均線交叉／布林通道／VWAP 回歸／突破）＋「買入時就決定」
    P6 費用    授權 29 杯（一次性）vs GCP 月費 <1 杯（比例長條，差距就是重點）

⚠️ **字級**（2026-11-05 第二輪，使用者「圖的字太小了加大些」）：圖內標籤一律 13–16 pt、
面板標題 14 pt、主數字 17–19 pt，最小不低於 12 pt（畫布 200 px ＝ 1 吋 ⇒ 圖內 pt ＝ 畫面上 pt）。
放大字級同時把磁磚／方框／面板一起放大，避免文字擠出方框。

用法：
    .venv/bin/python plans/ppt/for_who/make_for_whom_art.py            # 畫圖 + 嵌進主檔（先備份）
    .venv/bin/python plans/ppt/for_who/make_for_whom_art.py draw       # 只畫圖（→ for_who/art/）
    .venv/bin/python plans/ppt/for_who/make_for_whom_art.py embed      # 只嵌圖（用既有 art/）
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DECK = ROOT / "plans/ppt/for_who/for_whom.pptx"
ART = ROOT / "plans/ppt/for_who/art"
BACKUP = ROOT / "TMP/forwhom_build"

PX = 200                      # 200 px / inch
REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
TC = 3                        # NotoSansCJK ttc 的繁中字面

# ── 色票（與 make_why_design.py 同一家族，暗底提亮版）──────────────────────
TEXT = (242, 246, 251, 255)
SOFT = (201, 214, 232, 255)
MUTED = (150, 172, 198, 255)
ACCENT = (255, 90, 77, 255)          # 重點紅
ORANGE = (242, 164, 84, 255)         # 琥珀（曲線）
BLUE = (124, 172, 222, 255)          # 冷藍（線／框）
TEAL = (86, 190, 160, 255)           # 綠（買／通過）
CARD = (10, 20, 36, 205)
CARD_HI = (16, 30, 52, 225)
BORDER = (52, 84, 126, 255)
BORDER_DIM = (40, 64, 96, 255)

_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def F(pt: float, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    key = ("m" if mono else ("b" if bold else "r"), int(round(pt * PX / 72)))
    if key not in _fonts:
        if mono:
            _fonts[key] = ImageFont.truetype(MONO, key[1])
        else:
            _fonts[key] = ImageFont.truetype(BOLD if bold else REG, key[1], index=TC)
    return _fonts[key]


def canvas(w_in: float, h_in: float) -> Image.Image:
    return Image.new("RGBA", (int(w_in * PX), int(h_in * PX)), (0, 0, 0, 0))


def glow(img: Image.Image, draw_fn, *, radius: float = 4.0, scale: float = 1.0) -> None:
    """把 draw_fn 畫在另一層 → 模糊 → 疊回（做出暗底霓虹光暈）。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    if scale != 1.0:
        a = layer.split()[3].point(lambda v: min(255, int(v * scale)))
        layer.putalpha(a)
    img.alpha_composite(layer)


def rr(d: ImageDraw.ImageDraw, box, r=12, fill=None, outline=None, width=2) -> None:
    d.rounded_rectangle([int(v) for v in box], radius=r, fill=fill, outline=outline, width=width)


def line(d: ImageDraw.ImageDraw, pts, fill, width=3) -> None:
    d.line([(int(x), int(y)) for x, y in pts], fill=fill, width=width, joint="curve")


def arrow(d: ImageDraw.ImageDraw, p0, p1, fill, width=3, head=13) -> None:
    line(d, [p0, p1], fill, width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for s in (+1, -1):
        a = ang + s * math.radians(28)
        d.line([(int(p1[0]), int(p1[1])),
                (int(p1[0] - head * math.cos(a)), int(p1[1] - head * math.sin(a)))],
               fill=fill, width=width)


def txt(img, xy, s, pt, fill=SOFT, *, bold=False, mono=False, anchor="la", align="left"):
    ImageDraw.Draw(img).text((int(xy[0]), int(xy[1])), s, font=F(pt, bold=bold, mono=mono),
                             fill=fill, anchor=anchor, align=align)


def tile(img, box, glyph: str, *, accent: bool = False, badge: str | None = None) -> None:
    """圓角圖示磁磚（沿用 why_icons 的語言：深藍底＋細框＋白線字形，可加紅 ✕ 徽章）。"""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    rr(d, box, r=int((x1 - x0) * 0.24), fill=(16, 30, 50, 235),
       outline=ACCENT if accent else BORDER, width=3)
    cx, cy, s = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.30
    g = ORANGE if accent else TEXT
    w = max(3, int((x1 - x0) * 0.055))
    if glyph == "terminal":
        rr(d, (cx - s * 1.15, cy - s * 0.85, cx + s * 1.15, cy + s * 0.85), r=4, outline=g)
        d.line([cx - s * 0.75, cy - s * 0.35, cx - s * 0.30, cy], fill=g, width=w)
        d.line([cx - s * 0.30, cy, cx - s * 0.75, cy + s * 0.35], fill=g, width=w)
        d.line([cx + s * 0.05, cy + s * 0.42, cx + s * 0.75, cy + s * 0.42], fill=g, width=w)
    elif glyph == "cloud":
        cy2 = cy + s * 0.18
        d.ellipse([cx - s * 1.2, cy2 - s * 0.55, cx - s * 0.1, cy2 + s * 0.55], outline=g, width=w)
        d.ellipse([cx - s * 0.55, cy2 - s * 0.95, cx + s * 0.5, cy2 + s * 0.5], outline=g, width=w)
        d.ellipse([cx + s * 0.05, cy2 - s * 0.45, cx + s * 1.15, cy2 + s * 0.55], outline=g, width=w)
        d.line([cx - s * 1.05, cy2 + s * 0.5, cx + s * 1.05, cy2 + s * 0.5], fill=g, width=w)
    elif glyph == "spark":
        for i in range(3):
            yy = cy - s * 0.65 + i * s * 0.65
            d.line([cx - s * 1.0, yy, cx + s * 0.55, yy], fill=g, width=w)
        d.line([cx + s * 0.95, cy - s * 0.9, cx + s * 0.95, cy + s * 0.9], fill=g, width=w)
    elif glyph == "candle":
        for i, (h, up) in enumerate(((-0.5, 0), (-0.1, 1), (0.35, 1), (0.7, 0))):
            xx = cx - s * 0.95 + i * s * 0.62
            yy = cy - s * 0.3 + h * s * 0.9
            d.line([xx, yy - s * 0.42, xx, yy + s * 0.42], fill=g, width=w)
            d.rectangle([xx - s * 0.17, yy - s * 0.22, xx + s * 0.17, yy + s * 0.22],
                        outline=g, width=w)
    elif glyph == "sliders":
        for i in range(3):
            yy = cy - s * 0.62 + i * s * 0.62
            d.line([cx - s * 1.1, yy, cx + s * 1.1, yy], fill=g, width=w)
            kx = cx + (-s * 0.45 if i % 2 == 0 else s * 0.4)
            d.ellipse([kx - s * 0.2, yy - s * 0.2, kx + s * 0.2, yy + s * 0.2], fill=(8, 16, 30, 255),
                      outline=g, width=w)
    elif glyph == "code":
        d.line([cx - s * 0.65, cy - s * 0.55, cx - s * 1.15, cy], fill=g, width=w)
        d.line([cx - s * 1.15, cy, cx - s * 0.65, cy + s * 0.55], fill=g, width=w)
        d.line([cx + s * 1.15, cy - s * 0.55, cx + s * 0.65, cy], fill=g, width=w)
        d.line([cx + s * 0.65, cy, cx + s * 1.15, cy + s * 0.55], fill=g, width=w)
        d.line([cx + s * 0.25, cy - s * 0.8, cx - s * 0.25, cy + s * 0.8], fill=g, width=w)
    if badge == "x":
        bx, by, br = x1 - (x1 - x0) * 0.10, y1 - (y1 - y0) * 0.10, (x1 - x0) * 0.28
        d.ellipse([bx - br, by - br, bx + br, by + br], fill=ACCENT, outline=(10, 20, 36, 255), width=3)
        for sgn in (+1, -1):
            d.line([bx - br * 0.42 * sgn, by - br * 0.42, bx + br * 0.42 * sgn, by + br * 0.42],
                   fill=(255, 255, 255, 255), width=max(3, int(br * 0.3)))


def row(img, xy, icon: str, label: str, *, pt=16, badge=None, accent=False, tile_in=0.46):
    x, y = xy
    t = tile_in * PX
    tile(img, (x, y, x + t, y + t), icon, accent=accent, badge=badge)
    txt(img, (x + t + 0.18 * PX, y + t * 0.5), label, pt,
        TEXT if not badge else SOFT, anchor="lm")


# ══════════════════════════════════════════════════════════════════════════
# P1 · 適用條件檢查表（標籤 16 pt、卡標題 14 pt、磁磚 0.46 吋）
# ══════════════════════════════════════════════════════════════════════════
def p1() -> Image.Image:
    img = canvas(5.10, 5.36)
    d = ImageDraw.Draw(img)
    need = [("terminal", "會用 WSL（本機 Linux 指令）"),
            ("cloud", "會裝 Google GCP（懂 SSH／IP）"),
            ("spark", "會用 DSH 指揮 AI 改程式")]
    dont = [("candle", "不必懂股票"),
            ("sliders", "不必懂策略"),
            ("code", "不必自己寫程式")]

    def card(y, title, items, color, *, badge=None, accent=False):
        h = 0.74 * PX + len(items) * 0.60 * PX
        rr(d, (0.08 * PX, y, 5.02 * PX, y + h), r=18, fill=CARD, outline=BORDER_DIM, width=2)
        txt(img, (0.40 * PX, y + 0.20 * PX), title, 14, color, bold=True)
        for i, (ic, lb) in enumerate(items):
            row(img, (0.40 * PX, y + 0.62 * PX + i * 0.60 * PX), ic, lb,
                pt=16, badge=badge, accent=accent)
        return y + h

    y1 = card(0.02 * PX, "你必須會的", need, ORANGE, accent=True)
    card(y1 + 0.22 * PX, "你不必會的", dont, MUTED, badge="x")
    return img


# ══════════════════════════════════════════════════════════════════════════
# P2 · WSL 終端機 → ssh → GCP 雲端機器（mono 12.5 pt、說明 14 pt）
# ══════════════════════════════════════════════════════════════════════════
def p2() -> Image.Image:
    img = canvas(5.10, 3.66)
    d = ImageDraw.Draw(img)
    # 終端機視窗（整排寬，字才放得大）
    bx = (0.06 * PX, 0.04 * PX, 5.02 * PX, 1.98 * PX)
    rr(d, bx, r=16, fill=(8, 16, 30, 228), outline=BORDER, width=3)
    d.line([bx[0] + 2, bx[1] + 0.38 * PX, bx[2] - 2, bx[1] + 0.38 * PX], fill=BORDER_DIM, width=2)
    for i, c in enumerate(((255, 95, 86), (240, 180, 80), (90, 200, 140))):
        cx0 = bx[0] + 0.26 * PX + i * 0.24 * PX
        d.ellipse([cx0 - 6, bx[1] + 0.19 * PX - 6, cx0 + 6, bx[1] + 0.19 * PX + 6], fill=c + (255,))
    lines = [("$ ", "ls"), ("", "  cache  core  data  strategies"),
             ("$ ", "cd tw-selfselect"), ("$ ", "python selfselect_trader.py")]
    yy = bx[1] + 0.54 * PX
    for pre, cmd in lines:
        if pre:
            txt(img, (bx[0] + 0.20 * PX, yy), pre, 12.5, TEAL, mono=True)
            txt(img, (bx[0] + 0.20 * PX + 0.36 * PX, yy), cmd, 12.5, TEXT, mono=True)
        else:
            txt(img, (bx[0] + 0.20 * PX, yy), cmd, 12.5, MUTED, mono=True)
        yy += 0.34 * PX
    txt(img, (0.06 * PX, 2.10 * PX), "WSL ＝ 本機的 Linux", 15, TEXT, bold=True)
    # ssh 往下接到雲端卡
    ax = 3.05 * PX
    glow(img, lambda dd: arrow(dd, (ax, 2.08 * PX), (ax, 2.42 * PX), ACCENT, 4), radius=6, scale=0.9)
    arrow(d, (ax, 2.08 * PX), (ax, 2.42 * PX), ACCENT, 3)
    txt(img, (ax - 0.12 * PX, 2.18 * PX), "ssh", 12, ACCENT, mono=True, anchor="ra", align="right")
    # 雲端卡（左）＋說明（右）
    rr(d, (0.06 * PX, 2.46 * PX, 3.30 * PX, 3.12 * PX), r=14, fill=(255, 90, 77, 24),
       outline=ACCENT, width=2)
    ccy = 2.79 * PX
    cxc = 0.62 * PX
    for (dx, dy, r) in ((-0.20, 0.07, 0.15), (-0.03, -0.07, 0.20), (0.19, 0.04, 0.14)):
        d.ellipse([cxc + (dx - r) * PX, ccy + (dy - r * 0.74) * PX,
                   cxc + (dx + r) * PX, ccy + (dy + r * 0.74) * PX], outline=BLUE, width=3)
    txt(img, (0.96 * PX, 2.58 * PX), "GCP 雲端機器", 14, TEXT, bold=True)
    txt(img, (0.96 * PX, 2.86 * PX), "固定 IP", 12.5, SOFT)
    txt(img, (1.62 * PX, 2.86 * PX), "35.229.x.x", 12.5, ACCENT, mono=True)
    txt(img, (0.06 * PX, 3.30 * PX), "常用到的只是檔案與目錄指令：ls／cd／cp／rm", 13, MUTED)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P3 · 你出指令 → DSH／AI → 程式改好（泡泡 16 pt、程式碼 mono 12 pt）
# ══════════════════════════════════════════════════════════════════════════
def p3() -> Image.Image:
    img = canvas(5.10, 3.30)
    d = ImageDraw.Draw(img)
    # 你的指令
    bx = (0.06 * PX, 0.24 * PX, 1.72 * PX, 1.52 * PX)
    rr(d, bx, r=16, fill=CARD_HI, outline=BORDER, width=2)
    txt(img, (bx[0] + 0.18 * PX, bx[1] + 0.14 * PX), "你", 12, MUTED, bold=True)
    txt(img, (bx[0] + 0.18 * PX, bx[1] + 0.50 * PX), "把每月選股", 16, TEXT)
    txt(img, (bx[0] + 0.18 * PX, bx[1] + 0.86 * PX), "改成 3 檔", 16, TEXT)
    # AI 磁磚
    tile(img, (1.90 * PX, 0.56 * PX, 2.58 * PX, 1.24 * PX), "spark", accent=True)
    txt(img, (2.24 * PX, 1.32 * PX), "DSH／AI", 12.5, ORANGE, bold=True, anchor="ma")
    # 程式檔堆疊
    for i, off in enumerate((0.12, 0.06, 0.0)):
        rr(d, ((2.95 + off) * PX, (0.16 + off) * PX, (4.96 + off) * PX, (1.86 + off) * PX),
           r=14, fill=(12, 24, 42, 234), outline=BORDER_DIM if i else BORDER, width=2)
    fy = 0.16 * PX
    txt(img, (3.11 * PX, fy + 0.12 * PX), "selfselect_trader.py", 10, MUTED, mono=True)
    d.line([3.05 * PX, fy + 0.40 * PX, 4.86 * PX, fy + 0.40 * PX], fill=BORDER_DIM, width=2)
    for i, (code, col) in enumerate((("TOP_N = 5", MUTED), ("TOP_N = 3", TEAL),
                                     ("def pick(): ...", MUTED))):
        txt(img, (3.11 * PX, fy + 0.54 * PX + i * 0.34 * PX), code, 12, col, mono=True)
    # 結果徽章
    rr(d, (2.95 * PX, 1.98 * PX, 4.96 * PX, 2.44 * PX), r=12, fill=(86, 190, 160, 28),
       outline=TEAL, width=2)
    txt(img, (3.95 * PX, 2.21 * PX), "AI 改好，測試通過", 13.5, TEAL, anchor="mm")
    # 箭頭
    for x0, x1 in ((1.76, 1.86), (2.62, 2.91)):
        arrow(d, (x0 * PX, 0.90 * PX), (x1 * PX, 0.90 * PX), BLUE, 3, head=11)
    txt(img, (0.06 * PX, 2.70 * PX), "82 檔／14,115 行：你不需要自己動它", 13.5, MUTED)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P4 · 每月選股流程（方框標籤 16 pt、副標 12.5 pt）
# ══════════════════════════════════════════════════════════════════════════
def p4() -> Image.Image:
    img = canvas(5.10, 4.12)
    d = ImageDraw.Draw(img)
    CX = 2.55 * PX

    def box(y, h, label, *, sub=None, outline=BORDER, pt=16, accent=False):
        rr(d, (0.45 * PX, y, 4.65 * PX, y + h), r=16, fill=CARD,
           outline=ACCENT if accent else outline, width=3)
        yy = y + h / 2 - (0.17 * PX if sub else 0)
        txt(img, (CX, yy), label, pt, TEXT, bold=True, anchor="ma")
        if sub:
            txt(img, (CX, yy + 0.34 * PX), sub, 12.5, MUTED, anchor="ma")

    box(0.02 * PX, 0.94 * PX, "FinMind／TWSE 資料庫", sub="月營收、法人、股價")
    arrow(d, (CX, 0.98 * PX), (CX, 1.20 * PX), BLUE, 3, head=11)
    box(1.22 * PX, 1.02 * PX, "每月自動選股", sub="選出你指定的 N 檔")
    arrow(d, (CX, 2.26 * PX), (CX, 2.46 * PX), BLUE, 3, head=11)
    box(2.48 * PX, 0.88 * PX, "有合乎標準的股票？", outline=ACCENT, accent=True)
    arrow(d, (CX - 0.62 * PX, 3.38 * PX), (CX - 0.62 * PX, 3.58 * PX), TEAL, 3, head=11)
    txt(img, (CX - 0.50 * PX, 3.42 * PX), "是", 13, TEAL, bold=True)
    arrow(d, (CX + 0.62 * PX, 3.38 * PX), (CX + 0.62 * PX, 3.58 * PX), ORANGE, 3, head=11)
    txt(img, (CX + 0.74 * PX, 3.42 * PX), "否", 13, ORANGE, bold=True)
    rr(d, (0.20 * PX, 3.62 * PX, 2.50 * PX, 4.06 * PX), r=14, fill=CARD, outline=TEAL, width=3)
    txt(img, (1.35 * PX, 3.84 * PX), "買進 N 檔", 15, TEXT, bold=True, anchor="mm")
    rr(d, (2.62 * PX, 3.62 * PX, 4.92 * PX, 4.06 * PX), r=14, fill=CARD, outline=ORANGE, width=3)
    txt(img, (3.77 * PX, 3.84 * PX), "保留現金／買 0050", 14.5, TEXT, bold=True, anchor="mm")
    return img


# ══════════════════════════════════════════════════════════════════════════
# P5 · 四種策略迷你走勢（面板標題 14 pt、說明 12.5 pt）
# ══════════════════════════════════════════════════════════════════════════
def _path(seed: int, n: int = 90, drift: float = 0.0, vol: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y = np.cumsum(rng.normal(drift, vol, n))
    return (y - y.min()) / max(1e-9, y.max() - y.min())


def p5() -> Image.Image:
    img = canvas(5.10, 4.78)
    d = ImageDraw.Draw(img)
    PW, PH = 2.38, 2.16
    panels = [("均線交叉", 0.06, 0.06), ("布林通道", 2.66, 0.06),
              ("VWAP 回歸", 0.06, 2.32), ("突破", 2.66, 2.32)]

    def frame(x, y, title):
        x0, y0 = x * PX, y * PX
        x1, y1 = (x + PW) * PX, (y + PH) * PX
        rr(d, (x0, y0, x1, y1), r=16, fill=(10, 20, 36, 190), outline=BORDER_DIM, width=2)
        txt(img, (x0 + 0.16 * PX, y0 + 0.14 * PX), title, 14, TEXT, bold=True)
        txt(img, (x0 + 0.16 * PX, y1 - 0.46 * PX), "", 1, MUTED)   # 佔位（保持行高一致）
        return x0 + 0.16 * PX, y0 + 0.66 * PX, x1 - 0.16 * PX, y1 - 0.56 * PX

    def plot(pts, ax0, ay0, ax1, ay1, color, width=3, dashed=False):
        xs = np.linspace(ax0, ax1, len(pts))
        ys = ay0 + (1 - pts) * (ay1 - ay0)
        P = list(zip(xs.tolist(), ys.tolist()))
        if dashed:
            for i in range(0, len(P) - 1, 6):
                line(d, P[i:i + 4], color, width)
        else:
            line(d, P, color, width)

    n = 90
    # ① 均線交叉
    ax0, ay0, ax1, ay1 = frame(*panels[0][1:], panels[0][0])
    t = np.linspace(0, 1, n)
    fast = 1 / (1 + np.exp(-(t - 0.58) * 14))
    slow = 1 / (1 + np.exp(-(t - 0.66) * 9))
    plot(fast, ax0, ay0, ax1, ay1, ORANGE, 3)
    plot(slow, ax0, ay0, ax1, ay1, BLUE, 3)
    ix = int(n * 0.62)
    cx = ax0 + (ax1 - ax0) * ix / (n - 1)
    cy = ay0 + (1 - (fast[ix] + 0.02)) * (ay1 - ay0)
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=ACCENT)
    txt(img, (ax0, ay1 + 0.10 * PX), "快線穿過慢線 ⇒ 買", 12.5, TEAL)

    # ② 布林通道
    ax0, ay0, ax1, ay1 = frame(*panels[1][1:], panels[1][0])
    p = _path(7, n, 0.02, 0.55)
    p = p * 0.42 + 0.34
    up, lo = p + 0.24, p - 0.24
    band = list(zip(np.linspace(ax0, ax1, n), ay0 + (1 - up) * (ay1 - ay0))) + \
           list(zip(np.linspace(ax0, ax1, n)[::-1], (ay0 + (1 - lo) * (ay1 - ay0))[::-1]))
    d.polygon([(int(x), int(y)) for x, y in band], fill=(124, 172, 222, 26))
    plot(up, ax0, ay0, ax1, ay1, BORDER, 2)
    plot(lo, ax0, ay0, ax1, ay1, BORDER, 2)
    plot(p, ax0, ay0, ax1, ay1, ORANGE, 3)
    txt(img, (ax0, ay1 + 0.10 * PX), "跌破下軌再回月線 ⇒ 買", 12.5, TEAL)

    # ③ VWAP 回歸
    ax0, ay0, ax1, ay1 = frame(*panels[2][1:], panels[2][0])
    p = _path(21, n, -0.03, 0.6)
    p = p * 0.5 + 0.25
    plot(np.full(n, 0.5), ax0, ay0, ax1, ay1, BLUE, 2, dashed=True)
    plot(np.full(n, 0.74), ax0, ay0, ax1, ay1, BORDER_DIM, 2, dashed=True)
    plot(np.full(n, 0.26), ax0, ay0, ax1, ay1, BORDER_DIM, 2, dashed=True)
    plot(p, ax0, ay0, ax1, ay1, ORANGE, 3)
    k = int(n * 0.34)
    kx = ax0 + (ax1 - ax0) * k / (n - 1)
    ky = ay0 + (1 - p[k]) * (ay1 - ay0)
    d.ellipse([kx - 7, ky - 7, kx + 7, ky + 7], fill=ACCENT)
    txt(img, (ax0, ay1 + 0.10 * PX), "低於均價偏離帶 ⇒ 買", 12.5, TEAL)

    # ④ 突破
    ax0, ay0, ax1, ay1 = frame(*panels[3][1:], panels[3][0])
    p = np.concatenate([np.linspace(0.28, 0.46, 55), np.linspace(0.46, 0.92, 35)])
    rng = np.random.default_rng(3)
    p = np.clip(p + rng.normal(0, 0.028, n), 0, 1)
    plot(p, ax0, ay0, ax1, ay1, ORANGE, 3)
    ty = ay0 + (1 - 0.58) * (ay1 - ay0)
    for i in range(0, 60, 8):
        line(d, [(ax0 + (ax1 - ax0) * i / (n - 1), ty),
                 (ax0 + (ax1 - ax0) * (i + 4) / (n - 1), ty)], BORDER, 2)
    k = 62
    kx = ax0 + (ax1 - ax0) * k / (n - 1)
    ky = ay0 + (1 - p[k]) * (ay1 - ay0)
    d.ellipse([kx - 7, ky - 7, kx + 7, ky + 7], fill=ACCENT)
    txt(img, (ax0, ay1 + 0.10 * PX), "漲過 20 日高 ⇒ 買", 12.5, TEAL)

    txt(img, (0.06 * PX, 4.46 * PX), "程式依各股現況挑 1 種——買入時就決定", 13.5, MUTED)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P6 · 費用：29 杯 vs <1 杯（主數字 17–19 pt、標籤 14 pt）
# ══════════════════════════════════════════════════════════════════════════
def p6() -> Image.Image:
    img = canvas(5.10, 4.10)
    d = ImageDraw.Draw(img)
    # 咖啡杯
    cx, cy = 0.92 * PX, 1.16 * PX
    rr(d, (cx - 0.46 * PX, cy - 0.34 * PX, cx + 0.34 * PX, cy + 0.54 * PX), r=20,
       fill=(16, 30, 50, 235), outline=ORANGE, width=3)
    d.arc([cx + 0.28 * PX, cy - 0.16 * PX, cx + 0.64 * PX, cy + 0.34 * PX],
          start=-70, end=95, fill=ORANGE, width=3)
    d.line([cx - 0.46 * PX, cy - 0.34 * PX, cx + 0.34 * PX, cy - 0.34 * PX],
           fill=(255, 255, 255, 90), width=3)
    for dx in (-0.18, 0.02, 0.22):
        x0 = cx + dx * PX
        line(d, [(x0, cy - 0.46 * PX), (x0 + 7, cy - 0.62 * PX), (x0 - 4, cy - 0.76 * PX)],
             (233, 240, 248, 150), 3)
    txt(img, (cx - 0.06 * PX, cy + 0.66 * PX), "1 杯咖啡", 13, MUTED, anchor="ma")

    BX0, BX1 = 1.86 * PX, 5.02 * PX
    # 授權 29 杯
    txt(img, (BX0, 0.10 * PX), "軟體授權（一次性）", 14, SOFT, bold=True)
    glow(img, lambda dd: rr(dd, (BX0, 0.50 * PX, BX1, 0.96 * PX), r=14, fill=ACCENT),
         radius=9, scale=0.55)
    rr(d, (BX0, 0.50 * PX, BX1, 0.96 * PX), r=14, fill=(255, 90, 77, 238))
    txt(img, (BX1 - 0.16 * PX, 0.73 * PX), "29 杯", 19, (18, 12, 14, 255), bold=True, anchor="rm")
    txt(img, (BX1, 1.06 * PX), "每個帳戶，付一次", 13, MUTED, anchor="ra")

    # GCP 月費 < 1 杯（長條幾乎看不到，差距就是重點）
    d.line([BX0, 2.34 * PX, BX1, 2.34 * PX], fill=BORDER_DIM, width=2)
    txt(img, (BX0, 2.50 * PX), "GCP 月費（每月）", 14, SOFT, bold=True)
    w = (BX1 - BX0) / 29
    rr(d, (BX0, 2.90 * PX, BX0 + max(16, w), 3.34 * PX), r=9, fill=TEAL)
    txt(img, (BX0 + max(16, w) + 0.18 * PX, 3.12 * PX), "不到 1 杯", 17, TEAL, bold=True, anchor="lm")
    txt(img, (BX1, 3.46 * PX), "每月帳單比一杯咖啡便宜", 13, MUTED, anchor="ra")

    txt(img, (0.06 * PX, 3.74 * PX), "沒有訂閱費、沒有顧問費", 15, TEXT, bold=True)
    return img


FIGURES = {1: p1, 2: p2, 3: p3, 4: p4, 5: p5, 6: p6}

# 每頁的擺放位置（吋）：圖已按原吋畫好 ⇒ 直接以原尺寸放，不做縮放
PLACE = {1: (0.55, 0.40), 2: (0.55, 0.70), 3: (0.55, 0.90),
         4: (0.55, 0.66), 5: (0.55, 1.92), 6: (0.55, 0.92)}
ART_NAME = "ART-forwhom"


def draw_all() -> dict[int, Path]:
    ART.mkdir(parents=True, exist_ok=True)
    out = {}
    for n, fn in FIGURES.items():
        img = fn()
        p = ART / f"p{n}.png"
        img.save(p)
        out[n] = p
        print(f"  p{n}: {img.size[0]}×{img.size[1]} px → {p.relative_to(ROOT)}")
    return out


def embed_all() -> None:
    from pptx import Presentation
    from pptx.util import Inches

    BACKUP.mkdir(parents=True, exist_ok=True)
    bak = BACKUP / "for_whom.pptx.bak"
    if not bak.exists():
        shutil.copy2(DECK, bak)
        print(f"  備份原檔 → {bak.relative_to(ROOT)}")

    prs = Presentation(DECK)
    for n, (x, y) in PLACE.items():
        slide = prs.slides[n - 1]
        # 先清掉舊的 ART 圖（可重複執行）
        for sh in list(slide.shapes):
            if sh.name.startswith(ART_NAME):
                sh._element.getparent().remove(sh._element)
        p = ART / f"p{n}.png"
        with Image.open(p) as im:
            w_in, h_in = im.size[0] / PX, im.size[1] / PX
        slide.shapes.add_picture(str(p), Inches(x), Inches(y),
                                 width=Inches(w_in), height=Inches(h_in)).name = f"{ART_NAME}-p{n}"
    prs.save(DECK)
    print(f"  ✅ 已把 6 張圖嵌進 {DECK.relative_to(ROOT)}")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("▶ 畫圖")
    draw_all()
    if cmd != "draw":
        print("▶ 嵌進主檔")
        embed_all()
