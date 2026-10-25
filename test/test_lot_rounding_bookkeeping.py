"""迴歸測試：券商「整股進位/捨去」改動下單股數時，帳本必須跟著實際送單股數（2026-09-23）。

## 實盤事故（2026-09-23 13:25，自選股首次進場）

```
🔒 2884 auto 買入鎖定策略 → breakout
↻  2884 2000 股餘數 ≥500，進位至 2 張
✅ E.Sun 下單成功: 整股 buy 2884 2000 股 @ 45.45     ← 真正送出去的是 2000 股
📝 已記錄交易: BUY 2884 @ 45.45 (1584 股)            ← 帳上只記 1584 股 ❌
↻  5876 1461 股餘數 <500，捨去為 1 張
✅ E.Sun 下單成功: 整股 buy 5876 1000 股 @ 49.90     ← 真正送出去的是 1000 股
📝 已記錄交易: BUY 5876 @ 49.25 (1461 股)            ← 帳上卻記 1461 股 ❌
```

根因鏈：
1. `selfselect_trader.py` 用**計畫股數**（`int(額度/現價)`＝1584）下單；
2. `data/esun_provider.place_order` 把整股數量四捨五入到「張」（餘數 ≥500 進位、<500 捨去）
   ⇒ 真正送出去的是 2000 股／1000 股；
3. 13:25 送整股單時 `check_fill()` 還查不到成交（整股在 13:30 收盤撮合）⇒ `resolve_fill()` 回 `None`
   ⇒ 主程式沿用 `position_size` 記帳 ⇒ `holdings.json`／`performance.csv` 與券商庫存不一致
   （成本基礎、未實現損益、儀表板、賣出股數全部跟著錯）。

修法：provider 在成功回報裡帶上**實際送單股數**（`qty`），主程式以它為準記帳
（`core.live_utils.reconcile_order_qty`）；成交回報（`Check_fill`）仍然優先。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_utils import reconcile_order_qty   # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_msr_lot", ROOT / "scripts" / "monthly_selfselect_run.py")
msr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(msr)


class TestReconcileOrderQty(unittest.TestCase):
    def test_uses_broker_reported_qty_when_available(self):
        """provider 回報實際送單 2000 股 ⇒ 以 2000 記帳（不是計畫的 1584）。"""
        self.assertEqual(reconcile_order_qty(1584, {"order_no": "OK123", "sent_qty": 2000}), 2000)
        self.assertEqual(reconcile_order_qty(1461, {"order_no": "OK123", "sent_qty": 1000}), 1000)

    def test_falls_back_to_requested(self):
        """舊版 provider／mock／KGI 沒回報 qty ⇒ 維持原行為（requested）。"""
        self.assertEqual(reconcile_order_qty(470, {"order_no": "OK123"}), 470)
        self.assertEqual(reconcile_order_qty(470, None), 470)
        self.assertEqual(reconcile_order_qty(470, {"status": "filled"}), 470)

    def test_ignores_broken_qty_values(self):
        self.assertEqual(reconcile_order_qty(500, {"sent_qty": None}), 500)
        self.assertEqual(reconcile_order_qty(500, {"sent_qty": "abc"}), 500)
        self.assertEqual(reconcile_order_qty(500, {"sent_qty": 0}), 500, "0 不是合法送單股數")

    def test_accepts_string_qty(self):
        self.assertEqual(reconcile_order_qty(1000, {"sent_qty": "2000"}), 2000)

    def test_keeps_sdk_fields_for_callers(self):
        """provider 回傳值必須保留券商原始欄位（例如 order_no），只多帶 sent_qty。"""
        src = (ROOT / "data" / "esun_provider.py").read_text(encoding="utf-8")
        self.assertIn('out["sent_qty"] = qty_sent', src)
        self.assertIn("if isinstance(res, dict):", src)


class TestProviderReportsSentQty(unittest.TestCase):
    """`data/esun_provider.place_order` 必須把整股換算後的股數回報出來。"""

    def test_provider_returns_sent_qty(self):
        src = (ROOT / "data" / "esun_provider.py").read_text(encoding="utf-8")
        self.assertIn('result_holder["sent_qty"] = display_qty', src,
                      "成功回報要帶實際送單股數")
        self.assertIn("display_qty", src)

    def test_provider_rounding_rule_documented(self):
        src = (ROOT / "data" / "esun_provider.py").read_text(encoding="utf-8")
        self.assertIn("進位至", src)
        self.assertIn("捨去為", src)


class TestTraderUsesReconciledQty(unittest.TestCase):
    """主程式必須在記帳（log_trade／holdings）之前套用實際送單股數。"""

    def setUp(self):
        self.src = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")

    def test_reconcile_called_before_log_trade(self):
        for name, src in (("main", self.src),):
            i_rec = src.find("reconcile_order_qty(")
            i_log = src.find("rm.log_trade(symbol, signal, px, position_size")
            self.assertGreater(i_rec, 0, f"{name}: 沒用到 reconcile_order_qty")
            self.assertLess(i_rec, i_log, f"{name}: 必須在記帳之前套用實際送單股數")

    def test_imported_from_live_utils(self):
        for name, src in (("main", self.src),):
            imports = [l for l in src.split("\n") if l.startswith("from core.live_utils import")]
            self.assertTrue(imports, f"{name}: 找不到 core.live_utils 匯入行")
            self.assertIn("reconcile_order_qty", imports[0],
                          f"{name}: 未從 core.live_utils 匯入")



class TestStep0StillIntact(unittest.TestCase):
    """V4.34 步驟 0（補價＋基準日把關）不可因為這次修改被移除。"""

    def test_step0_present(self):
        self.assertTrue(hasattr(msr, "refresh_basis_data"))
        self.assertTrue(hasattr(msr, "basis_data_warning"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
