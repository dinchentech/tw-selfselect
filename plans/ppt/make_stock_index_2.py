#!/usr/bin/env python3
"""make_stock_index_2.py · 「常見技術指標」直式 9:16 六頁（K 線／均線／RSI／ATR）

姊妹作：`make_stock_index.py`（年化／本益比／回撤／夏普）。同一套視覺語言與版面節奏，
四張示意圖用 matplotlib 現畫，圖上的價格是**同一檔股票的同一段 95 個交易日**（各頁只是取不同窗口／加不同面板）。

內容摘用自 `策略說明.md`：
- 附錄 B「技術分析的核心指標」——K 線／均線／RSI 的白話解讀與典型用法，
  以及「技術指標不應單獨使用，需要多個指標相互印證」「入門先掌握 K 線、均線與成交量」。
- 附錄 D「RSI 補充說明」——50 中軸／70 超買／30 超賣，以及本系統的兩個週期（5 日、近似 14 日）。
- 附錄 E「ATR 補充說明」——TR／ATR 公式、N=14、門檻（ma_cross ≥0.5%、breakout >1%）、TR 的兩種口徑。
- 附錄 H「MA 與 EMA 的差異」——MA(5) 算例、本專案四個固定策略都用 MA。

重跑：
    MPLCONFIGDIR=$PWD/TMP/mplcache .venv/bin/python plans/ppt/make_stock_index_2.py
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
from matplotlib.patches import Rectangle              # noqa: E402
from pptx import Presentation                         # noqa: E402
from pptx.util import Inches, Pt                      # noqa: E402

import make_stock_index as S                          # noqa: E402  版面元件（卡／圖卡／重點列／講稿）
import make_why_design as W                           # noqa: E402  背景與共用視覺
from why_icons import icon as draw_icon               # noqa: E402

OUT = Path(ROOT / "plans/ppt/stock_index_2/stock_index_2.pptx")
TOTAL = 6
TICK = 13.0                       # 圖內刻度（沿用 stock_index 放大後的字級）

UP = W.ACCENT                     # 台股：紅＝漲
DOWN = S.GREEN                    # 綠＝跌
MA5_C, MA20_C, MA60_C = S.AMBER, S.BLUE, W.MUTED


# ── 同一檔股票的 95 個交易日（三段 regime：上升 → 回檔 → 波動放大的上攻）──
def series() -> dict:
    n = 95
    rng = np.random.default_rng(23)
    drift = np.concatenate([np.full(30, 0.30), np.full(22, -0.55), np.full(28, 0.62), np.full(15, 0.05)])
    vol = np.concatenate([np.full(30, 0.85), np.full(22, 1.05), np.full(28, 1.80), np.full(15, 1.35)])
    close = 100.0 * np.cumprod(1 + rng.normal(drift, vol) / 100)
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.25, n) / 100)
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.55, n)) / 100)
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.55, n)) / 100)
    return {"o": open_, "h": high, "l": low, "c": close}


def _ma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x)
    for i in range(len(x)):
        out[i] = x[max(0, i - n + 1): i + 1].mean()
    return out


def _rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = _ma(up, n), _ma(dn, n)
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-9))


def _atr(s: dict, n: int = 14, *, gap: bool = True) -> np.ndarray:
    tr = s["h"] - s["l"]
    if gap:                      # ma_cross 口徑：含前一日收盤（會吃到跳空）
        pc = np.concatenate([[s["c"][0]], s["c"][:-1]])
        tr = np.maximum(tr, np.maximum(np.abs(s["h"] - pc), np.abs(s["l"] - pc)))
    return _ma(tr, n)


def _candles(ax, s: dict, idx: np.ndarray) -> None:
    for i in idx:
        o, h, l, c = s["o"][i], s["h"][i], s["l"][i], s["c"][i]
        up = c >= o
        color = S._hex(UP if up else DOWN)
        ax.plot([i, i], [l, h], color=color, lw=1.2, solid_capstyle="butt", zorder=3)
        y0 = min(o, c)
        ax.add_patch(Rectangle((i - 0.34, y0), 0.68, max(abs(c - o), 0.006),
                               facecolor=color, edgecolor=color, linewidth=0.8, zorder=4))


# ── 圖① K 線：紅綠蠟燭＋開高低收標註 ────────────────────────────────────
def candle_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    s = series()
    path = W.BUILD / "si2_candle.png"
    fig = S._fig()
    ax = fig.add_axes([0.075, 0.135, 0.905, 0.845])
    S._bare(ax)

    idx = np.arange(len(s["c"]) - 26, len(s["c"]))
    _candles(ax, s, idx)

    body = s["c"] - s["o"]
    pick = int(idx[np.argmax(body[idx])])          # 最長的一根紅 K
    ax.add_patch(Rectangle((pick - 0.5, s["l"][pick] * 0.998), 1.0,
                           (s["h"][pick] - s["l"][pick]) * 1.004, facecolor="none",
                           edgecolor=S._hex(W.TEXT), linewidth=1.0, ls=(0, (2, 2)), zorder=6))

    o, h, l, c = s["o"][pick], s["h"][pick], s["l"][pick], s["c"][pick]
    tag = dict(boxstyle="round,pad=0.24", facecolor="#0A1424", edgecolor="none", alpha=0.9)
    for x, y, text, dx, dy, ha, va in (
            (pick, h, "最高", 0, 12, "center", "bottom"),
            (pick, l, "最低", 0, -12, "center", "top"),
            (pick - 0.45, o, "開盤", -10, 0, "right", "center"),
            (pick + 0.45, c, "收盤", 10, 0, "left", "center")):
        ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                    fontproperties=bold, fontsize=12.5, color=S._hex(W.TEXT), bbox=tag,
                    arrowprops=dict(arrowstyle="-", color=S._hex(W.MUTED), lw=0.9,
                                    shrinkA=1, shrinkB=3))

    ax.text(0.015, 0.03, "反白框＝一根長紅 K（收盤 > 開盤）", transform=ax.transAxes,
            va="bottom", ha="left", fontproperties=reg, fontsize=11.5, color=S._hex(UP),
            bbox=dict(boxstyle="round,pad=0.22", facecolor="#0A1424", edgecolor="none", alpha=0.85))
    ax.set_xlim(idx[0] - 1.2, idx[-1] + 1.2)
    ax.set_ylim(s["l"][idx].min() * 0.985, s["h"][idx].max() * 1.02)
    ax.set_xticks(idx[::5])
    ax.set_xticklabels([f"{i + 1}" for i in idx[::5]])
    ax.set_xlabel("交易日（近 26 日）", fontproperties=reg, fontsize=11.5,
                  color=S._hex(W.MUTED), labelpad=3)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_ylabel("股價（元）", fontproperties=reg, fontsize=12.5, color=S._hex(W.MUTED), labelpad=3)

    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖② 均線：收盤＋MA5／MA20／MA60＋金叉死叉 ─────────────────────────────
def ma_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    s = series()
    c = s["c"]
    x = np.arange(len(c))
    path = W.BUILD / "si2_ma.png"
    fig = S._fig()
    ax = fig.add_axes([0.135, 0.175, 0.775, 0.80])
    S._bare(ax)

    ma5, ma20, ma60 = _ma(c, 5), _ma(c, 20), _ma(c, 60)
    ax.plot(x, c, color=S._hex(W.TEXT), lw=1.2, alpha=0.85, label="收盤")
    for line, color, name in ((ma5, MA5_C, "MA5"), (ma20, MA20_C, "MA20"), (ma60, MA60_C, "MA60")):
        ax.plot(x, line, color=S._hex(color), lw=2.0, label=name)

    cross = np.where(np.diff(np.sign(ma5 - ma20)) != 0)[0]
    gold = [i + 1 for i in cross if ma5[i + 1] > ma20[i + 1]]
    dead = [i + 1 for i in cross if ma5[i + 1] < ma20[i + 1]]
    for i, text, dy in ((gold[0] if gold else None, "黃金交叉", 0.055),
                        (dead[0] if dead else None, "死亡交叉", -0.055)):
        if i is None:
            continue
        ax.scatter([i], [ma5[i]], s=58, color=S._hex(UP if dy > 0 else DOWN), zorder=8)
        ax.annotate(text, (i, ma5[i]), xytext=(i + 3, c[i] * (1 + dy)), textcoords="data",
                    fontproperties=bold, fontsize=12, color=S._hex(UP if dy > 0 else DOWN),
                    va="center", ha="left",
                    arrowprops=dict(arrowstyle="-", color=S._hex(W.MUTED), lw=0.8,
                                    shrinkA=0, shrinkB=3))

    for line, color, name, lx in ((ma5, MA5_C, "MA5", 0.02), (ma20, MA20_C, "MA20", 0.14),
                                  (ma60, MA60_C, "MA60", 0.26)):
        ax.text(lx, 0.055, name, transform=ax.transAxes, fontproperties=bold, fontsize=12.5,
                color=S._hex(color), va="bottom", ha="left")
    ax.text(0.36, 0.055, "＋ 收盤", transform=ax.transAxes, fontproperties=reg, fontsize=12,
            color=S._hex(W.TEXT), va="bottom", ha="left")

    ax.set_xlim(-1, len(c) + 1)
    ax.set_xticks(np.arange(0, len(c) + 1, 20))
    ax.set_xticklabels([f"{i + 1}" for i in np.arange(0, len(c) + 1, 20)])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_xlabel("交易日（95 日）", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED), labelpad=3)
    ax.set_ylabel("股價（元）", fontproperties=reg, fontsize=12.5, color=S._hex(W.MUTED), labelpad=3)

    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖③ RSI：價格＋RSI(14) 子圖（70／30 線）─────────────────────────────
def rsi_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    s = series()
    c = s["c"]
    x = np.arange(len(c))
    r = _rsi(c)
    path = W.BUILD / "si2_rsi.png"
    fig = S._fig()

    ax = fig.add_axes([0.135, 0.545, 0.775, 0.415])
    S._bare(ax)
    ax.plot(x, c, color=S._hex(W.TEXT), lw=1.5)
    ax.set_xticks([])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_ylabel("股價", fontproperties=reg, fontsize=12, color=S._hex(W.MUTED), labelpad=3)

    ax2 = fig.add_axes([0.135, 0.175, 0.775, 0.295], sharex=ax)
    S._bare(ax2)
    ax2.fill_between(x, 70, 100, color=S._hex(UP), alpha=0.10, lw=0)
    ax2.fill_between(x, 0, 30, color=S._hex(DOWN), alpha=0.12, lw=0)
    ax2.plot(x, r, color=S._hex(S.AMBER), lw=2.0)
    for y, label, color in ((70, "超買 70", UP), (50, None, W.MUTED), (30, "超賣 30", DOWN)):
        ax2.axhline(y, color=S._hex(color), lw=1.0, ls=(0, (4, 4)), alpha=0.85)
        if label is None:            # 50 中軸只留虛線（y 軸刻度已有 50）
            continue
        ax2.annotate(label, (len(c) - 1, y), xytext=(-3, 0), textcoords="offset points",
                     va="center", ha="right", fontproperties=bold, fontsize=11.5,
                     color=S._hex(color),
                     bbox=dict(boxstyle="round,pad=0.20", facecolor="#0A1424",
                               edgecolor="none", alpha=0.88))
    ax2.set_ylim(0, 100)
    ax2.set_yticks([0, 50, 100])
    ax2.set_xticks(np.arange(0, len(c) + 1, 20))
    ax2.set_xticklabels([f"{i + 1}" for i in np.arange(0, len(c) + 1, 20)])
    ax2.set_xlabel("交易日（95 日）", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED), labelpad=3)
    ax2.set_ylabel("RSI(14)", fontproperties=reg, fontsize=12, color=S._hex(S.AMBER), labelpad=3)

    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 圖④ ATR：價格＋ATR(14) 子圖（波動放大看得見）────────────────────────
def atr_png() -> Path:
    from matplotlib import pyplot as plt

    reg, bold = S._fonts()
    s = series()
    c = s["c"]
    x = np.arange(len(c))
    a = _atr(s)
    pct = a / c * 100
    path = W.BUILD / "si2_atr.png"
    fig = S._fig()

    ax = fig.add_axes([0.135, 0.545, 0.775, 0.415])
    S._bare(ax)
    ax.plot(x, c, color=S._hex(W.TEXT), lw=1.5)
    ax.set_xticks([])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_ylabel("股價", fontproperties=reg, fontsize=12, color=S._hex(W.MUTED), labelpad=3)

    ax2 = fig.add_axes([0.135, 0.175, 0.775, 0.295], sharex=ax)
    S._bare(ax2)
    ax2.fill_between(x, 0, pct, color=S._hex(S.AMBER), alpha=0.18, lw=0)
    ax2.plot(x, pct, color=S._hex(S.AMBER), lw=2.0)
    ax2.axhline(0.5, color=S._hex(DOWN), lw=1.0, ls=(0, (4, 4)))
    ax2.axhline(1.0, color=S._hex(UP), lw=1.0, ls=(0, (4, 4)))
    _tag = dict(boxstyle="round,pad=0.20", facecolor="#0A1424", edgecolor="none", alpha=0.88)
    ax2.annotate("0.5%＝ma_cross 門檻", (len(c) - 1, 0.5), xytext=(-2, 3), textcoords="offset points",
                 va="bottom", ha="right", fontproperties=bold, fontsize=11, color=S._hex(DOWN),
                 bbox=_tag)
    ax2.annotate("1.0%＝breakout 門檻", (len(c) - 1, 1.0), xytext=(-2, 3), textcoords="offset points",
                 va="bottom", ha="right", fontproperties=bold, fontsize=11, color=S._hex(UP),
                 bbox=_tag)
    ax2.set_ylim(0, max(2.2, float(pct.max()) * 1.15))
    ax2.set_xticks(np.arange(0, len(c) + 1, 20))
    ax2.set_xticklabels([f"{i + 1}" for i in np.arange(0, len(c) + 1, 20)])
    ax2.set_xlabel("交易日（95 日）", fontproperties=reg, fontsize=11.5, color=S._hex(W.MUTED), labelpad=3)
    ax2.set_ylabel("ATR ÷ 股價", fontproperties=reg, fontsize=12, color=S._hex(S.AMBER), labelpad=3)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    fig.savefig(path, dpi=220, transparent=True)
    plt.close(fig)
    return path


# ── 內容（摘用 `策略說明.md` 附錄 B／D／E／H）────────────────────────────
COVER_TITLE = "常見技術指標"
COVER_SUB = "K 線，均線，RSI，ATR"

P2_DEF = ["用紅綠蠟燭線表示股價漲跌。",
          "一根 K 線＝一段時間的開盤、最高、最低、收盤。"]
P2_ROWS = [("candle", "紅＝收盤 > 開盤（漲）；綠＝收盤 < 開盤（跌）", ("紅", "綠")),
           ("range", "實體越長＝多空力量差距越大；影線越長＝被拉回或撐住", ("實體", "影線"))]
P2_CALL = ["典型用法：觀察多空力量對比，", "而不是拿它猜明天漲跌。"]

P3_DEF = ["均線（MA）＝最近 N 天平均價格線，也就是「平均成本線」。",
          "MA(5) = (100+102+101+103+105) ÷ 5 = 102.2"]
P3_ROWS = [("ma_lines", "股價站上均線 ⇒ 趨勢偏強；跌破 ⇒ 趨勢轉弱", ("趨勢偏強",)),
           ("arrow_up", "MA5 > MA20 > MA60 ＝ 多頭排列（反過來是空頭排列）", ("多頭排列",))]
P3_CALL = ["均線是落後指標：", "它確認趨勢已經發生，不是預測未來。"]

P4_DEF = ["RSI 統計一段時間的漲跌力道，像「心率」，數值 0～100。"]
P4_ROWS = [("divide", "50 中軸＝多空分水嶺：> 50 買方較強、< 50 賣方較強", ("50 中軸",)),
           ("warn", "70 以上＝超買：市場過熱，追高風險大", ("70 以上",)),
           ("valley", "30 以下＝超賣：常被視為跌深反彈機會", ("30 以下",))]
P4_CALL = ["本系統兩處用法週期不同：5 日 RSI 當買賣過濾、", "近似 14 日 RSI 當「買入過熱閘門」。"]

P5_DEF = ["ATR 衡量波動程度，不預測方向（一天平均會動多少錢）。",
          "TR = max（最高−最低, |最高−前收|, |最低−前收|）",
          "ATR = TR 的 N 日移動平均（本系統 N = 14）"]
P5_ROWS = [("range", "ATR 很小 ⇒ 盤整、沒人玩 ⇒ 跳過訊號", ("跳過訊號",)),
           ("divide", "門檻：ma_cross ≥ 0.5%、breakout > 1%（ATR ÷ 股價）", ("0.5%", "1%"))]
P5_CALL = ["ATR 是尺：", "決定要不要出手，也決定停損距離。"]

P6_ROWS = [("bars", "成交量：放量上漲才是真漲（1 張＝1,000 股）", ("放量",)),
           ("gauge", "MACD：像「油門力道」，紅柱變長＝加速上漲", ("油門",)),
           ("thermo", "KD：情緒溫度計，K > 80 超買、< 20 超賣", ("80", "20")),
           ("valley", "布林通道：像「橡皮筋」，觸上軌可能回調", ("橡皮筋",))]
P6_CALL = ["台股入門先掌握三件事：", "K 線、均線與成交量。"]

SECONDS = {1: 13, 2: 30, 3: 30, 4: 30, 5: 31, 6: 27}

SPOKEN = {
    1: ["這一節講四個技術指標：K 線、均線、RSI、ATR。",
        "前面四個指標判斷值不值得買，這四個判斷什麼時候買賣。"],
    2: ["先看 K 線：紅色是收盤比開盤高、也就是漲；綠色相反。",
        "一根 K 線有四件事：開盤、最高、最低、收盤。",
        "實體越長代表多空力量差距越大；影線越長代表被拉回或撐住。",
        "所以 K 線看的是多空力量對比，不是猜明天漲跌。"],
    3: ["均線是最近 N 天收盤價的平均，也叫平均成本線；五日線就是最近五天的平均。",
        "股價站上均線代表趨勢偏強，跌破就轉弱；三條均線由上而下排好叫多頭排列。",
        "但均線是落後指標：它告訴你趨勢已經發生，不是預測未來。"],
    4: ["RSI 統計一段時間的漲跌力道，像心跳，數值 0 到 100。",
        "50 是中軸：50 以上買方較強，50 以下賣方較強。",
        "70 以上叫超買，追高風險大；30 以下叫超賣，常當成跌深反彈。",
        "我們用兩個週期：五日 RSI 當買賣過濾，十四日 RSI 當買入過熱閘門。"],
    5: ["ATR 量的是波動，不是方向：這檔股票一天平均會動多少錢。",
        "真實區間取三個值最大的：最高減最低、最高減前收、最低減前收，再取十四天平均。",
        "ATR 太小代表盤整、沒人玩，訊號就跳過。",
        "門檻：均線策略要求 0.5%，突破策略要求 1%。"],
    6: ["最後提醒：技術指標不該單獨使用，要互相印證。",
        "成交量，放量上漲才是真漲；MACD 像油門，紅柱變長代表加速。",
        "KD 是情緒溫度計，80 以上超買、20 以下超賣；布林通道像橡皮筋，碰到上軌可能回調。",
        "台股入門，先掌握 K 線、均線跟成交量。"],
}
TIPS = {
    2: "台股紅漲綠跌，美股相反（綠漲紅跌）；本專案用的是日 K。",
    3: "本專案四個固定策略的均線全部是 MA（簡單移動平均），沒有用 EMA；"
       "ma_cross 是 MA9 上穿 MA21，而且要求 ATR ÷ 股價 ≥ 0.5%。",
    4: "兩個週期不要混淆：bollinger／vwap 用 5 日 RSI；買入過熱閘門用近似 14 日"
       "（最近 15 根收盤漲跌的簡單平均）。超買不等於一定會跌。",
    5: "口徑提醒：breakout 的 TR 只用當日 high／low／close（不含前一日收盤、不含跳空）；"
       "ma_cross 的 TR 有納入前一日收盤 ⇒ 兩者不完全相同。",
    6: "附錄 B 另外還有乖離率（BIAS）與 OBV；本專案的做法是先用 K 線／均線定方向，"
       "再用 ATR 過濾、RSI 判過熱。",
}


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W.SLIDE_W, W.SLIDE_H

    bgs = {
        1: W.background("si2_cover", 311, glow_xy=(0.44, 0.26), glow_r=0.72, glow_s=0.20),
        2: W.background("si2_s2", 323, glow_xy=(0.86, 0.64), glow_s=0.14),
        3: W.background("si2_s3", 337, glow_xy=(0.12, 0.68), glow_r=0.70, glow_s=0.14),
        4: W.background("si2_s4", 349, glow_xy=(0.52, 0.62), glow_s=0.12, glow_r=0.62),
        5: W.background("si2_s5", 353, glow_xy=(0.18, 0.40), glow_s=0.15, glow_r=0.70),
        6: W.background("si2_s6", 367, glow_xy=(0.74, 0.22), glow_s=0.13, glow_r=0.66),
    }

    # ① 封面 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[1])
    W._accent_bar(s, Inches(2.71), Inches(6.62))
    _b, tf = W._textbox(s, S.MARGIN, Inches(6.98), S.CONTENT_W, Inches(2.20))
    W._rich_para(tf.paragraphs[0], COVER_TITLE, (COVER_TITLE,), size=Pt(34), bold=True,
                 align=W.PP_ALIGN.CENTER, line=1.34, space_after=Pt(6))
    W._rich_para(tf.add_paragraph(), COVER_SUB, (), size=Pt(26), bold=True,
                 align=W.PP_ALIGN.CENTER, line=1.34, space_after=Pt(0), color=W.WHITE)
    icons = ("candle", "ma_lines", "pulse", "range")
    tile, gap = 0.56, 0.52
    x0 = (6.2014 - (tile * len(icons) + gap * (len(icons) - 1))) / 2
    for i, name in enumerate(icons):
        pic = s.shapes.add_picture(str(draw_icon(name, W.BUILD / "icons", question_glyph=None)),
                                   Inches(x0 + i * (tile + gap)), Inches(9.42),
                                   width=Inches(tile), height=Inches(tile))
        pic.line.fill.background()
    S._notes(s, SECONDS[1], SPOKEN[1],
             "四個指標的順序是有邏輯的：K 線看單日多空、均線看趨勢、RSI 看力道過熱、ATR 看波動大小。")
    W._page_no(s, 1, TOTAL)

    # ② K 線 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[2])
    S._title(s, "K 線圖", "Candlestick・紅漲綠跌，看單日的多空力量")
    S._chart(s, candle_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.38)), P2_DEF,
                 label="定義", phrase_marks=("紅綠蠟燭線",), size=Pt(15.5))
    S._icon_row(s, (S.MARGIN, Inches(7.10), S.CONTENT_W, Inches(1.72)), P2_ROWS,
                size=Pt(16.5), row_gap=0.30)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P2_CALL,
               ("多空力量對比",))
    S._notes(s, SECONDS[2], SPOKEN[2], TIPS[2])
    W._page_no(s, 2, TOTAL)

    # ③ 均線 -----------------------------------------------------------
    s = W._bg_slide(prs, bgs[3])
    S._title(s, "均線（MA）", "Moving Average・平均成本線")
    S._chart(s, ma_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.58)), P3_DEF,
                 label="定義", phrase_marks=("平均成本線",), size=Pt(15))
    S._icon_row(s, (S.MARGIN, Inches(7.34), S.CONTENT_W, Inches(1.50)), P3_ROWS,
                size=Pt(16.5), row_gap=0.28)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P3_CALL,
               ("落後指標",))
    S._notes(s, SECONDS[3], SPOKEN[3], TIPS[3])
    W._page_no(s, 3, TOTAL)

    # ④ RSI ------------------------------------------------------------
    s = W._bg_slide(prs, bgs[4])
    S._title(s, "RSI", "相對強弱指標・統計漲跌力道，像「心率」")
    S._chart(s, rsi_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.42)), P4_DEF,
                 label="定義", phrase_marks=("0～100",), size=Pt(15))
    S._icon_row(s, (S.MARGIN, Inches(7.14), S.CONTENT_W, Inches(1.76)), P4_ROWS,
                size=Pt(16), row_gap=0.24)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P4_CALL,
               ("5 日", "14 日"))
    S._notes(s, SECONDS[4], SPOKEN[4], TIPS[4])
    W._page_no(s, 4, TOTAL)

    # ⑤ ATR ------------------------------------------------------------
    s = W._bg_slide(prs, bgs[5])
    S._title(s, "ATR", "平均真實波動幅度・量波動，不量方向")
    S._chart(s, atr_png())
    S._card_text(s, (Inches(0.34), Inches(5.64), Inches(5.52), Inches(1.72)), P5_DEF,
                 label="定義", phrase_marks=("N 日移動平均（本系統 N = 14）",), size=Pt(14))
    S._icon_row(s, (S.MARGIN, Inches(7.42), S.CONTENT_W, Inches(1.42)), P5_ROWS,
                size=Pt(16), row_gap=0.26)
    S._callout(s, (Inches(0.34), Inches(9.02), Inches(5.52), Inches(0.98)), P5_CALL,
               ("停損距離",))
    S._notes(s, SECONDS[5], SPOKEN[5], TIPS[5])
    W._page_no(s, 5, TOTAL)

    # ⑥ 不要單獨用（附錄 B 的關鍵提醒）---------------------------------
    s = W._bg_slide(prs, bgs[6])
    S._title(s, "但是，不要單獨用", "附錄 B 的關鍵提醒・其餘四個指標一句話")
    _b, tf = W._textbox(s, S.MARGIN, Inches(1.86), S.CONTENT_W, Inches(0.90))
    W._rich_para(tf.paragraphs[0], "技術指標不應單獨使用，", ("不應單獨使用",),
                 size=Pt(21), bold=True, line=1.30, space_after=Pt(0))
    W._rich_para(tf.add_paragraph(), "需要多個指標相互印證。", (), size=Pt(21), bold=True,
                 line=1.30, space_after=Pt(0))
    S._icon_row(s, (S.MARGIN, Inches(2.92), S.CONTENT_W, Inches(5.48)), P6_ROWS,
                size=Pt(16.5), row_gap=0.46, icon_in=0.52)
    S._callout(s, (Inches(0.34), Inches(8.62), Inches(5.52), Inches(1.18)), P6_CALL,
               ("互相印證",))
    S._notes(s, SECONDS[6], SPOKEN[6], TIPS[6])
    W._page_no(s, 6, TOTAL)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"✅ 產生 {path.relative_to(ROOT)}（{path.stat().st_size / 1024 / 1024:.2f} MB，{TOTAL} 頁）")
    print(f"   中間產物：{W.BUILD.relative_to(ROOT)}/（背景 ×6、示意圖 ×4、圖示）")
