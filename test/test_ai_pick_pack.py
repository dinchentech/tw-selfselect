#!/usr/bin/env python
"""`core/ai_pick.py`（AI 選股的可稽核外殼）回歸測試（2026-10-28）。

要守住的四件事：
1. **不得夾帶未來資料**：封包的每個 provenance 日期都必須 ≤ 選股日，否則直接丟錯。
2. prompt 必須把每一檔都編號（[R1]..[Rn]），且明說「資料不足不得臆測」。
3. 模型輸出必須可驗證：只能從池內挑、數量要對、每檔都要有理由與引用、引用必須是 R#。
4. 稽核檔要可重現：同一份輸入 → 同一個 pack_sha256。
"""
import json
import os
import sys
import tempfile
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.ai_pick import (PackError, SelectionError, build_pack, build_prompt,  # noqa: E402
                          parse_selection, assert_no_lookahead, write_audit)

AS_OF = "2022-01-03"
IDX = pd.date_range("2021-06-01", "2022-06-30", freq="B")


def price_df():
    n = len(IDX)
    close = [100 + i * 0.1 for i in range(n)]
    return pd.DataFrame({"close": close, "high": [c * 1.01 for c in close],
                         "low": [c * 0.99 for c in close], "open": close,
                         "volume": [1e6] * n}, index=IDX)


class TestBuildPack(unittest.TestCase):
    def test_only_uses_data_up_to_as_of(self):
        df = price_df()
        pack = build_pack("2330", AS_OF, price_df=df)
        self.assertEqual(pack["provenance"]["price"], AS_OF)
        # 選股日之後的價格不得影響封包（把未來價格改成天價，封包不變）
        df2 = df.copy()
        df2.loc[df2.index > pd.Timestamp(AS_OF), "close"] = 9999
        pack2 = build_pack("2330", AS_OF, price_df=df2)
        self.assertEqual(pack["price"], pack2["price"])

    def test_missing_data_is_null_not_invented(self):
        pack = build_pack("9999", AS_OF)
        self.assertIsNone(pack["price"])
        self.assertIsNone(pack["per"])
        self.assertIsNone(pack["inst_net_15d"])
        self.assertTrue(pack["month_revenue"]["unavailable"])
        self.assertTrue(pack["news"]["unavailable"])

    def test_inst_and_per_are_clipped(self):
        inst = {"2021-12-30": 100.0, "2022-01-03": 50.0, "2022-02-01": 999999.0}
        per = {"2021-12-30": 12.5, "2023-01-03": 99.0}
        pack = build_pack("2330", AS_OF, price_df=price_df(), inst_series=inst, per_series=per)
        self.assertEqual(pack["inst_net_15d"], 150.0, "選股日之後的法人資料不得計入")
        self.assertEqual(pack["per"]["value"], 12.5)
        self.assertEqual(pack["per"]["date"], "2021-12-30")


class TestNoLookahead(unittest.TestCase):
    def test_future_provenance_raises(self):
        pack = build_pack("2330", AS_OF, price_df=price_df())
        pack["provenance"]["price"] = "2022-06-01"     # 模擬被塞進未來資料
        with self.assertRaises(PackError):
            assert_no_lookahead(pack, AS_OF)

    def test_clean_pack_passes(self):
        assert_no_lookahead(build_pack("2330", AS_OF, price_df=price_df()), AS_OF)


class TestPrompt(unittest.TestCase):
    def test_ids_and_rules(self):
        pack = build_pack("2330", AS_OF, price_df=price_df())
        prompt = build_prompt([pack], top_n=1)
        self.assertIn("[R1] 2330", prompt)
        self.assertIn("不得引用任何資料之外的記憶", prompt)
        self.assertIn("不得臆測", prompt)
        self.assertIn('"picks"', prompt)


class TestParseSelection(unittest.TestCase):
    pool = ["2330", "2454", "2881"]

    def _ok(self):
        return json.dumps({"as_of": AS_OF, "picks": [
            {"sid": "2330", "reasons": ["動能強 [R1]"], "citations": ["R1"]},
            {"sid": "2454", "reasons": ["法人買超 [R2]"], "citations": ["R2"]},
        ]}, ensure_ascii=False)

    def test_valid(self):
        obj = parse_selection(self._ok(), self.pool, top_n=2)
        self.assertEqual([p["sid"] for p in obj["picks"]], ["2330", "2454"])

    def test_rejects_unknown_sid(self):
        bad = json.dumps({"picks": [
            {"sid": "9999", "reasons": ["x"], "citations": ["R1"]},
            {"sid": "2454", "reasons": ["x"], "citations": ["R2"]}]})
        with self.assertRaises(SelectionError):
            parse_selection(bad, self.pool, top_n=2)

    def test_rejects_wrong_count(self):
        with self.assertRaises(SelectionError):
            parse_selection(self._ok(), self.pool, top_n=3)

    def test_rejects_missing_citations(self):
        bad = json.dumps({"picks": [
            {"sid": "2330", "reasons": ["x"]},
            {"sid": "2454", "reasons": ["x"], "citations": ["R2"]}]})
        with self.assertRaises(SelectionError):
            parse_selection(bad, self.pool, top_n=2)

    def test_rejects_non_data_citation(self):
        bad = json.dumps({"picks": [
            {"sid": "2330", "reasons": ["我記得它後來會漲 [NEWS]"], "citations": ["NEWS"]},
            {"sid": "2454", "reasons": ["x"], "citations": ["R2"]}]})
        with self.assertRaises(SelectionError):
            parse_selection(bad, self.pool, top_n=2)

    def test_rejects_not_json(self):
        with self.assertRaises(SelectionError):
            parse_selection("我覺得 2330 不錯", self.pool, top_n=1)


class TestAudit(unittest.TestCase):
    def test_hash_is_reproducible(self):
        pack = build_pack("2330", AS_OF, price_df=price_df())
        prompt = build_prompt([pack], top_n=1)
        with tempfile.TemporaryDirectory() as d:
            m1 = write_audit(d, AS_OF, [pack], prompt, None, model="m")
            m2 = write_audit(d, AS_OF, [pack], prompt, None, model="m")
            self.assertEqual(m1["pack_sha256"], m2["pack_sha256"])
            self.assertEqual(m1["prompt_sha256"], m2["prompt_sha256"])
            self.assertTrue(os.path.exists(os.path.join(d, AS_OF, "pack.json")))
            self.assertTrue(os.path.exists(os.path.join(d, AS_OF, "prompt.txt")))

    def test_response_is_written(self):
        pack = build_pack("2330", AS_OF, price_df=price_df())
        with tempfile.TemporaryDirectory() as d:
            meta = write_audit(d, AS_OF, [pack], "p", '{"picks": []}', model="m")
            self.assertTrue(os.path.exists(os.path.join(d, AS_OF, "response.json")))
            self.assertEqual(len(meta["response_sha256"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
