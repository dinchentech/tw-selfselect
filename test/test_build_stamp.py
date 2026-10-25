#!/usr/bin/env python
"""banner「建置」標記的回歸測試（2026-09-15）。

背景：`selfselect_trader.py` 原本寫 `BUILD_DATE = datetime.now()`，於是 banner 上的
「建置日期」其實是**程式啟動時間**——VM 實證：
  2026-09-14 18:57:06 啟動 → `build 2026-09-14 18:57:06`
  2026-09-15 08:01:09 啟動 → `build 2026-09-15 08:01:09`
⇒ 這一欄永遠無法回答「容器裡跑的是不是剛 deploy 的那版程式」。

修復：建置資訊改由 `core.version.build_info()` 從**原始碼檔**推導
（最新 mtime ＋ 內容 sha1 指紋），與程式啟動時間無關。
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.version import build_info  # noqa: E402

SRC_CANDIDATES = ('selfselect_trader.py',)


def _write(path: Path, text: str, mtime: float = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class TestBuildInfo(unittest.TestCase):
    def test_build_time_is_newest_source_mtime(self):
        """建置時間 = 來源檔最新 mtime（不是呼叫當下時間）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = time.mktime(time.strptime('2026-09-14 18:20:11', '%Y-%m-%d %H:%M:%S'))
            new = old + 3600
            _write(root / 'a.py', 'x = 1\n', mtime=old)
            _write(root / 'core' / 'b.py', 'y = 2\n', mtime=new)
            stamp, fp = build_info(root=root, paths=('.',))
            self.assertEqual(stamp, '2026-09-14 19:20:11',
                             '建置時間必須是來源檔最新 mtime')
            self.assertEqual(len(fp), 8, '指紋應為 8 碼短雜湊')

    def test_fingerprint_tracks_content_not_mtime(self):
        """指紋只看內容：同樣內容＝同指紋；內容一改＝指紋必變（mtime 不變也會變）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mt = time.mktime(time.strptime('2026-09-14 18:20:11', '%Y-%m-%d %H:%M:%S'))
            _write(root / 'a.py', 'x = 1\n', mtime=mt)
            fp1 = build_info(root=root, paths=('.',))[1]
            fp2 = build_info(root=root, paths=('.',))[1]
            self.assertEqual(fp1, fp2, '同一份原始碼的指紋必須穩定')
            _write(root / 'a.py', 'x = 2\n', mtime=mt)   # 只改內容、mtime 不動
            fp3 = build_info(root=root, paths=('.',))[1]
            self.assertNotEqual(fp1, fp3,
                                '內容改了但 mtime 沒動時，指紋仍必須改變'
                                '（否則無法判斷容器內是不是新版程式）')

    def test_missing_paths_are_safe(self):
        """來源檔都不存在時要回 unknown，不可拋例外（例如精簡映像）"""
        with tempfile.TemporaryDirectory() as td:
            stamp, fp = build_info(root=Path(td), paths=('selfselect_trader.py', 'core'))
            self.assertEqual((stamp, fp), ('unknown', 'unknown'))

    def test_repo_defaults_cover_entrypoint(self):
        """預設掃描範圍必須涵蓋進入點與 core/（真的能算出這份 repo 的建置資訊）"""
        stamp, fp = build_info(root=Path(_ROOT))
        self.assertRegex(stamp, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertRegex(fp, r'^[0-9a-f]{8}$')


class TestBannerUsesBuildStamp(unittest.TestCase):
    """原始碼層級防護：banner 不得再把「啟動時間」當成建置時間"""

    def _srcs(self):
        out = []
        for rel in SRC_CANDIDATES:
            p = Path(_ROOT) / rel
            if p.exists():
                out.append((rel, p.read_text(encoding='utf-8')))
        return out

    def test_build_date_not_datetime_now(self):
        srcs = self._srcs()
        self.assertTrue(srcs, '找不到 selfselect_trader.py 源碼')
        for rel, src in srcs:
            self.assertFalse(
                'BUILD_DATE = datetime.now()' in src,
                f'{rel}: BUILD_DATE 不得用 datetime.now()（那會讓「建置」= 啟動時間）')
            self.assertTrue('build_info' in src,
                            f'{rel}: banner 必須使用 core.version.build_info()')

    def test_banner_shows_build_time_and_fingerprint(self):
        for rel, src in self._srcs():
            self.assertTrue('原始碼指紋' in src,
                            f'{rel}: banner 應同時顯示原始碼指紋（分辨同版號的不同建置）')


if __name__ == '__main__':
    unittest.main()
