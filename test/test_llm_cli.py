#!/usr/bin/env python
"""`scripts/llm_cli.py`（模型轉接頭）的回歸測試（2026-10-28）。

A/B 的 `--llm-cmd` 契約很嚴格：**stdout 只能有 JSON**。模型很愛加 ```json 圍欄或客套話，
所以 `extract_json()` 必須抽得出來；抽不到就要 exit 2（A/B 會記「輸出不合格」而不是靜默算錯）。

這裡**不呼叫任何模型**（沒有金鑰、不花錢）：只測純函式與 `echo` provider 的管線。
"""
import json
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.llm_cli import extract_json  # noqa: E402

PICKS = {"as_of": "2022-01-03", "picks": [
    {"sid": "2330", "reasons": ["動能 [R1]"], "citations": ["R1"]},
    {"sid": "2454", "reasons": ["法人 [R2]"], "citations": ["R2"]}]}


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(extract_json(json.dumps(PICKS)), PICKS)

    def test_fenced_json(self):
        text = "好的，以下是結果：\n```json\n" + json.dumps(PICKS) + "\n```\n希望有幫助！"
        self.assertEqual(extract_json(text), PICKS)

    def test_trailing_prose(self):
        self.assertEqual(extract_json(json.dumps(PICKS) + "\n（以上）"), PICKS)

    def test_two_objects_takes_first(self):
        text = json.dumps(PICKS) + "\n" + json.dumps({"other": 1})
        self.assertEqual(extract_json(text), PICKS)

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            extract_json("我覺得 2330 不錯")
        with self.assertRaises(ValueError):
            extract_json("")


class TestEchoProvider(unittest.TestCase):
    """`--provider echo`：不呼叫模型、只證明 stdin→stdout 管線與 JSON 契約。"""

    def _run(self, stdin_text):
        return subprocess.run(
            [sys.executable, os.path.join(_ROOT, "scripts", "llm_cli.py"),
             "--provider", "echo"],
            input=stdin_text, capture_output=True, text=True, timeout=60)

    def test_echo_returns_valid_json(self):
        prompt = "選股日：2022-01-03\n[R1] 2330：收盤 581\n[R2] 2454：收盤 843\n請從上列 2 檔中選出 2 檔。"
        r = self._run(prompt)
        self.assertEqual(r.returncode, 0, r.stderr)
        obj = json.loads(r.stdout)
        self.assertEqual([p["sid"] for p in obj["picks"]], ["2330", "2454"])
        self.assertEqual(obj["as_of"], "2022-01-03")

    def test_empty_stdin_fails_loudly(self):
        r = self._run("")
        self.assertEqual(r.returncode, 2)
        self.assertIn("stdin 是空的", r.stderr)

    def test_missing_model_fails_loudly_for_real_providers(self):
        r = subprocess.run([sys.executable, os.path.join(_ROOT, "scripts", "llm_cli.py"),
                            "--provider", "ollama", "--model", ""],
                           input="選出 1 檔", capture_output=True, text=True, timeout=60,
                           env={**os.environ, "LLM_MODEL": ""})
        self.assertEqual(r.returncode, 2)
        self.assertIn("缺少 --model", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
