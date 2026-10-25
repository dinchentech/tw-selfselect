"""迴歸測試：`.env` 變更「當天立即生效」（V4.36）。

使用者裁定（2026-09-23）：「手動改完當天 13:25 就跑，買價才不會差太大」。

原本：`.env` 只在**每天 08:40 熱重載一次** ⇒ 手動 `VM_pick`／`VM_sync_env`（或自動選股寫入、
或直接改 VM 的 `.env`）之後，要等到**隔天**才生效，買價多漂一天。

現在：主迴圈每圈比對 `.env` 的**內容指紋（md5）**，一有變化立即套用（與 08:40 共用同一段
`_reload_env_config()`）⇒ 只要在 13:25 前改完，當天 13:25–13:30 就用新名單下單。
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

src_text = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")


def _load_env_fingerprint():
    """只匯入 `env_fingerprint`（不啟動整個交易程式：selfselect_trader 是腳本，import 會執行頂層碼）。"""
    import ast
    tree = ast.parse(src_text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "env_fingerprint":
            mod = ast.Module(body=[node], type_ignores=[])
            ns = {"Path": Path}
            exec(compile(mod, "<env_fingerprint>", "exec"), ns)
            return ns["env_fingerprint"]
    raise AssertionError("selfselect_trader.py 找不到 env_fingerprint()")


env_fingerprint = _load_env_fingerprint()


class TestEnvFingerprint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / ".env"
        self.p.write_text("PC_2006={}\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_stable_for_unchanged_file(self):
        a = env_fingerprint(str(self.p))
        self.assertEqual(a, env_fingerprint(str(self.p)))
        self.assertEqual(len(a), 32)

    def test_changes_when_content_changes(self):
        a = env_fingerprint(str(self.p))
        self.p.write_text("PC_2006={}\nPC_6505={}\n", encoding="utf-8")
        self.assertNotEqual(a, env_fingerprint(str(self.p)),
                            "加了新標的 ⇒ 指紋必須變（否則偵測不到手動更新）")

    def test_same_length_rewrite_is_detected(self):
        """只換內容、長度不變（例如改 alloc 6.0→4.0）也要抓到。"""
        self.p.write_text('PC_2006={"alloc":6.0}\n', encoding="utf-8")
        a = env_fingerprint(str(self.p))
        self.p.write_text('PC_2006={"alloc":4.0}\n', encoding="utf-8")
        self.assertNotEqual(a, env_fingerprint(str(self.p)))

    def test_missing_file_returns_none(self):
        self.assertIsNone(env_fingerprint(str(Path(self._tmp.name) / "nope.env")))


class TestTraderWiring(unittest.TestCase):
    def test_watch_block_present(self):
        self.assertIn("_env_fp_now = env_fingerprint()", src_text)
        self.assertIn("_reload_env_config('偵測到 .env 變更')", src_text)
        self.assertIn("偵測到 .env 內容變更", src_text)

    def test_single_reload_implementation_shared(self):
        """08:40 與即時偵測必須共用同一段重載邏輯（不可各寫一份）。"""
        self.assertEqual(src_text.count("def _reload_env_config"), 1)
        self.assertEqual(src_text.count("_reload_env_config('08:40 熱重載')"), 1)
        self.assertEqual(src_text.count("_reload_env_config('偵測到 .env 變更')"), 1)
        # 重載內文（把 PORTFOLIO_CONFIG 換成新的一份）只該出現一次
        self.assertEqual(src_text.count("PORTFOLIO_CONFIG.update(new_config)"), 1)
        self.assertEqual(src_text.count("new_config = load_portfolio_config()"), 1,
                         "只有 _reload_env_config() 內可以重讀設定（啟動那次是模組層常數）")

    def test_check_runs_every_loop_before_ordering(self):
        """指紋檢查必須在主迴圈內、且在 13:25 下單視窗之前（當天才來得及生效）。"""
        i_fp = src_text.index("_env_fp_now = env_fingerprint()")
        i_close = src_text.index("if (sn != 'keep_wait') and (not _close_order_window):")
        self.assertLess(i_fp, i_close)

    def test_first_loop_does_not_reload(self):
        """剛啟動時 `.env` 已經載入過 ⇒ 第一次看到指紋不該再重載一次。"""
        self.assertIn("_env_fp_seen['v'] and", src_text,
                      "要用『已見過的指紋』當條件，避免啟動瞬間重載")

    def test_failure_does_not_kill_loop(self):
        self.assertIn("不影響其他策略", src_text)


    # ── V4.38：狀態必須活在迴圈「外面」（否則每圈重置 ⇒ 比對永遠 False ⇒ 功能是死的）──
    def test_state_is_initialised_outside_the_main_loop(self):
        """⚠️ 這條就是 V4.36 的致命錯誤：`_env_fp_seen` 寫在 `while True:` 裡面
        ⇒ 每圈都用「當下指紋」重新初始化 ⇒ 後面的比對永遠 False ⇒ 即時生效從未觸發。"""
        import ast
        tree = ast.parse(src_text)
        loops = [n for n in ast.walk(tree)
                 if isinstance(n, ast.While) and isinstance(n.test, ast.Constant) and n.test.value is True]
        # 主迴圈＝`main()` 裡那個（含 `_HEARTBEAT['ts']` 的那個）
        main_loops = [n for n in loops
                      if "_env_fp_now" in ast.unparse(n) or "_HEARTBEAT" in ast.unparse(n)]
        self.assertTrue(main_loops, "找不到主迴圈")
        for loop in main_loops:
            body = ast.unparse(loop)
            self.assertNotIn("_env_fp_seen = {", body,
                             "`_env_fp_seen` 不可在迴圈內初始化（會被每圈重置 ⇒ 偵測永遠失效）")
            self.assertNotIn("def _reload_env_config", body,
                             "`_reload_env_config` 應定義在迴圈外（只需定義一次）")

    def test_state_declared_before_loop(self):
        i_state = src_text.index("_env_fp_seen = {'v': env_fingerprint()}")
        i_loop = src_text.index("  while True:\n    now = datetime.now()")
        self.assertLess(i_state, i_loop, "狀態要在主迴圈之前就建立")

    def test_sleep_window_also_checks_fingerprint(self):
        """休市／盤後一輪可長達 1 小時 ⇒ 睡眠中也必須檢查，否則「立即生效」會變「最慢一小時」。"""
        self.assertIn("_fp_sleep = env_fingerprint()", src_text)
        self.assertIn("中斷休眠立即套用", src_text)
        i_sleep = src_text.index("_sleep_total = max(sleep_seconds, 60)")
        i_check = src_text.index("_fp_sleep = env_fingerprint()")
        self.assertGreater(i_check, i_sleep, "檢查要放在睡眠迴圈內（`_sleep_total` 之後）")


class TestDocsUpdated(unittest.TestCase):
    def test_manual_documents_immediate_effect(self):
        manual = (ROOT / "使用手冊.md").read_text(encoding="utf-8")
        self.assertIn("立即", manual)
        self.assertIn(".env", manual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
