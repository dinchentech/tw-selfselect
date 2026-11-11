"""買單「現金上限」守門測試（2026-11-09 事故後補，v1.1.37）

## 為什麼需要

`check_monthly_budget()`／`check_stock_cap()` 比的是**額度**（`alloc × 本金`），不是**現金**。
2026-11-05 的「額度≠現金」修正（`core.park_asset.cash_available()`，缺陷四）只接到**停泊**
一條路徑；策略買進／資金加碼／買入補足這三條買單完全沒有現金檢查。

2026-11-09 實例（VM 日誌）：停泊釋出 0050 4,000 股（約 NT$390,400）→ 買 2609（NT$229,200）
→ 現金見底；若同一天 2603 也給買訊，那一筆 NT$250,000 的買單額度檢查照樣會過，
卻沒有現金交割（再把停泊買回時就變成超支 NT$42,840 那筆）。

## 修法（v1.1.37）

`fit_cash()`（`selfselect_trader.py`，`place_buy()` 旁邊）＝
`fit_buy_qty(qty, px, cash_available(本金 − 持股成本, 停泊成本視為可動用))`：
三條買單路徑（策略／加碼／補足）在 `place_buy()` 之前一律先過它。
⚠️ 停泊本身**不用**它——停泊的現金上限已經是 `min(額度, 現金)`（`park_idle_if_due()` 內）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.lots import fit_buy_qty   # noqa: E402

TRADER = ROOT / "selfselect_trader.py"


def _src():
    return TRADER.read_text(encoding="utf-8")


class TestCashCapMath(unittest.TestCase):
    """`fit_buy_qty(qty, px, 可用現金)` 的性質（`fit_cash()` 就是這個式子的包裝）。"""

    def test_zero_cash_blocks_buy(self):
        """現金 0 ⇒ 一股都不買（即使額度很寬）。"""
        self.assertEqual(fit_buy_qty(2500, 100.0, 0.0), 0)

    def test_todays_scenario(self):
        """2026-11-09：現金上限 NT$152,360、0050 @97.60 ⇒ 1,000 股（NT$97,600）。"""
        self.assertEqual(fit_buy_qty(1561, 97.60, 152_360), 1000)

    def test_allocation_ok_but_cash_runs_out(self):
        """本金 50 萬、4 檔各 25 萬額度 ⇒ 第 3 檔額度合格但現金 0（這就是原本沒人擋的情境）。"""
        total, px, alloc = 500_000.0, 50.0, 250_000.0
        open_cost = 0.0
        sent = []
        for _ in range(4):
            qty = int(alloc / px)                        # 額度：5,000 股
            n = fit_buy_qty(qty, px)                     # ① 策略 sizing：不得超過計畫金額（整股對齊）
            cash = max(0.0, total - open_cost)           # ② 可用現金（＝fit_cash 的上限）
            n = fit_buy_qty(n, px, cash)
            sent.append(n)
            open_cost += n * px
        self.assertEqual(sent, [5000, 5000, 0, 0],
                         "前兩檔把本金用完，後兩檔必須被現金擋下（不是被額度擋下）")
        self.assertLessEqual(sum(sent) * px, total)

    def test_never_exceeds_cash(self):
        for qty in (1000, 1561, 2500, 4363):
            for px in (10.0, 57.3, 97.6):
                cash = 200_000.0
                self.assertLessEqual(fit_buy_qty(qty, px, cash) * px, cash + 1e-9)


class TestCashGuardWiring(unittest.TestCase):
    """原始碼守門：三條買單路徑都必須在 `place_buy()` 之前過 `fit_cash()`。"""

    def setUp(self):
        self.src = _src()

    def test_fit_cash_defined_with_shared_helpers(self):
        self.assertIn("def fit_cash(", self.src, "缺少 fit_cash()（買單的現金上限）")
        body = self.src[self.src.find("def fit_cash("):]
        body = body[:body.find("\n  def ", 1)] if "\n  def " in body[1:] else body
        self.assertIn("cash_available", body, "fit_cash() 必須用 core.park_asset.cash_available()")
        self.assertIn("fit_buy_qty(", body, "fit_cash() 必須用共用的整股對齊（core.lots）")
        self.assertIn("already_parked_cost=0.0", body,
                      "停泊部位對買單是準現金（place_buy 會先賣掉它）⇒ 不得再從現金扣除")
        self.assertIn("return int(qty or 0)", body, "現金估算失敗時不可把買單變成 0（不套用上限）")

    def test_strategy_buy_uses_cash_guard(self):
        i_fit = self.src.find("position_size = fit_cash(symbol, position_size, px)")
        i_order = self.src.find("order_result = (place_buy(symbol, position_size)")
        self.assertGreater(i_fit, 0, "策略買進沒有過 fit_cash()")
        self.assertLess(i_fit, i_order, "現金上限必須在下單之前")

    def test_keep_wait_addon_uses_cash_guard(self):
        i_fit = self.src.find("buy_shares = fit_cash(symbol, buy_shares, px)")
        i_order = self.src.find("place_buy(symbol, buy_shares, '資金加碼需要資金')")
        self.assertGreater(i_fit, 0, "資金加碼沒有過 fit_cash()")
        self.assertLess(i_fit, i_order, "現金上限必須在下單之前")

    def test_topup_uses_cash_guard(self):
        i_fit = self.src.find("_need = fit_cash(symbol, _need, px)")
        i_order = self.src.find("place_buy(symbol, _need, '買入補足需要資金')")
        self.assertGreater(i_fit, 0, "買入補足沒有過 fit_cash()")
        self.assertLess(i_fit, i_order, "現金上限必須在下單之前")

    def test_cash_cap_logged(self):
        """被現金砍股數時必須留下可見的一行（否則就是另一個靜默失敗）。"""
        self.assertIn("買單受限於可用現金", self.src)


if __name__ == "__main__":
    unittest.main()
