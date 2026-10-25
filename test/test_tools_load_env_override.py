"""迴歸測試：用 `docker exec` 跑的工具必須 `load_dotenv(override=True)`。

坑（2026-10-01 實測）：
  docker-compose 的 `env_file: .env` 在**建立容器時**把變數注入 process env；之後在主機上改 `.env`，
  既有的 process env **不會**跟著變。而 `python-dotenv` 的 `load_dotenv()` 預設 `override=False`
  ⇒ 它不會覆蓋已存在的變數 ⇒ **在容器內用 `docker exec` 跑、且直接讀 `os.environ` 的工具
  會拿到「容器啟動當時」的舊 `.env` 值**。
  實例：把 `TOTAL_CAPITAL` 改成 130 萬後，`docker exec … python -c "load_dotenv(); os.getenv('TOTAL_CAPITAL')"`
  仍回 **120 萬**（`override=True` 才回 130 萬）。

主程式 `selfselect_trader.py` 一直都用 `override=True`（V4.36 熱重載），所以**只有工具腳本**會踩到。
本測試就是防這條尾巴再長出來：**凡讀 `.env` 既有鍵的腳本，就必須載入 `.env` 且 override**。
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERRIDE_CALL = "load_dotenv(override=True)"


def _env_keys() -> set:
    """`.env`（若存在）＋ `.env.example.txt` 的所有鍵名（後者是版控檔，CI 也拿得到）。"""
    keys = set()
    for rel in (".env", ".env.example.txt"):
        p = ROOT / rel
        if p.exists():
            keys |= {m.group(1) for m in re.finditer(r"^([A-Z_0-9]+)=", p.read_text(encoding="utf-8"), re.M)}
    return keys


def _reads_env_keys(text: str, keys) -> bool:
    if not keys:
        return False
    pat = re.compile(r"os\.(?:getenv|environ\.get)\(['\"](?:%s)['\"]" % "|".join(sorted(keys)))
    return bool(pat.search(text))


def scripts_missing_override(texts: dict, keys) -> list:
    """回傳「讀了 .env 既有鍵、卻沒有 load_dotenv(override=True)」的檔名清單。

    `texts`: {檔名或路徑: 內容}（可注入 fixture 測試本函式本身）。
    """
    return sorted(name for name, text in texts.items()
                  if _reads_env_keys(text, keys) and OVERRIDE_CALL not in text)


class TestDockerExecToolsLoadEnvOverride(unittest.TestCase):
    def test_every_env_reading_script_loads_env_with_override(self):
        keys = _env_keys()
        self.assertTrue(keys, "取不到 .env 鍵名（連 .env.example.txt 都沒有？）")
        texts = {f.name: f.read_text(encoding="utf-8") for f in sorted((ROOT / "scripts").glob("*.py"))}
        offenders = scripts_missing_override(texts, keys)
        self.assertEqual(offenders, [],
                         f"這些腳本會用 docker exec 跑、卻會讀到容器啟動時的舊 .env：{offenders}\n"
                         f"修法：在 import 之後加 `from dotenv import load_dotenv` ＋ `{OVERRIDE_CALL}`")

    def test_checker_flags_a_script_without_override(self):
        """自驗：沒有 override 的寫法必須被抓到（否則這條規則等於沒在檢查）。"""
        keys = {"TOTAL_CAPITAL"}
        bad = {"bad_tool.py": "import os\nx = os.getenv('TOTAL_CAPITAL')\n"}
        good = {"good_tool.py": f"import os\nfrom dotenv import load_dotenv\n{OVERRIDE_CALL}\nx = os.getenv('TOTAL_CAPITAL')\n"}
        self.assertEqual(scripts_missing_override(bad, keys), ["bad_tool.py"])
        self.assertEqual(scripts_missing_override(good, keys), [])

    def test_plain_load_dotenv_is_not_enough(self):
        """只寫 `load_dotenv()`（override=False）不算數 —— 那正是這個坑的來源。"""
        keys = {"TOTAL_CAPITAL"}
        half = {"tool.py": "import os\nfrom dotenv import load_dotenv\nload_dotenv()\nx = os.getenv('TOTAL_CAPITAL')\n"}
        self.assertEqual(scripts_missing_override(half, keys), ["tool.py"])

    def test_entrypoint_itself_uses_override(self):
        src = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn(OVERRIDE_CALL, src)
        plans = (ROOT / "plans" / "selfselect_trader.py")
        if plans.exists():
            self.assertIn(OVERRIDE_CALL, plans.read_text(encoding="utf-8"), "plans/ 也要同步")


if __name__ == "__main__":
    unittest.main()
