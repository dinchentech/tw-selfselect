"""迴歸測試：`keep_wait` 的 `max_additions` 語意（＝加碼次數，不含初始建倉）。

背景（2026-10-27）：使用者反映投影片 W4-S23 關於 keep_wait 的說法不對。查核後確認：
`buy_count` 在初始建倉／「偵測既有持股」時就設為 1，而加碼條件原本寫 `buy_count < max_additions`
⇒ `max_additions=2` **實際只加碼 1 次**，與 `策略說明.md` §9.3／§9.4 和投影片寫的「最多加碼 2 次」矛盾。
修法：條件改成 `(buy_count - 1) < max_additions`。

順帶修掉記帳污染：原本 `++buy_count` 與 `last_buy_price`／`total_cost`／`total_shares` 的更新寫在
`if max_entry_price 擋價` 的 if/else **之外** ⇒ 被擋掉的那次也算一次加碼，且把沒發生的交易
記進均價與股數（之後停利基準全歪）。

測什麼：
1. `max_additions=2` ⇒ 初始建倉後可以連加 2 次，第 3 次停手。
2. `max_additions=0` ⇒ 完全不加碼；`=1` ⇒ 剛好 1 次。
3. 回跌門檻仍然必要（沒跌夠就不加）。
4. 擋價時**不得**更新 tracker；更新只能落在 `else`（真的要下單）分支。
"""
import ast
import unittest
from pathlib import Path

TRADER = Path(__file__).resolve().parent.parent / "selfselect_trader.py"
SRC = TRADER.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _find_dca_if():
    """找出 keep_wait 的 DCA 判斷式：`(drop_pct >= kw_drop_pct) and (... < kw_max_add)`。"""
    for node in ast.walk(TREE):
        if isinstance(node, ast.If):
            dump = ast.dump(node.test)
            if "kw_max_add" in dump and "kw_drop_pct" in dump and "buy_count" in dump:
                return node
    raise AssertionError("找不到 keep_wait 的 DCA 判斷式（條件字串可能被改寫）")


NODE = _find_dca_if()
CODE = compile(ast.Expression(body=NODE.test), "<dca-condition>", "eval")


def can_add(buy_count, kw_max_add, drop_pct=6.0, kw_drop_pct=5.0):
    """重跑實盤那行判斷式（buy_count 由初始建倉起算為 1）。"""
    return bool(eval(CODE, {"__builtins__": {}},  # noqa: S307 - 測試專用
                     {"trk": {"buy_count": buy_count},
                      "kw_max_add": kw_max_add,
                      "drop_pct": drop_pct,
                      "kw_drop_pct": kw_drop_pct}))


class DcaCountTest(unittest.TestCase):
    def test_default_allows_two_additions(self):
        self.assertTrue(can_add(1, 2), "初始建倉後應允許第 1 次加碼")
        self.assertTrue(can_add(2, 2), "第 1 次加碼後應允許第 2 次加碼")
        self.assertFalse(can_add(3, 2), "已加碼 2 次（buy_count=3）後應停手")

    def test_zero_disables_dca(self):
        self.assertFalse(can_add(1, 0))

    def test_one_allows_exactly_one_addition(self):
        self.assertTrue(can_add(1, 1))
        self.assertFalse(can_add(2, 1))

    def test_drop_threshold_still_required(self):
        self.assertFalse(can_add(1, 2, drop_pct=4.9, kw_drop_pct=5.0))
        self.assertTrue(can_add(1, 2, drop_pct=5.0, kw_drop_pct=5.0))

    def test_condition_counts_additions_not_total_buys(self):
        # 防退化：條件必須是 (buy_count - 1)，不是裸的 buy_count
        self.assertIn("(trk['buy_count'] - 1) < kw_max_add",
                      " ".join(SRC.split()),
                      "max_additions 是加碼次數，條件要扣掉初始建倉那一次")

    def test_tracker_updated_only_when_order_really_placed(self):
        inner = NODE.body[0]
        self.assertIsInstance(inner, ast.If, "DCA 分支內應先判斷 max_entry_price")
        blocked = ast.dump(ast.Module(body=inner.body, type_ignores=[]))
        placed = ast.dump(ast.Module(body=inner.orelse, type_ignores=[]))
        for frag in ("total_cost", "total_shares", "last_buy_price"):
            self.assertNotIn(frag, blocked, f"擋價時不可更新 {frag}")
            self.assertIn(frag, placed, f"真的要下單時才更新 {frag}")
        self.assertIn("'buy_count'", placed, "buy_count 只在真的要下單時 +1")
        self.assertNotIn("'buy_count'", blocked, "擋價時不可 ++buy_count")


if __name__ == "__main__":
    unittest.main()
