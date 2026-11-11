"""核心：券商「整股（board lot）」規則的**單一出處**（2026-11-09 新增，v1.1.36）

## 規則（玉山 ESun）

- 股數 **≤999** ⇒ 走**盤中零股**（`APCode.IntradayOdd`），原樣送出，股數不變。
- 股數 **≥1000** ⇒ 走**整股**（`APCode.Common`，以「張」為單位）⇒ **餘數 ≥500 進位、餘數 <500 捨去**
  ＝ 四捨五入到張。

## 為什麼要有這個檔案（實盤事故，2026-11-09）

同一條規則原本只寫在 `data/esun_provider.place_order()` 裡，**上層 sizing 完全不知道**。
2026-11-09 13:25 停泊：

```
🅿️ 停泊額度 213,152 受限於可用現金 152,360（額度≠現金）      ← 上限 152,360
↻  0050 2000 股餘數 ≥500，進位至 2 張                        ← 券商把 1,561 進位成 2,000
🅿️ 閒置資金停泊：買進 0050 2000 股 @ 97.60（NT$195,200）      ← 實付 195,200
⚠️ 停泊 0050 記帳股數依實際送單：1561 → 2000 股（差 -439 股）  ← 知道自己多買 439 股，但沒擋
```

計畫 1,561 × 97.60 ＝ NT$152,354（貼齊上限，正確）；券商進位後 2,000 × 97.60 ＝ NT$195,200
⇒ **超支 NT$42,840（+28%）**（還沒算手續費）。`core/park_asset.cash_available()` 刻意保守
（賣出回款不加回）的前提，就在下游這一步被打穿。

**買進方向的「進位」就是「多花錢」**，所以金額上限必須在**對齊整股之後**再檢查一次；
反之賣出方向的「進位」會送出**超過庫存**的委託（2026-11-05：持有 1,000 股卻送 2 張 ⇒ 只成交 1,000 股）。

## 與 2026-11-06 那次修正的關係

那次修的是「**帳**」（記帳股數要用券商回報的 `sent_qty`，`core.live_utils.reconcile_order_qty`）；
這次修的是「**錢**」（送單前就對齊，讓金額檢查看得到真正會花掉多少）。兩者互補、都要有：
對齊是「預防」，`reconcile_order_qty` 是「事後校正」。
"""

LOT = 1000           # 一張 ＝ 1000 股
ODD_LOT_MAX = 999    # 999 股（含）以下走盤中零股，股數不變


def _to_int(qty):
    try:
        return int(qty)
    except (TypeError, ValueError):
        return 0


def board_lot_qty(qty) -> int:
    """「想送的股數」→ 券商整股規則下**實際會送出去的股數**（回傳單位是「股」）。

    ≤999 ⇒ 原樣（盤中零股）；≥1000 ⇒ 四捨五入到張（餘數 ≥500 進位、<500 捨去）。
    非法／非正數一律回 0。
    """
    q = _to_int(qty)
    if q <= 0:
        return 0
    if q <= ODD_LOT_MAX:
        return q
    lots, rem = divmod(q, LOT)
    return (lots + 1) * LOT if rem >= LOT // 2 else lots * LOT


def fit_buy_qty(qty, price, max_cost=None) -> int:
    """買單用：先依整股規則對齊，再確認**金額不超過 `max_cost`**；超過就降一張（不降成零股）。

    `max_cost` 預設 ＝ `qty × price`（＝「不要比原計畫多花錢」，因為原計畫已經通過上層的
    額度／現金檢查）。停泊買進另有現金上限時把它傳進來即可。

    ⚠️ 停泊事故（2026-11-09）：`fit_buy_qty(1561, 97.60, 152360)` ⇒ **1,000 股**
    （NT$97,600 ≤ 上限），而不是券商進位後的 2,000 股（NT$195,200）。
    """
    px = float(price or 0)
    q = _to_int(qty)
    n = board_lot_qty(q)
    if px <= 0 or n <= 0:
        return 0
    limit = float(px * q) if max_cost is None else float(max_cost)
    if limit <= 0:
        return 0
    while n > 0 and n * px > limit + 1e-9:
        n = n - LOT if n >= LOT else 0
    return n


def sell_lot_qty(qty, held) -> int:
    """賣單用：對齊整股規則，但**不得超過實際持有股數**（否則券商的進位會送出超過庫存的委託）。

    持有 1,584 股要清倉：送 1,584 ⇒ 券商進位成 2,000（超過庫存）⇒ 只成交 1,000 股或退單。
    本函式會回 1,000 股，剩下的 584 股之後走零股。
    """
    n = board_lot_qty(qty)
    h = _to_int(held)
    if n <= 0 or h <= 0:
        return 0
    if n <= h:
        return n
    return h if h <= ODD_LOT_MAX else (h // LOT) * LOT
