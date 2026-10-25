"""迴歸測試：picker 的「從 VM 抓回實盤持股」選項（2026-09-22 使用者裁定以本機流程為主）。

背景：自選股選股日要在**本機**跑（`.env` 在本機維護），但 picker 需要**實盤的**
`logs/holdings.json` 才能正確判斷「已持倉一律保留」。作法 B＝先
`gcloud compute scp tw-autotrader:~/tw-autotrader/logs/holdings.json logs/holdings.json`
再跑 picker。使用者要求以 B 為主 ⇒ 把它縮成一個旗標 `--sync-holdings-from-vm`，
避免每次忘記先 scp（忘記的後果＝持倉判斷用舊資料，可能把持股誤列為汰換）。

本檔只測「命令怎麼組、抓完怎麼驗」的純邏輯（用注入的 runner，不真的連 VM）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.monthly_rebalance_picker import (  # noqa: E402
    fetch_holdings_from_vm, gcloud_scp_command)


class FakeRunner:
    def __init__(self, returncode=0, write=None, stderr=""):
        self.returncode = returncode
        self.write = write
        self.stderr = stderr
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)

        class R:
            pass
        r = R()
        r.returncode = self.returncode
        r.stderr = self.stderr
        r.stdout = ""
        if self.returncode == 0 and self.write:
            Path(kw.get("cwd") or ".").joinpath  # noqa: B018  (僅為了 lint 不抱怨)
            self.write()
        return r


class TestScpCommand(unittest.TestCase):
    def test_command_shape(self):
        cmd = gcloud_scp_command("tw-autotrader", "asia-east1-b",
                                 "logs/holdings.json")
        self.assertEqual(cmd[0], "gcloud")
        self.assertIn("compute", cmd)
        self.assertIn("scp", cmd)
        self.assertTrue(any("tw-autotrader:" in c and "logs/holdings.json" in c for c in cmd))
        self.assertIn("--zone", cmd)
        self.assertIn("asia-east1-b", cmd)
        self.assertIn("--quiet", cmd)


class TestFetchHoldings(unittest.TestCase):
    def test_ok_when_download_produces_positions(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "holdings.json"

            def write():
                dest.write_text(json.dumps({"2006": 689, "3515": 286}), encoding="utf-8")

            ok, msg = fetch_holdings_from_vm(dest=dest, runner=FakeRunner(write=write))
            self.assertTrue(ok, msg)
            self.assertEqual(json.loads(dest.read_text(encoding="utf-8"))["2006"], 689)

    def test_fail_when_scp_fails(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "holdings.json"
            ok, msg = fetch_holdings_from_vm(dest=dest, runner=FakeRunner(returncode=1, stderr="boom"))
            self.assertFalse(ok)
            self.assertIn("scp", msg.lower() + " ")

    def test_empty_download_is_ok_but_warns_to_reconcile(self):
        """2026-10-17 起契約改變：scp 成功 ⇒ 空倉是**合法狀態**（從零重來後就是空的）。

        舊契約「空檔一律當失敗」會讓選股流程在重置後完全卡住（實際事故）；
        改為接受空倉，但**必須**在訊息裡提醒先對帳（避免帳實不符時把持股當成不存在）。
        """
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "holdings.json"

            def write():
                dest.write_text("{}", encoding="utf-8")

            ok, msg = fetch_holdings_from_vm(dest=dest, runner=FakeRunner(write=write))
            self.assertTrue(ok, msg)
            self.assertIn("空倉", msg)
            self.assertIn("對帳", msg, "空倉時必須提醒對帳")

    def test_fail_when_file_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "holdings.json"
            ok, msg = fetch_holdings_from_vm(dest=dest, runner=FakeRunner())
            self.assertFalse(ok)


class TestWiring(unittest.TestCase):
    def test_picker_has_flag_and_uses_helper(self):
        src = (ROOT / "scripts" / "monthly_rebalance_picker.py").read_text(encoding="utf-8")
        self.assertIn("--sync-holdings-from-vm", src)
        self.assertIn("fetch_holdings_from_vm", src)
        # 必須在持倉脈絡檢查「之前」抓，否則守門會先中止
        self.assertLess(src.index("fetch_holdings_from_vm("),
                        src.index("holdings_context_check("))

    def test_manual_documents_local_flow_first(self):
        manual = (ROOT / "使用手冊.md").read_text(encoding="utf-8")
        self.assertIn("--sync-holdings-from-vm", manual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
