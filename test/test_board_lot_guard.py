"""券商整股（board lot）規則的守門測試（2026-11-09，v1.1.36）

## 事故：停泊買進「進位」超支 NT$42,840（+28%）

VM 日誌（2026-11-09 13:25）：

```
🅿️ 停泊額度 213,152 受限於可用現金 152,360（額度≠現金）       ← 現金上限 152,360
↻  0050 2000 股餘數 ≥500，進位至 2 張                         ← 計畫 1,561 股被進位成 2,000 股
🅿️ 閒置資金停泊：買進 0050 2000 股 @ 97.60（NT$195,200）       ← 實付 195,200 ❌
⚠️ 停泊 0050 記帳股數依實際送單：1561 → 2000 股（差 -439 股）   ← 知道多買 439 股，卻沒有擋
```

- 計畫 1,561 × 97.60 ＝ NT$152,354（貼齊上限，正確）；券商進位後 2,000 × 97.60 ＝ NT$195,200
  ⇒ **超支 NT$42,840**（+439 股、+28%），還沒算手續費。
- 根因：`core/park_asset.park_shares()` 只取整到「股」，而 `data/esun_provider.place_order()`
  的整股規則是**四捨五入到張**（餘數 ≥500 進位）。**買進方向的進位就是多花錢**，
  所以 `cash_available()` 刻意保守（賣出回款不加回）的前提在下游被打穿。
- 與 2026-11-06 那次是同一條規則的兩面：那次修「帳」（記帳股數用 `sent_qty`），
  這次修「錢」（送單前先對齊，金額檢查才看到真正會花掉多少）。

守門重點：
1. `board_lot_qty()` 就是券商規則本身（回傳「股」），`fit_buy_qty()` 保證對齊後**不超過上限**。
2. 停泊買進、策略買進、停泊釋出、策略賣出四條路徑都必須先對齊（原始碼順序守門）。
3. provider 不得再自己寫第二份規則（單一出處）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.lots import board_lot_qty, fit_buy_qty, sell_lot_qty   # noqa: E402
from core.park_asset import park_shares                          # noqa: E402


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class TestBoardLotQty(unittest.TestCase):
    """`board_lot_qty()` ＝ 券商實際會送出去的股數。"""

    def test_odd_lot_untouched(self):
        """≤999 股走盤中零股，股數不變。"""
        for q in (1, 470, 999):
            self.assertEqual(board_lot_qty(q), q)

    def test_round_half_up_to_lot(self):
        """≥1000 股：餘數 ≥500 進位、<500 捨去。"""
        self.assertEqual(board_lot_qty(1000), 1000)
        self.assertEqual(board_lot_qty(1499), 1000)   # 餘 499 → 捨去
        self.assertEqual(board_lot_qty(1500), 2000)   # 餘 500 → 進位
        self.assertEqual(board_lot_qty(1561), 2000)   # 事故股數
        self.assertEqual(board_lot_qty(4000), 4000)   # 整張不動
        self.assertEqual(board_lot_qty(4363), 4000)   # 2026-11-09 2609 買單（捨去）

    def test_invalid(self):
        for q in (0, -5, None, "abc"):
            self.assertEqual(board_lot_qty(q), 0)


class TestFitBuyQty(unittest.TestCase):
    """買單：對齊整股後，金額不得超過上限（進位＝多花錢）。"""

    def test_incident_1561_shares_never_becomes_2000(self):
        """事故回歸：上限 152,360、0050 @97.60 ⇒ 只能買 1,000 股（NT$97,600），不是 2,000 股。"""
        n = fit_buy_qty(1561, 97.60, 152_360)
        self.assertEqual(n, 1000)
        self.assertLessEqual(n * 97.60, 152_360)
        # 反證：不設上限（＝舊行為：對齊後就是券商會送的股數）會超支
        self.assertGreater(board_lot_qty(1561) * 97.60, 152_360)

    def test_default_cap_is_planned_cost(self):
        """沒給上限時，以「計畫股數的金額」為上限（不允許進位多花錢）。"""
        # 1,561 股 @97.60 計畫 NT$152,354 ⇒ 進位成 2,000（NT$195,200）不允許 ⇒ 1,000 股
        self.assertEqual(fit_buy_qty(1561, 97.60), 1000)
        # 4,363 股 @57.30 計畫 NT$250,000 ⇒ 對齊成 4,000（NT$229,200）比計畫便宜 ⇒ 保留
        self.assertEqual(fit_buy_qty(4363, 57.30), 4000)

    def test_never_exceeds_cap(self):
        for q in (1000, 1561, 2000, 4000, 4363, 999):
            for px in (10.0, 57.3, 97.6, 500.0):
                n = fit_buy_qty(q, px, q * px)
                self.assertGreaterEqual(n, 0)
                self.assertLessEqual(n * px, q * px + 1e-9)

    def test_insufficient_cash_returns_zero(self):
        """連一張都買不起 ⇒ 0（不硬買）。"""
        self.assertEqual(fit_buy_qty(1500, 100.0, 150_000), 1000)
        self.assertEqual(fit_buy_qty(1500, 200.0, 150_000), 0)

    def test_bad_price(self):
        self.assertEqual(fit_buy_qty(2000, 0), 0)
        self.assertEqual(fit_buy_qty(0, 97.6), 0)


class TestParkSizingIncident(unittest.TestCase):
    """停泊 sizing 端到端：`park_shares()` → `fit_buy_qty()` 之後金額必須 ≤ 現金上限。"""

    def test_park_never_exceeds_cash_cap(self):
        cap = 152_360.0
        px = 97.60
        raw = park_shares(cap, px)
        self.assertEqual(raw, 1561, "park_shares 仍取整到股（本測試的前提）")
        final = fit_buy_qty(raw, px, cap)
        self.assertEqual(final, 1000)
        self.assertLessEqual(final * px, cap, "停泊金額不得超過現金上限")

    def test_park_keeps_full_lots_when_affordable(self):
        """有錢時不要多降：上限 NT$400,000、0050 @97.60 ⇒ 4,096→4,000 股（不是 3,000）。"""
        raw = park_shares(400_000, 97.60)          # 4098
        self.assertEqual(fit_buy_qty(raw, 97.60, 400_000), 4000)


class TestSellLotQty(unittest.TestCase):
    """賣單：對齊整股但不得超過持有（否則券商的進位會送出超過庫存的委託）。"""

    def test_never_sells_more_than_held(self):
        self.assertEqual(sell_lot_qty(1584, 1584), 1000)   # 進位成 2,000 > 庫存 ⇒ 退 1,000
        self.assertEqual(sell_lot_qty(4000, 4000), 4000)
        self.assertEqual(sell_lot_qty(584, 584), 584)      # 零股原樣
        self.assertEqual(sell_lot_qty(2000, 1000), 1000)   # 想賣 2,000 但只有 1,000

    def test_no_holdings(self):
        self.assertEqual(sell_lot_qty(1000, 0), 0)


class TestSingleSourceOfTruth(unittest.TestCase):
    """整股規則只能有一份；四條下單路徑都要先對齊。"""

    def test_provider_imports_shared_rule(self):
        prov = _read("data/esun_provider.py")
        self.assertIn("from core.lots import", prov)
        self.assertIn("board_lot_qty(", prov)
        self.assertNotIn("% 1000 >= 500", prov, "provider 不得再自己實作一份整股規則")

    def test_park_buy_aligns_before_order(self):
        src = _read("selfselect_trader.py")
        i_fit = src.find("fit_buy_qty(_n_raw, px, idle)")
        i_order = src.find("broker.place_order(sym, 'buy'")
        self.assertGreater(i_fit, 0, "停泊買進必須先 fit_buy_qty 對齊")
        self.assertLess(i_fit, i_order, "對齊必須在下單之前")

    def test_park_release_aligns_sell(self):
        src = _read("selfselect_trader.py")
        i_sell = src.find("sell_lot_qty(sh, sh)")
        i_order = src.find("broker.place_order(sym, 'sell', _send)")
        self.assertGreater(i_sell, 0, "停泊釋出必須先 sell_lot_qty 對齊")
        self.assertLess(i_sell, i_order, "對齊必須在下單之前")

    def test_orphan_cleanup_aligns_sell(self):
        """孤兒清倉（第 5 條賣單路徑）：持有非整張股數時也要先對齊，免得進位超過庫存。"""
        src = _read("selfselect_trader.py")
        i_align = src.find("sell_lot_qty(old_shares, old_shares)")
        i_call = src.find("sell_with_fill_check(broker, old_sym, _orphan_send")
        self.assertGreater(i_align, 0, "孤兒清倉必須先 sell_lot_qty 對齊")
        self.assertLess(i_align, i_call, "對齊必須在下單之前")

    def test_strategy_buy_and_sell_align(self):
        src = _read("selfselect_trader.py")
        i_fit = src.find("position_size = fit_buy_qty(_asked_size, px)")
        i_sell = src.find("position_size = sell_lot_qty(_asked_size")
        i_order = src.find("order_result = (place_buy(symbol, position_size)")
        self.assertGreater(i_fit, 0, "策略買進必須先 fit_buy_qty 對齊")
        self.assertGreater(i_sell, 0, "策略賣出必須先 sell_lot_qty 對齊")
        self.assertLess(i_fit, i_order, "買單對齊必須在下單之前")
        self.assertLess(i_sell, i_order, "賣單對齊必須在下單之前")

    def test_provider_prints_requested_qty(self):
        """舊版印的是進位後的股數（讀日誌會被誤導，事故當天就出現 `2000 股餘數 ≥500`）。"""
        prov = _read("data/esun_provider.py")
        self.assertIn("_asked_qty", prov)
        self.assertNotIn("{qty * 1000} 股餘數", prov)


if __name__ == "__main__":
    unittest.main()
