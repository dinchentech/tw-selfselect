"""迴歸測試：picker 的「總數上限 N」（＝使用者說的 N−M，對齊回測 `SWAP_MODE=addonly`）。

背景（2026-09-22 使用者裁定）：實盤規則「已持倉一律保留＋每月固定再選 N 檔新名」**沒有上限**，
名單會累積（例：8 檔新選 ＋ 2 檔已持倉 ＝ 10 檔）。回測的 `addonly` 口徑則是
`new = new[:max(0, TOP_N - active)]`（`active`＝本腿持股檔數）⇒ **本腿總檔數維持 N**。

實測（正常組）：addonly 明顯優於 full（每月掉出前 N 名就賣）——
2015-2025 **+743.9%** vs +291.0%、2022-2025 **+122.5%** vs +76.2%；且 **N=5 優於 N=8**（+743.9% vs +441.4%）。
因此 picker 改為預設套用上限，`--no-cap` 可回到舊行為。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.monthly_rebalance_picker import cap_new_picks  # noqa: E402


class TestCapNewPicks(unittest.TestCase):
    def test_caps_to_remaining_room(self):
        picks = ["a", "b", "c", "d", "e"]
        self.assertEqual(cap_new_picks(picks, leg_held_count=2, top_n=5), ["a", "b", "c"])

    def test_no_room_when_already_full(self):
        self.assertEqual(cap_new_picks(["a", "b"], leg_held_count=5, top_n=5), [])
        self.assertEqual(cap_new_picks(["a", "b"], leg_held_count=6, top_n=5), [])

    def test_no_held_means_full_n(self):
        self.assertEqual(len(cap_new_picks(list("abcdefgh"), leg_held_count=0, top_n=5)), 5)

    def test_no_cap_keeps_old_behaviour(self):
        picks = list("abcdefgh")
        self.assertEqual(cap_new_picks(picks, leg_held_count=2, top_n=5, cap_total=False), picks)


class TestPickerWiring(unittest.TestCase):
    def test_picker_has_cap_and_flag(self):
        src = (ROOT / "scripts" / "monthly_rebalance_picker.py").read_text(encoding="utf-8")
        self.assertIn("cap_new_picks(", src)
        self.assertIn("--no-cap", src)
        # 只算本腿持股：不可把 keep_wait（全輪替腿）算進 N
        self.assertIn('current.get(s, {}).get("strategy") != "keep_wait"', src)

    def test_docs_mention_total_cap(self):
        manual = (ROOT / "使用手冊.md").read_text(encoding="utf-8")
        self.assertTrue("總數上限" in manual, "使用手冊 未說明『總數上限 N』")


if __name__ == "__main__":
    unittest.main(verbosity=2)
