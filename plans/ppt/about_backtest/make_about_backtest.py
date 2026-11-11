#!/usr/bin/env python3
"""make_about_backtest.py · 給 `about_backtest/about_backtest.pptx` 重寫文案＋畫 6 張示意圖

背景：`about_backtest.pptx` 是使用者從 `for_who/for_whom.pptx` 複製過來當版型的直式 6 頁短片
（深藍漸層底＋橘紅走勢線），內容還是「適合甚麼人」。本腳本把**版面與文案**一次生成到底，
避免手改 6 頁文字框互相對不齊：

    P1 封面      回測的曲線與實盤的曲線有落差（4 項內容的導覽；P3、P4 同屬「前向驗證」）
    P2 倖存者偏差 回測宇宙只有「今天還活著」的 610 檔，看不到 62 檔下市／被併
    P3 前向驗證   訓練段只往左看、OOS 完全不參與挑參數（擴張式 × 6 輪）
    P4 驗證結果   分年 vs 0050（4/6 勝）＋「換一個參數就掉 382~959pp」的鄰居表
    P5 滑價       訊號看當日收盤、成交也在同一個收盤；換手 24 倍/年 × 0.15% ≈ 3.6%/年
    P6 買不到     左：實盤會、回測永遠不會；右：本專案回測已經算進去的成本與規則

數字全部取自 `results/walk_forward/wf_presets_2020_2025.md` 與 `cairn/backtest-data-pitfalls.md`
（2026-11-05 快照）；改數字時**兩邊一起改**，不要只改圖或只改文字。

⚠️ 字級（沿用 for_who 第二輪的教訓）：圖內最小 12 pt、標籤 13–16 pt、主數字 17–19 pt；
   畫布 200 px ＝ 1 吋 ⇒ 圖內 pt ＝ 畫面上 pt。放大字級要連方框一起放大並重新目視。
   `draw` 會印出「文字超出方框」的警告，有警告就是版面還沒好。

用法：
    .venv/bin/python plans/ppt/about_backtest/make_about_backtest.py         # 畫圖＋改文案＋嵌圖（先備份）
    .venv/bin/python plans/ppt/about_backtest/make_about_backtest.py draw    # 只畫圖（→ about_backtest/art/）
    .venv/bin/python plans/ppt/about_backtest/make_about_backtest.py embed   # 只嵌圖＋改文案
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DECK = ROOT / "plans/ppt/about_backtest/about_backtest.pptx"
ART = ROOT / "plans/ppt/about_backtest/art"
BACKUP = ROOT / "TMP/abt_build"

PX = 200                      # 200 px / inch
REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
TC = 3                        # NotoSansCJK ttc 的繁中字面

# ── 色票（與 make_for_whom_art.py / make_why_design.py 同一家族）────────────
TEXT = (242, 246, 251, 255)
SOFT = (201, 214, 232, 255)
MUTED = (150, 172, 198, 255)
ACCENT = (255, 90, 77, 255)          # 重點紅
ORANGE = (242, 164, 84, 255)         # 琥珀（策略／曲線）
BLUE = (124, 172, 222, 255)          # 冷藍（基準／整段）
TEAL = (86, 190, 160, 255)           # 綠（通過／已內建）
GREY = (108, 126, 148, 255)          # 灰（消失的股票）
CARD = (10, 20, 36, 205)
BORDER = (52, 84, 126, 255)
BORDER_DIM = (40, 64, 96, 255)

_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_WARN: list[str] = []


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


def arrow(d: ImageDraw.ImageDraw, p0, p1, fill, width=3, head=12) -> None:
    line(d, [p0, p1], fill, width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for s in (+1, -1):
        a = ang + s * math.radians(28)
        d.line([(int(p1[0]), int(p1[1])),
                (int(p1[0] - head * math.cos(a)), int(p1[1] - head * math.sin(a)))],
               fill=fill, width=width)


_CMAP: dict[str, set] = {}


def _missing_glyph(ch: str, bold: bool, mono: bool) -> bool:
    """該字在字型裡有沒有字面（沒有就會畫成豆腐方框）。"""
    if mono:
        return False                       # mono 由另一條規則擋（只能純 ASCII）
    key = "b" if bold else "r"
    if key not in _CMAP:
        try:
            from fontTools.ttLib import TTFont
            f = TTFont(BOLD if bold else REG, fontNumber=TC)
            _CMAP[key] = set(f.getBestCmap())
        except Exception:
            _CMAP[key] = set()
    return bool(_CMAP[key]) and ord(ch) not in _CMAP[key]


def txt(img, xy, s, pt, fill=SOFT, *, bold=False, mono=False, anchor="la", align="left",
        fit=None, tag=""):
    """`fit`＝可用寬度（吋）；超出就印警告（畫完才知道版面有沒有爆）。"""
    if mono and any(ord(ch) > 0x2000 for ch in s):
        _WARN.append(f"⚠️ mono 字型沒有中文字面（會變豆腐）：{s!r}")
    bad = [ch for ch in s if _missing_glyph(ch, bold, mono)]
    if bad:
        _WARN.append(f"⚠️ 字型缺字面（會變豆腐）{[f'{c} U+{ord(c):04X}' for c in bad]}：{s}")
    if fit:
        w = F(pt, bold=bold, mono=mono).getlength(s) / PX
        if w > fit:
            _WARN.append(f"⚠️ 文字超出 {w:.2f} > {fit:.2f} 吋：{tag or s}")
    ImageDraw.Draw(img).text((int(xy[0]), int(xy[1])), s, font=F(pt, bold=bold, mono=mono),
                             fill=fill, anchor=anchor, align=align)


def mark_v(d, cx, cy, r, color=TEAL, width=4) -> None:
    """打勾（向量畫，不依賴字型有沒有 ✓）。"""
    line(d, [(cx - r, cy + r * 0.04), (cx - r * 0.28, cy + r * 0.75), (cx + r, cy - r * 0.72)],
         color, width)


def mark_x(d, cx, cy, r, color=ACCENT, width=4) -> None:
    """打叉（向量畫）。"""
    for s in (+1, -1):
        line(d, [(cx - r * 0.8 * s, cy - r * 0.8), (cx + r * 0.8 * s, cy + r * 0.8)], color, width)


def numdot(img, cx, cy, s, r=0.115 * PX, color=ACCENT) -> None:
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    txt(img, (cx, cy), s, 10, (14, 10, 12, 255), bold=True, anchor="mm")


# ══════════════════════════════════════════════════════════════════════════
# 字級基準（2026-11-05 使用者「圖型內的字還是太小加大些」）
#   最小 14 pt（刻度／註腳）｜說明 15–16 pt｜面板標題 18–19 pt｜主數字 19–24 pt
#   ⚠️ 加大字級時方框、行距、畫布高度要一起放大，改完一定重跑（draw 會回報溢位）
# ══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
# P1 · 封面：回測曲線 vs 實盤曲線的落差 ＋ 4 項導覽（P3、P4 同屬第 2 項）
# ══════════════════════════════════════════════════════════════════════════
def p1() -> Image.Image:
    img = canvas(5.10, 5.25)
    d = ImageDraw.Draw(img)
    rr(d, (0.04 * PX, 0.06 * PX, 5.06 * PX, 2.80 * PX), r=16,
       fill=(8, 16, 30, 175), outline=BORDER_DIM, width=2)
    x0, x1, y0, y1 = 0.18 * PX, 4.18 * PX, 0.36 * PX, 2.54 * PX
    line(d, [(x0, y1), (x1, y1)], BORDER_DIM, 2)
    n = 120
    bt = [0.06 + 0.80 * (i / (n - 1)) ** 0.92 for i in range(n)]
    rng = [0.03, -0.05, 0.04, -0.03, 0.05, -0.04, 0.02, -0.06, 0.03, -0.02, 0.04, -0.05]
    lv, v = [], 0.10
    for i in range(n):
        v += 0.0042 + rng[i % len(rng)] * 0.35 * (0.4 + 0.6 * i / (n - 1))
        lv.append(max(0.02, min(0.62, v)))

    def curve(values, color, width=4):
        pts = [(x0 + (x1 - x0) * i / (n - 1), y0 + (1 - values[i]) * (y1 - y0)) for i in range(n)]
        line(d, pts, color, width)
        return pts

    pb = curve(bt, ORANGE, 5)
    pl = curve(lv, BLUE, 4)
    ex, ey_b, ey_l = pb[-1][0], pb[-1][1], pl[-1][1]
    arrow(d, (ex + 0.16 * PX, ey_l - 8), (ex + 0.16 * PX, ey_b + 12), ACCENT, 3, head=10)
    txt(img, (ex + 0.28 * PX, (ey_b + ey_l) / 2), "落差", 15, ACCENT, bold=True,
        anchor="lm", fit=0.60)
    d.ellipse([ex - 9, ey_b - 9, ex + 9, ey_b + 9], fill=ORANGE)
    d.ellipse([ex - 9, ey_l - 9, ex + 9, ey_l + 9], fill=BLUE)
    txt(img, (ex - 0.16 * PX, ey_b - 0.32 * PX), "回測", 16, ORANGE, bold=True, anchor="ra")
    txt(img, (ex - 0.16 * PX, ey_l + 0.14 * PX), "實盤", 16, BLUE, bold=True, anchor="ra")

    chips = [("1", "倖存者偏差", "被消失的股票"),
             ("2", "前向驗證", "兩頁：方法＋結果"),
             ("3", "滑價", "零成本成交"),
             ("4", "買不到", "停牌／漲跌停")]
    for i, (num, title, sub) in enumerate(chips):
        cx = 0.04 + (i % 2) * 2.54
        cy = 2.92 + (i // 2) * 1.02
        rr(d, (cx * PX, cy * PX, (cx + 2.48) * PX, (cy + 0.94) * PX), r=16,
           fill=CARD, outline=BORDER_DIM, width=2)
        numdot(img, (cx + 0.34) * PX, (cy + 0.36) * PX, num, r=0.19 * PX)
        txt(img, ((cx + 0.68) * PX, (cy + 0.14) * PX), title, 19, TEXT, bold=True, fit=1.72)
        txt(img, ((cx + 0.68) * PX, (cy + 0.58) * PX), sub, 14.5, MUTED, fit=1.74)
    txt(img, (0.04 * PX, 4.92 * PX), "對應頁次：P2／P3-P4／P5／P6", 15, MUTED, fit=4.9)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P2 · 倖存者偏差：活著的 610 檔 vs 被消失的 62 檔
# ══════════════════════════════════════════════════════════════════════════
def _mini_candles(img, box, alive=True, n=6) -> None:
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    span = (x1 - x0) / n
    heights = [0.52, 0.66, 0.44, 0.72, 0.58, 0.68]
    col = TEAL if alive else GREY
    for i in range(n):
        cx = x0 + span * (i + 0.5)
        hh = heights[i % len(heights)] * (y1 - y0)
        top = y1 - hh
        d.line([cx, top - 0.09 * PX, cx, y1 - 0.02 * PX], col, 3)
        bw = span * 0.20
        d.rectangle([cx - bw, top, cx + bw, y1 - 0.06 * PX], outline=col, width=3)
        if not alive:
            mark_x(d, cx, (top + y1) / 2, span * 0.34, ACCENT, 4)


def p2() -> Image.Image:
    img = canvas(5.10, 4.70)
    d = ImageDraw.Draw(img)
    rr(d, (0.04 * PX, 0.04 * PX, 2.30 * PX, 2.06 * PX), r=16, fill=CARD, outline=TEAL, width=3)
    txt(img, (0.22 * PX, 0.14 * PX), "今天的股市", 19, TEXT, bold=True, fit=1.9)
    txt(img, (0.22 * PX, 0.54 * PX), "610 檔還活著", 16, TEAL, bold=True, fit=1.9)
    _mini_candles(img, (0.22 * PX, 1.00 * PX, 2.12 * PX, 1.92 * PX), alive=True)

    rr(d, (2.74 * PX, 0.04 * PX, 5.06 * PX, 2.06 * PX), r=16, fill=(22, 14, 22, 215),
       outline=ACCENT, width=3)
    txt(img, (2.92 * PX, 0.14 * PX), "回測宇宙裡沒有", 19, TEXT, bold=True, fit=2.10)
    txt(img, (2.92 * PX, 0.54 * PX), "62 檔已下市／被併", 16, ACCENT, bold=True, fit=2.0)
    _mini_candles(img, (2.92 * PX, 1.00 * PX, 4.88 * PX, 1.92 * PX), alive=False)

    arrow(d, (2.36 * PX, 1.04 * PX), (2.68 * PX, 1.04 * PX), MUTED, 3, head=10)

    rr(d, (0.04 * PX, 2.20 * PX, 5.06 * PX, 3.46 * PX), r=14, fill=(255, 90, 77, 22),
       outline=ACCENT, width=2)
    txt(img, (0.20 * PX, 2.30 * PX), "2016-01 市值前 5 名 — 後來全部下市或被併", 16,
        ACCENT, bold=True, fit=4.7)
    txt(img, (0.20 * PX, 2.72 * PX), "6452 康友-KY　2325 矽品　1704 榮化", 16, SOFT, fit=4.7)
    txt(img, (0.20 * PX, 3.06 * PX), "3474 華亞科　2311 日月光", 16, SOFT, fit=4.7)

    rr(d, (0.04 * PX, 3.56 * PX, 2.46 * PX, 4.64 * PX), r=12, fill=CARD, outline=BORDER, width=2)
    txt(img, (0.18 * PX, 3.64 * PX), "池 150＋營收＋上限2", 14, MUTED, fit=2.2)
    txt(img, (0.18 * PX, 3.90 * PX), "+1289.5%", 18, SOFT, bold=True, fit=2.2)
    txt(img, (0.18 * PX, 4.18 * PX), "→ +1070.5%", 18, ACCENT, bold=True, fit=2.2)
    rr(d, (2.64 * PX, 3.56 * PX, 5.06 * PX, 4.64 * PX), r=12, fill=CARD, outline=BORDER, width=2)
    txt(img, (2.78 * PX, 3.64 * PX), "池 20", 14, MUTED, fit=2.2)
    txt(img, (2.78 * PX, 3.90 * PX), "+369.4%", 18, SOFT, bold=True, fit=2.2)
    txt(img, (2.78 * PX, 4.18 * PX), "→ +395.1%", 18, TEAL, bold=True, fit=2.2)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P3 · 前向驗證（walk-forward）時間軸
# ══════════════════════════════════════════════════════════════════════════
WF = [(2020, "+59.2%", True), (2021, "+103.0%", True), (2022, "-29.9%", False),
      (2023, "+116.5%", True), (2024, "+16.2%", False), (2025, "+38.2%", True)]


def p3() -> Image.Image:
    img = canvas(5.10, 4.20)
    d = ImageDraw.Draw(img)
    X0, X1 = 0.42 * PX, 3.94 * PX                # 2016 → 2026

    def X(year: float) -> float:
        return X0 + (X1 - X0) * (year - 2016) / 10.0

    for yr in (2016, 2018, 2020, 2022, 2024, 2026):
        line(d, [(X(yr), 0.56 * PX), (X(yr), 3.34 * PX)], (36, 56, 82, 255), 1)
        txt(img, (X(yr), 3.42 * PX), str(yr), 14, MUTED, anchor="ma")
    txt(img, (4.14 * PX, 0.34 * PX), "OOS", 15, ORANGE, bold=True, anchor="lm")
    for i, (yr, oos, win) in enumerate(WF):
        y = (0.86 + i * 0.44) * PX
        txt(img, (0.04 * PX, y), f"輪{i + 1}", 15, MUTED, anchor="lm")
        rr(d, (X(2016), y - 0.13 * PX, X(yr) - 0.03 * PX, y + 0.13 * PX), r=6,
           fill=(124, 172, 222, 70), outline=BLUE, width=2)
        rr(d, (X(yr), y - 0.16 * PX, X(yr + 1) - 0.03 * PX, y + 0.16 * PX), r=6,
           fill=(242, 166, 84, 235), outline=ORANGE, width=2)
        txt(img, (4.14 * PX, y), oos, 14, TEAL if win else ACCENT, bold=True, mono=True,
            anchor="lm", fit=0.86)
    xr = X(2026) + 0.02 * PX
    line(d, [(xr, 0.56 * PX), (xr, 3.34 * PX)], ACCENT, 3)
    txt(img, (xr - 0.04 * PX, 0.36 * PX), "不能往右看", 15, ACCENT, bold=True, anchor="ra")
    txt(img, (0.04 * PX, 3.80 * PX), "藍＝只用過去挑參數　橘＝完全不參與挑選的那一年", 14.5,
        MUTED, fit=4.9)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P4 · 驗證結果：分年 vs 0050 ＋ 參數鄰居表
# ══════════════════════════════════════════════════════════════════════════
YEARLY = [(2020, 59.2, 29.3), (2021, 103.0, 19.0), (2022, -29.9, -22.2),
          (2023, 116.5, 26.0), (2024, 16.2, 48.2), (2025, 38.2, 37.1)]
NEIGH = [("最佳組", 1323.6),
         ("只換上限 2→0", 940.9),
         ("只換池 150→100", 756.6),
         ("只換池 150→20", 389.5),
         ("關掉營收因子", 364.2)]


def p4() -> Image.Image:
    img = canvas(5.10, 4.90)
    d = ImageDraw.Draw(img)
    # ── 上：分年柱狀（橘＝策略 藍＝0050）──
    TOPV, BOTV = 120.0, -35.0
    CY0, CY1 = 0.58 * PX, 2.24 * PX
    yz = CY0 + TOPV / (TOPV - BOTV) * (CY1 - CY0)
    SC = (CY1 - CY0) / (TOPV - BOTV)

    def yy(v):
        return yz - v * SC

    txt(img, (0.04 * PX, 0.00 * PX), "分年報酬（橘＝策略　藍＝0050）", 16, SOFT, bold=True, fit=4.90)
    gw = (4.86 - 0.54) / 6
    for i, (yr, st, bm) in enumerate(YEARLY):
        cxi = 0.54 + gw * (i + 0.5)
        for j, (val, col) in enumerate(((st, ORANGE), (bm, BLUE))):
            bx = (cxi + (j - 0.5) * 0.235) * PX
            y0, y1 = sorted((yz, yy(val)))
            rr(d, (bx - 0.085 * PX, y0, bx + 0.085 * PX, max(y1, y0 + 4)), r=3, fill=col)
        vy = yy(st)
        lab = f"{st:+.1f}"
        lx = (cxi - 0.12) * PX
        if st >= 0:
            txt(img, (lx, vy - 0.05 * PX), lab, 13.5, SOFT, mono=True, anchor="mb", fit=0.72)
        else:
            txt(img, (lx, vy + 0.05 * PX), lab, 13.5, ACCENT, mono=True, anchor="mt", fit=0.72)
        txt(img, (cxi * PX, 2.34 * PX), str(yr)[2:], 14.5, MUTED, anchor="ma")
    line(d, [(0.50 * PX, yz), (5.00 * PX, yz)], BORDER, 2)
    txt(img, (0.48 * PX, yz), "0", 13.5, MUTED, anchor="rm")

    # ── 下：參數鄰居表 ──
    line(d, [(0.04 * PX, 2.60 * PX), (5.06 * PX, 2.60 * PX)], BORDER_DIM, 2)
    txt(img, (0.04 * PX, 2.68 * PX), "最佳＝池150＋營收＋上限2；以下只換一個參數", 15,
        SOFT, bold=True, fit=4.9)
    for i, (label, val) in enumerate(NEIGH):
        y = (3.08 + i * 0.30) * PX
        txt(img, (0.04 * PX, y), label, 15, TEXT if i == 0 else MUTED, anchor="lm", fit=2.10)
        w = val / NEIGH[0][1] * 1.80
        rr(d, (2.22 * PX, y - 0.11 * PX, (2.22 + w) * PX, y + 0.11 * PX), r=4,
           fill=ORANGE if i == 0 else BLUE)
        txt(img, (5.02 * PX, y), f"+{val:.1f}%", 14, ACCENT if i == 0 else SOFT,
            mono=True, bold=(i == 0), anchor="rm", fit=0.96)
    txt(img, (0.04 * PX, 4.48 * PX), "⇒ 換一個參數就掉 382～959pp", 16, ACCENT, bold=True, fit=4.9)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P5 · 滑價：訊號與成交同一個收盤價 ＋ 換手成本
# ══════════════════════════════════════════════════════════════════════════
def p5() -> Image.Image:
    img = canvas(5.10, 3.85)
    d = ImageDraw.Draw(img)
    # ── 左：K 棒與兩個成交價（① 回測 ② 實盤）──
    rr(d, (0.04 * PX, 0.04 * PX, 2.46 * PX, 3.64 * PX), r=16, fill=(8, 16, 30, 175),
       outline=BORDER_DIM, width=2)
    cx = 1.30 * PX
    line(d, [(cx, 0.28 * PX), (cx, 2.02 * PX)], GREY, 4)
    rr(d, (cx - 0.20 * PX, 0.76 * PX, cx + 0.20 * PX, 1.62 * PX), r=4,
       fill=(255, 90, 77, 40), outline=ACCENT, width=4)
    y_close, y_fill = 1.62 * PX, 1.62 * PX - 0.34 * PX
    for yv, col in ((y_fill, ACCENT), (y_close, ORANGE)):
        for seg in ((0.18 * PX, 0.80 * PX), (1.80 * PX, 2.30 * PX)):
            line(d, [(seg[0], yv), (seg[1], yv)], col, 2)
    d.ellipse([cx - 8, y_close - 8, cx + 8, y_close + 8], fill=ORANGE)
    d.ellipse([cx - 8, y_fill - 8, cx + 8, y_fill + 8], fill=ACCENT)
    numdot(img, cx + 0.38 * PX, y_fill, "2", r=0.13 * PX)
    numdot(img, cx + 0.38 * PX, y_close, "1", r=0.13 * PX)
    arrow(d, (cx - 0.34 * PX, y_fill + 6), (cx - 0.34 * PX, y_close - 6), ACCENT, 2, head=8)
    numdot(img, 0.28 * PX, 2.24 * PX, "1", r=0.12 * PX, color=ORANGE)
    txt(img, (0.50 * PX, 2.24 * PX), "回測：用收盤價成交", 15, ORANGE, anchor="lm", fit=1.90)
    numdot(img, 0.28 * PX, 2.66 * PX, "2", r=0.12 * PX)
    txt(img, (0.50 * PX, 2.64 * PX), "實盤：不知道成交價", 15, ACCENT, anchor="lm", fit=1.90)
    txt(img, (0.50 * PX, 3.02 * PX), "成交價（就是滑價）", 15, ACCENT, fit=1.90)

    # ── 右：成本三格 ＋ 算式 ──
    items = [("手續費 0.1425%", TEAL, "v"), ("證交稅 0.3%", TEAL, "v"), ("滑價 0", ACCENT, "x")]
    for i, (label, col, kind) in enumerate(items):
        y = 0.04 + i * 0.64
        rr(d, (2.60 * PX, y * PX, 5.06 * PX, (y + 0.54) * PX), r=12, fill=CARD, outline=col, width=2)
        if kind == "v":
            mark_v(d, 2.86 * PX, (y + 0.27) * PX, 0.095 * PX, TEAL, 5)
        else:
            mark_x(d, 2.86 * PX, (y + 0.27) * PX, 0.085 * PX, ACCENT, 5)
        txt(img, (3.10 * PX, (y + 0.27) * PX), label, 16, TEXT, bold=True, anchor="lm", fit=1.90)
    txt(img, (2.60 * PX, 1.98 * PX), "✓＝已內建　×＝沒算", 14, MUTED, fit=2.44)

    rr(d, (2.60 * PX, 2.32 * PX, 5.06 * PX, 3.44 * PX), r=14, fill=(255, 90, 77, 26),
       outline=ACCENT, width=3)
    txt(img, (2.76 * PX, 2.42 * PX), "每月全部換手", 15, MUTED, fit=2.2)
    txt(img, (2.76 * PX, 2.68 * PX), "24 倍/年 × 0.15%", 18, ACCENT, bold=True, fit=2.2)
    txt(img, (2.76 * PX, 2.98 * PX), "≈ 每年 3.6%", 21, ACCENT, bold=True, fit=2.2)
    txt(img, (2.60 * PX, 3.54 * PX), "先打折，再看結論", 15, SOFT, fit=2.44)
    return img


# ══════════════════════════════════════════════════════════════════════════
# P6 · 買不到（左）vs 回測已內建（右）
# ══════════════════════════════════════════════════════════════════════════
CANNOT = ["漲跌停鎖死買不到", "停牌／暫停交易", "量太小買不到足額",
          "零股／整張限制", "限價單掛不到", "T+2 交割錢未到"]
MODELLED = ["手續費 0.1425%", "證交稅 0.3%", "大盤年線濾網 MA200", "下市宇宙 672 檔",
            "PER 資格／月營收", "暖機不足就不選", "股災防護＋硬停損"]


def p6() -> Image.Image:
    img = canvas(5.10, 5.02)
    d = ImageDraw.Draw(img)
    rr(d, (0.04 * PX, 0.04 * PX, 2.28 * PX, 4.80 * PX), r=16, fill=(24, 12, 18, 210),
       outline=ACCENT, width=3)
    txt(img, (0.18 * PX, 0.14 * PX), "實盤會發生", 19, ACCENT, bold=True, fit=1.95)
    txt(img, (0.18 * PX, 0.52 * PX), "回測永遠不會", 15, MUTED, fit=1.95)
    for i, s in enumerate(CANNOT):
        y = (1.02 + i * 0.60) * PX
        mark_x(d, 0.36 * PX, y, 0.085 * PX, ACCENT, 4)
        txt(img, (0.56 * PX, y), s, 14.5, SOFT, anchor="lm", fit=1.66)

    rr(d, (2.36 * PX, 0.04 * PX, 5.06 * PX, 4.80 * PX), r=16, fill=(10, 24, 34, 210),
       outline=TEAL, width=3)
    txt(img, (2.52 * PX, 0.14 * PX), "回測已經算進去", 19, TEAL, bold=True, fit=2.45)
    txt(img, (2.52 * PX, 0.52 * PX), "本專案現在的設定", 15, MUTED, fit=2.45)
    for i, s in enumerate(MODELLED):
        y = (1.06 + i * 0.46) * PX
        mark_v(d, 2.68 * PX, y, 0.080 * PX, TEAL, 4)
        txt(img, (2.92 * PX, y), s, 14.5, SOFT, anchor="lm", fit=2.06)
    txt(img, (2.52 * PX, 4.42 * PX), "仍未計：滑價、平倉成本", 14, ACCENT, fit=2.40)
    return img


FIGURES = {1: p1, 2: p2, 3: p3, 4: p4, 5: p5, 6: p6}

COL = {"t": "F2F6FB", "soft": "DDE7F2", "accent": "FF5A4D", "muted": "5E7189", "teal": "56BEA0"}
PAGES = {
    1: {"art": (0.58, 5.25), "bar": True,
        "title": [("TW-SelfSelect", 34, "t", True), ("回測怎麼看", 34, "t", True)],
        "lines": [("4 件最容易被回測騙的事", 19, "soft", False),
                  ("每一件，本專案都真的踩過也量過", 17, "muted", False)],
        "notes": "⏱ 約 12 秒\n【旁白】回測可以讓一個策略看起來很賺，但有四件事會讓它比實盤好看。\n"
                 "【畫面】標題＋回測與實盤曲線的落差"},
    2: {"art": (0.58, 4.70),
        "title": [("倖存者偏差", 30, "t", True)],
        "lines": [("只回測「今天還活著」的股票", 22, "t", False),
                  ("等於先偷看誰會倒、誰會被併", 22, "t", False),
                  ("宇宙 610 → 672 檔", 20, "accent", True)],
        "notes": "⏱ 約 22 秒\n【旁白】只回測今天還活著的股票，等於先偷看誰會倒。我們把 62 檔下市股補回宇宙。"
                 "補完不一定變好也不一定變差，大池下修、小池上修，所以一定要重跑。\n"
                 "【畫面】610 檔活著／62 檔被消失；2016-01 前 5 名全部下市"},
    3: {"art": (0.58, 4.20),
        "title": [("前向驗證 Forward test", 30, "t", True)],
        "lines": [("回測看過的資料，不能再拿來挑參數", 22, "t", False),
                  ("只用過去挑，隔年才看結果", 22, "t", False),
                  ("擴張式訓練段 × 6 輪，完全不參與挑選", 20, "accent", True)],
        "notes": "⏱ 約 20 秒\n【旁白】回測看過的資料不能再拿來挑參數。前向驗證是只用過去挑，隔年才看。我們做了六輪。\n"
                 "【畫面】時間軸：藍色訓練段越來越長、橘色 OOS 一格一年"},
    4: {"art": (0.58, 4.90),
        "title": [("我們的前向驗證結果", 30, "t", True)],
        "lines": [("6 輪串接 +687.7%｜0050 +206.4%", 22, "t", False),
                  ("4 勝 2 負（輸 2022、2024）", 22, "t", False),
                  ("六輪都挑回同一組 ⇒ 尖峰不是平台", 20, "accent", True)],
        "notes": "⏱ 約 25 秒\n【旁白】結果四勝兩負，串接 +687.7% 對 0050 的 +206.4%。"
                 "但六輪都挑回同一組，而且換一個參數就掉 382 到 959 個百分點，所以它是尖峰、不是平台。\n"
                 "【畫面】分年長條＋參數鄰居表"},
    5: {"art": (0.58, 3.85),
        "title": [("滑價：回測沒有這一段", 30, "t", True)],
        "lines": [("訊號看當日收盤，成交也用同一個收盤", 21, "t", False),
                  ("換手 24 倍/年 × 0.15% ≈ 每年 3.6%", 21, "t", False),
                  ("結論要先打折，還站得住才可信", 20, "accent", True)],
        "notes": "⏱ 約 20 秒\n【旁白】回測是看當日收盤、也用當日收盤成交，實盤做不到。"
                 "每月全部換手，一年 24 倍乘 0.15%，大約每年 3.6%。\n"
                 "【畫面】K 棒上的兩個成交價；右邊三個成本格"},
    6: {"art": (0.58, 5.01),
        "title": [("買不到：實盤會、回測不會", 30, "t", True)],
        "lines": [("左邊 6 種狀況，模擬永遠不會遇到", 21, "t", False),
                  ("右邊是本專案回測已經算進去的", 21, "teal", True),
                  ("仍未計：滑價、期末平倉成本", 18, "muted", False)],
        "notes": "⏱ 約 22 秒\n【旁白】漲跌停、停牌、量不夠、限價沒成交，這些模擬永遠不會遇到。"
                 "右邊是我們已經算進回測的成本與規則；滑價和期末平倉成本還沒算。\n"
                 "【畫面】左紅✕、右綠✓"},
}
ART_NAME = "ART-abt"


def draw_all() -> dict[int, Path]:
    ART.mkdir(parents=True, exist_ok=True)
    _WARN.clear()
    out = {}
    for n, fn in FIGURES.items():
        img = fn()
        p = ART / f"p{n}.png"
        img.save(p)
        out[n] = p
        print(f"  p{n}: {img.size[0]}×{img.size[1]} px "
              f"({img.size[0] / PX:.2f}×{img.size[1] / PX:.2f} 吋) → {p.relative_to(ROOT)}")
    if _WARN:
        print("\n".join("  " + w for w in _WARN))
    else:
        print("  ✅ 沒有文字超出方框的警告")
    return out


def _check_width(text: str, size: float, bold: bool, limit_in: float) -> None:
    """投影片文字會不會換行：用 Noto 量（LibreOffice 對 CJK 的字寬與它一致）。

    2026-11-05 實際踩到：文字框有 0.1 吋內縮 + 一行塞不下 ⇒ LibreOffice 折成兩行，
    下一行沒跟著下移就**疊字**（P3 第一行壓在第二行上）。⇒ 內縮歸零、加寬、並在這裡量。
    """
    w = F(size, bold=bold).getlength(text) / PX
    if w > limit_in:
        _WARN.append(f"⚠️ 投影片文字會換行（{w:.2f} > {limit_in:.2f} 吋）：{text}")


def _font(run, size, bold, color, name="Noto Sans CJK TC") -> None:
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from pptx.util import Pt

    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {})
            rPr.append(e)
        e.set("typeface", name)


def embed_all() -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches

    BACKUP.mkdir(parents=True, exist_ok=True)
    bak = BACKUP / "about_backtest.pptx.bak"
    if not bak.exists():
        shutil.copy2(DECK, bak)
        print(f"  備份原檔 → {bak.relative_to(ROOT)}")

    prs = Presentation(DECK)
    sw = prs.slide_width
    for n, slide in enumerate(prs.slides, 1):
        spec = PAGES[n]
        bg = None
        for sh in slide.shapes:                     # 保留滿版背景圖
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE and sh.width >= sw * 0.98:
                bg = sh
                break
        # ⚠️ 要比 _element（python-pptx 每次存取 shapes 都回新的 proxy 物件，
        #    `sh is bg` 永遠是 False ⇒ 連背景圖都會被砍掉、整頁變白底）
        keep = bg._element if bg is not None else None
        for sh in list(slide.shapes):               # 其餘全部重建 ⇒ 可重複執行
            if sh._element is not keep:
                sh._element.getparent().remove(sh._element)

        art_top, art_h = spec["art"]
        y = art_top + art_h + 0.28
        if spec.get("bar"):
            bar = slide.shapes.add_shape(1, Inches(0.55), Inches(y), Inches(2.05), Inches(0.10))
            bar.fill.solid()
            bar.fill.fore_color.rgb = RGBColor.from_string(COL["accent"])
            bar.line.fill.background()
            bar.name = "ACCENT-bar"
            y += 0.28

        for i, (text, size, color, bold) in enumerate(spec["title"]):
            tb = slide.shapes.add_textbox(Inches(0.52), Inches(y), Inches(5.30), Inches(0.62))
            tb.name = f"TXT-title-{i + 1}"
            tf = tb.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.TOP
            for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                setattr(tf, m, 0)
            _check_width(text, size, bold, 5.26)
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            run = p.add_run()
            run.text = text
            _font(run, size, bold, COL[color] if color in COL else color)
            y += size * 0.0215

        y += 0.14
        for i, (text, size, color, bold) in enumerate(spec["lines"]):
            tb = slide.shapes.add_textbox(Inches(0.55), Inches(y), Inches(5.28), Inches(0.64))
            tb.name = f"TXT-line-{i + 1}"
            tf = tb.text_frame
            tf.word_wrap = True
            for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                setattr(tf, m, 0)
            _check_width(text, size, bold, 5.24)
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            run = p.add_run()
            run.text = text
            _font(run, size, bold, COL[color] if color in COL else color)
            y += size * 0.0235

        pn = slide.shapes.add_textbox(Inches(0), Inches(10.40), Inches(6.20), Inches(0.32))
        pn.name = "TXT-pageno"
        p = pn.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = f"{n:02d} / 06"
        _font(run, 10.5, False, COL["muted"])

        img_path = ART / f"p{n}.png"
        with Image.open(img_path) as im:
            w_in, h_in = im.size[0] / PX, im.size[1] / PX
        slide.shapes.add_picture(str(img_path), Inches(0.55), Inches(art_top),
                                 width=Inches(w_in), height=Inches(h_in)).name = f"{ART_NAME}-p{n}"

        slide.notes_slide.notes_text_frame.text = spec["notes"]

    prs.save(DECK)
    if _WARN:
        print("\n".join("  " + w for w in _WARN))
    print(f"  ✅ 已重寫 6 頁文案並嵌入 6 張圖 → {DECK.relative_to(ROOT)}")


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("▶ 畫圖")
    draw_all()
    if cmd != "draw":
        print("▶ 改文案＋嵌圖")
        embed_all()
