#!/usr/bin/env python3
"""why_icons.py · `make_why_design.py` 用的扁平線條圖示庫（Pillow 現畫，無版權問題）

每顆圖示＝圓角磁磚底（深藍 60%）＋細紅框＋白色/紅色線條字形，輸出 256×256 PNG（透明底）。
用法：
    from why_icons import icon
    p = icon("chip", out_dir=…, color=ACCENT)      # → Path
座標一律用 0~1 正規化，畫布 256×256，線寬 14px ⇒ 縮到 0.44 吋仍清楚。
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 256                      # 畫布
LW = 14                      # 主線寬
TILE_FILL = (18, 32, 52, 216)
TILE_LINE = (255, 90, 77, 105)
GLYPH = (255, 255, 255, 255)
ACCENT = (255, 90, 77, 255)
MUTED = (150, 176, 206, 255)


def _p(*xy: float) -> tuple[float, float]:
    """0~1 → 像素。"""
    return (xy[0] * S, xy[1] * S)


def _line(d, xy, fill=None, w=LW):
    d.line([_p(xy[i], xy[i + 1]) for i in range(0, len(xy), 2)],
           fill=fill or GLYPH, width=w, joint="curve")


def _arc(d, box, start, end, fill=None, w=LW):
    d.arc([_p(box[0], box[1]), _p(box[2], box[3])], start, end, fill=fill or GLYPH, width=w)


def _circle(d, cx, cy, r, fill=None, w=LW):
    d.ellipse([_p(cx - r, cy - r), _p(cx + r, cy + r)], outline=fill or GLYPH, width=w)


def _rrect(d, box, r=0.06, fill=None, w=LW):
    d.rounded_rectangle([_p(box[0], box[1]), _p(box[2], box[3])], radius=int(r * S),
                        outline=fill or GLYPH, width=w)


def _dot(d, cx, cy, r=0.028, fill=None):
    d.ellipse([_p(cx - r, cy - r), _p(cx + r, cy + r)], fill=fill or GLYPH)


def _badge_x(d):
    """右下角紅色 ✕ 徽章（代表「不要／不能」，不遮主字形）。"""
    cx, cy, r = 0.735, 0.735, 0.145
    d.ellipse([_p(cx - r, cy - r), _p(cx + r, cy + r)], fill=ACCENT)
    k = 0.055
    d.line([_p(cx - k, cy - k), _p(cx + k, cy + k)], fill=(12, 22, 36, 255), width=9)
    d.line([_p(cx + k, cy - k), _p(cx - k, cy + k)], fill=(12, 22, 36, 255), width=9)


def _glyph_text(d, ch: str, size=0.40, fill=None, font_path: Path | None = None):
    px = int(size * S)
    fp = str(font_path) if font_path else None
    font = ImageFont.truetype(fp, px) if fp else ImageFont.load_default()
    box = d.textbbox((0, 0), ch, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((S - tw) / 2 - box[0], (S - th) / 2 - box[1]), ch, font=font, fill=fill or GLYPH)


# ── 字形 ──────────────────────────────────────────────────────────────
def _chip(d, **kw):
    _rrect(d, (0.30, 0.30, 0.70, 0.70), r=0.07)
    _rrect(d, (0.42, 0.42, 0.58, 0.58), r=0.03, w=LW - 3)
    for i in (0.38, 0.50, 0.62):
        d.line([_p(i, 0.30), _p(i, 0.20)], fill=GLYPH, width=10)
        d.line([_p(i, 0.70), _p(i, 0.80)], fill=GLYPH, width=10)
        d.line([_p(0.30, i), _p(0.20, i)], fill=GLYPH, width=10)
        d.line([_p(0.70, i), _p(0.80, i)], fill=GLYPH, width=10)


def _coins(d, **kw):
    for k, cy in enumerate((0.66, 0.55, 0.44)):
        d.ellipse([_p(0.24, cy - 0.055), _p(0.50, cy + 0.055)], outline=GLYPH, width=11)
    _line(d, (0.24, 0.66, 0.24, 0.55), w=11)
    _line(d, (0.50, 0.66, 0.50, 0.44), w=11)
    # 上升箭頭
    _line(d, (0.58, 0.62, 0.58, 0.32), fill=ACCENT)
    _line(d, (0.46, 0.44, 0.58, 0.31), fill=ACCENT)
    _line(d, (0.70, 0.44, 0.58, 0.31), fill=ACCENT)


def _tag(d, **kw):
    d.polygon([_p(0.30, 0.34), _p(0.56, 0.34), _p(0.72, 0.50), _p(0.44, 0.78), _p(0.28, 0.62)],
              outline=GLYPH, width=LW)
    _circle(d, 0.58, 0.44, 0.028, w=6)


def _person(d, **kw):
    _circle(d, 0.50, 0.40, 0.10)
    _arc(d, (0.28, 0.52, 0.72, 0.94), 180, 360)


def _gauge(d, **kw):
    _arc(d, (0.26, 0.30, 0.74, 0.78), 160, 380)
    for deg in (160, 250, 340, 20):
        a = math.radians(deg)
        r0, r1 = 0.20, 0.155
        d.line([_p(0.50 + r0 * math.cos(a), 0.54 + r0 * math.sin(a)),
                _p(0.50 + r1 * math.cos(a), 0.54 + r1 * math.sin(a))],
               fill=MUTED, width=8)
    a = math.radians(-40)
    _line(d, (0.50, 0.54, 0.50 + 0.14 * math.cos(a), 0.54 + 0.14 * math.sin(a)), fill=ACCENT)
    _dot(d, 0.50, 0.54, 0.028, fill=ACCENT)


def _chart_x(d, **kw):
    _line(d, (0.26, 0.66, 0.40, 0.54, 0.52, 0.60, 0.66, 0.40, 0.74, 0.34), fill=MUTED, w=11)
    _line(d, (0.42, 0.72, 0.62, 0.52), fill=ACCENT)
    _line(d, (0.62, 0.72, 0.42, 0.52), fill=ACCENT)


def _code(d, **kw):
    _line(d, (0.42, 0.38, 0.30, 0.50, 0.42, 0.62))
    _line(d, (0.58, 0.38, 0.70, 0.50, 0.58, 0.62))
    _line(d, (0.54, 0.34, 0.46, 0.66), fill=ACCENT, w=10)


def _robot(d, **kw):
    _rrect(d, (0.30, 0.36, 0.70, 0.70), r=0.08)
    _line(d, (0.50, 0.36, 0.50, 0.27), w=10)
    _dot(d, 0.50, 0.24, 0.030, fill=ACCENT)
    _dot(d, 0.42, 0.52, 0.030)
    _dot(d, 0.58, 0.52, 0.030)
    _line(d, (0.43, 0.62, 0.57, 0.62), w=10)


def _tag_x(d, **kw):
    _tag(d)
    _badge_x(d)


def _person_x(d, **kw):
    _person(d)
    _badge_x(d)


def _robot_x(d, **kw):
    _robot(d)
    _badge_x(d)


def _gear_check(d, **kw):
    cx, cy, r = 0.46, 0.54, 0.15
    for k in range(8):
        a = math.radians(k * 45)
        d.line([_p(cx + r * math.cos(a), cy + r * math.sin(a)),
                _p(cx + (r + 0.055) * math.cos(a), cy + (r + 0.055) * math.sin(a))],
               fill=GLYPH, width=11)
    _circle(d, cx, cy, r, w=11)
    _circle(d, cx, cy, 0.045, w=8)
    _line(d, (0.40, 0.68, 0.62, 0.44, 0.80, 0.28), fill=ACCENT)


def _arrow_up(d, **kw):
    _line(d, (0.28, 0.78, 0.28, 0.30), fill=MUTED, w=10)
    _line(d, (0.28, 0.78, 0.74, 0.78), fill=MUTED, w=10)
    _line(d, (0.36, 0.70, 0.50, 0.52, 0.60, 0.58, 0.74, 0.34), fill=ACCENT)
    _line(d, (0.60, 0.32, 0.76, 0.32, 0.76, 0.48), fill=ACCENT, w=11)


def _valley(d, **kw):
    _line(d, (0.26, 0.34, 0.40, 0.40, 0.50, 0.68, 0.60, 0.42, 0.74, 0.36), fill=MUTED, w=11)
    _line(d, (0.50, 0.50, 0.50, 0.74), fill=ACCENT)
    _line(d, (0.42, 0.64, 0.50, 0.75, 0.58, 0.64), fill=ACCENT)


def _x_circle(d, **kw):
    _circle(d, 0.50, 0.50, 0.22)
    _line(d, (0.42, 0.42, 0.58, 0.58), fill=ACCENT)
    _line(d, (0.58, 0.42, 0.42, 0.58), fill=ACCENT)


def _calendar(d, **kw):
    _rrect(d, (0.28, 0.34, 0.72, 0.74), r=0.05)
    _line(d, (0.28, 0.46, 0.72, 0.46), w=10)
    _line(d, (0.38, 0.26, 0.38, 0.38), w=10)
    _line(d, (0.62, 0.26, 0.62, 0.38), w=10)
    _dot(d, 0.42, 0.58, 0.030, fill=ACCENT)
    _dot(d, 0.58, 0.58, 0.030, fill=MUTED)
    _dot(d, 0.42, 0.66, 0.030, fill=MUTED)


def _warn(d, **kw):
    d.polygon([_p(0.50, 0.28), _p(0.76, 0.72), _p(0.24, 0.72)], outline=ACCENT, width=LW)
    _line(d, (0.50, 0.42, 0.50, 0.56), fill=ACCENT, w=11)
    _dot(d, 0.50, 0.65, 0.028, fill=ACCENT)


def _flask(d, **kw):
    _line(d, (0.40, 0.28, 0.40, 0.44, 0.28, 0.70, 0.72, 0.70, 0.60, 0.44, 0.60, 0.28))
    _line(d, (0.36, 0.28, 0.64, 0.28), w=10)
    _line(d, (0.36, 0.58, 0.64, 0.58), fill=ACCENT, w=9)


GLYPHS = {
    "chip": _chip, "coins": _coins, "tag": _tag, "person": _person, "gauge": _gauge,
    "tag_x": _tag_x, "person_x": _person_x, "robot_x": _robot_x,
    "chart_x": _chart_x, "code": _code, "robot": _robot,
    "gear_check": _gear_check, "arrow_up": _arrow_up, "valley": _valley,
    "x_circle": _x_circle, "calendar": _calendar, "warn": _warn, "flask": _flask,
}


def icon(name: str, out_dir: Path, *, question_glyph: Path | None = None) -> Path:
    """畫一顆圖示（圓角磁磚＋字形），回傳 PNG 路徑（同名快取）。"""
    out = out_dir / f"icon_{name}.png"
    if out.exists():
        return out
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([_p(0.02, 0.02), _p(0.98, 0.98)], radius=int(0.22 * S),
                        fill=TILE_FILL, outline=TILE_LINE, width=3)
    if name == "question":
        _glyph_text(d, "?", size=0.46, fill=ACCENT, font_path=question_glyph)
    else:
        try:
            GLYPHS[name](d)
        except KeyError:
            raise SystemExit(f"未知圖示：{name}（可用：{', '.join(sorted(GLYPHS))}）") from None
    img.save(out, optimize=True)
    return out


if __name__ == "__main__":     # 預覽：把全部圖示排成一張表
    import sys

    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    names = sorted(GLYPHS) + ["question"]
    cols, cell = 6, 140
    sheet = Image.new("RGB", (cols * cell, math.ceil(len(names) / cols) * cell), (8, 16, 28))
    from fontTools.ttLib import TTCollection
    tc = out_dir / "NotoSansCJKtc-bold.otf"
    if not tc.exists():
        coll = TTCollection("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
        next(f for f in coll.fonts if f["name"].getDebugName(1) == "Noto Sans CJK TC").save(tc)
    for i, n in enumerate(names):
        im = Image.open(icon(n, out_dir, question_glyph=tc)).resize((120, 120), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * cell + 10, (i // cols) * cell + 10), im)
    sheet.save(out_dir / "icons_sheet.png")
    print(f"✅ {out_dir / 'icons_sheet.png'}（{len(names)} 顆）")
