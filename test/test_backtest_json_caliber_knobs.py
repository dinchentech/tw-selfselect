#!/usr/bin/env python
"""回測結果 JSON 的檔頭必須記錄「會改變選股名單」的旋鈕（2026-11-05 補）。

## 為什麼

2026-11-05 要回答「我們的預設口徑跟母專案 tw-autotrader 的輪替四策略，選股差多少」，
做法是拿兩份 `results/*.json` 比 `selection_log`。但檔頭只有 `overheat`（舊版人工降溫）與 `oh_*`，
**沒有** `Z_OVERHEAT`（選股端過熱過濾，實測少 10.4% 名單）、`IMM_OVERHEAT`／`ENTRY_OVERHEAT`
（買進當下的過熱閘門），也沒有實際生效的 `preset`——正好是最會改變名單的幾個開關。
⇒ 兩份 JSON 看起來「同口徑」，實際上可能差一整組名單（實際踩到：得重跑一組控制變因的
group vs form 實驗才敢下結論，結果是 58 個選股日有 57 天名單逐位相同）。

規則因此收斂成一句：**會改變「選哪 5 檔」或「買不買得進去」的旋鈕，一律寫進 `out` 檔頭**；
純量測用的（`LEVERAGE`／`SCALE_TO_UTIL`）不強制。

本測試用 `ast` 解析 `scripts/backtest_plan2_monthly_3group.py` 的 `out = {...}` 字典
（不 import 該腳本——它在 module 層讀 `.env` 並印警告，import 會有副作用），
少一個鍵、或鍵沒接到對應的常量，就紅。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

HARNESS = Path(_ROOT) / "scripts" / "backtest_plan2_monthly_3group.py"

#: 檔頭鍵 → 必須接到的模組層常量（鍵存在但接到別的值/寫死 False 都不算數）
REQUIRED = {
    "preset": "_PRESET",
    "z_overheat": "Z_OVERHEAT",
    "imm_overheat": "IMM_OVERHEAT",
    "entry_overheat": "ENTRY_OVERHEAT",
    "oh_rsi_th": "OH_RSI_TH",
    "oh_dist_win": "OH_DIST_WIN",
    "oh_dist_th": "OH_DIST_TH",
    "oh_entry_mode": "OH_ENTRY_MODE",
    "pick_cooldown_months": "PICK_COOLDOWN_MONTHS",
    "prerank_r63_pct": "PRERANK_R63_PCT",
    "w_dist": "W_DIST",
    "nonmom_slots": "NONMOM_SLOTS",
}

#: 舊有的口徑鍵（「比對檔頭確認同口徑」這個工作流程靠它們）
LEGACY_KEYS = ("start", "end", "exec", "strat_mode", "swap_mode", "pool_n", "top_n",
               "scoring_model", "factor_revenue", "max_per_sector", "min_draw_back",
               "market_filter", "idle_cash_asset", "overheat", "groups", "benchmark_0050")


def find_out_dict(src: str) -> ast.Dict:
    """回傳腳本裡 `out = {...}` 的那個 dict 字面值（找 `groups`/`benchmark_0050` 那個）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "out" for t in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            if "groups" in keys:
                return node.value
    raise AssertionError("找不到 `out = {...}`（含 groups 的結果字典）")


class TestBacktestJsonCaliberKnobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = HARNESS.read_text(encoding="utf-8")
        cls.out_dict = find_out_dict(cls.src)
        cls.keys = [k.value for k in cls.out_dict.keys if isinstance(k, ast.Constant)]
        cls.values = {}
        for k, v in zip(cls.out_dict.keys, cls.out_dict.values):
            if isinstance(k, ast.Constant):
                cls.values[k.value] = v

    def test_caliber_knobs_are_recorded(self):
        missing = [k for k in REQUIRED if k not in self.keys]
        self.assertEqual(missing, [], f"檔頭缺這些會改變名單的旋鈕：{missing}")

    def test_caliber_knobs_wired_to_the_real_constants(self):
        for key, const in REQUIRED.items():
            node = self.values[key]
            self.assertIsInstance(node, ast.Name, f"`{key}` 應該直接引用常量 {const}，不要寫死")
            self.assertEqual(node.id, const, f"`{key}` 接到 {node.id}，預期 {const}")

    def test_constants_exist_at_module_level(self):
        tree = ast.parse(self.src)
        assigned = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))
        missing = [const for const in REQUIRED.values() if const not in assigned]
        self.assertEqual(missing, [], f"這些常量不存在於 module 層：{missing}")

    def test_legacy_keys_survive(self):
        missing = [k for k in LEGACY_KEYS if k not in self.keys]
        self.assertEqual(missing, [], f"舊的檔頭鍵被弄掉了：{missing}")

    def test_duplicate_keys_do_not_hide_new_values(self):
        """同一個鍵在 dict 字面值裡出現兩次時，後者覆蓋前者（Python 語意）。

        `strat_mode`／`swap_mode` 目前確實各寫了兩次（值相同，無害）；萬一哪天有人
        只改其中一處，實際落地的會是後面的那個 ⇒ 這裡把「重複鍵但值不同」擋下來。
        """
        seen = {}
        for k, v in zip(self.out_dict.keys, self.out_dict.values):
            if not isinstance(k, ast.Constant):
                continue
            prev = seen.get(k.value)
            cur = ast.dump(v)
            if prev is not None and prev != cur:
                self.fail(f"`{k.value}` 在 out 字典裡重複出現且值不同 ⇒ 讀到的是後者，容易誤判")
            seen[k.value] = cur


if __name__ == "__main__":
    unittest.main()
