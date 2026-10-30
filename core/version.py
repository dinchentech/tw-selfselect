"""TW SelfSelect Trader 版本（單一來源，所有模組共用）

## 版號規則（2026-10-29 使用者裁定，**這是硬規則**）

1. **只要程式有修改，版號就要 +1**（`1.1.0` → `1.1.1` → `1.1.2`…），文件-only 的修改不必動版號。
2. **大升版（跳到 `1.2.0` / `2.0.0` 這種）由使用者主動通知**，不要自己決定。
3. 版號會出現在：啟動 banner、Telegram 啟動／收盤訊息、儀表板標題 ⇒ 換版後 VM 上一眼就能確認跑的是哪一版。
4. `deploy_source.sh` 一律**由使用者手動執行**，任何自動化流程（含 AI agent）不得代跑部署。

## 版本沿革

- `1.0.0`（2026-08）由 tw-autotrader v4.54 的自選股腿拆出後重新起版。
- `1.1.0`（2026-10-29）AI 選股模式（`SELFSELECT_AI`，D1 手動／逾期 fallback）＋ zscore 評分器（`SELFSELECT_SCORING_MODEL`，預設）
  ＋ 選股口徑 preset（`SELFSELECT_PRESET`，預設 `revenue`：池 100＋營收因子）＋實盤與回測逐位一致的驗證；
  同批把宇宙補回 62 檔已下市個股、PER 補到 672/672、月營收補到 645/672。
- `1.1.6`（2026-10-30）教材：W7 S14 補上 **D1／D2 的定義**（D1＝每月選股第一日＝該月第 1 個交易日，盤後 13:36 起選股、AI 期限 13:50；
  D2＝第 2 個交易日 13:25–13:30 依訊號換股），並補「逾期 fallback 不會卡住」「名單沿用到下一個 D1」兩條說明；講稿同步。
- `1.1.5`（2026-10-30）教材：W7 的「一句話總結」補上專案狀態——**自 2026-10-30 起開始實測、持續改進，
  最新更新以 Git 專案為準**（S2 與 S18 各加一行＋講稿同步）。同批修掉編號項目重複的項目符號。
- `1.1.4`（2026-10-30）教材：新增 W7 講稿版（`plans/ppt/make_w7.py` 產生）＋ `W7-解說腳本.md`，
  主題為 v1.1 之後的 zscore（預設）／AI 選股／參數／改進方向。只有 `plans/` 教材與版本字串改動，**執行行為不變**（指紋仍會變，因為 `core/version.py` 在 `BUILD_PATHS` 內）。
- `1.1.3`（2026-10-29）儀表板發佈改走 **`gh-pages` 分支（Pages 分支模式）**：`publish_dashboard.sh` 改寫
  `gh-pages` 根目錄的 `index.html`，移除 `.github/workflows/pages.yml`；GitHub Pages Source 已改為
  「Deploy from a branch → `gh-pages` / (root)」並驗證線上內容一致。先前試的 `dash`＋Actions 方案作廢（見下）。
- `1.1.2`（2026-10-29）修 `scripts/ai_pick_ab.py` 的 `NameError`：`load_historical_shares()` 只在 `honest_pool()` 內 import，
  實際呼叫在 `main()` ⇒ 執行會炸；CI 的 pyflakes「undefined name」檢查抓到。
- `1.1.1`（2026-10-29）儀表板發佈改推 **`dash` 分支**（`scripts/vm/publish_dashboard.sh`）＋ `pages.yml` 觸發分支加 `dash`：
  機器人不再往 `main` 推 commit，解決「人手 push 被拒（非 fast-forward）」。GitHub Pages 設定不用改。
"""
import hashlib
from datetime import datetime
from pathlib import Path

APP_VERSION = "1.1.6"

# ── 建置標記 ─────────────────────────────────────────────────────────────
# ⚠️ 這裡**不是**「程式啟動時間」。原本 banner 用 `datetime.now()` 當 BUILD_DATE，
# 結果「建置日期」永遠等於啟動時間（VM 實證 2026-09-14 18:57 啟動顯示 18:57），
# 無法回答「容器裡跑的是不是剛 deploy 的那版程式」（2026-09-15 修）。
# 建置時間 = 執行期原始碼檔的最新 mtime（容器內≈映像 COPY 進去的時間）；
# 指紋 = 檔案內容 sha1（與 mtime 無關）→ 內容一改就一定看得出來。
BUILD_PATHS = ('selfselect_trader.py', 'core', 'utils', 'strategies', 'config', 'data', 'scripts')


def _iter_source_files(root, paths):
  for rel in paths:
    p = Path(root) / rel
    if p.is_file():
      yield p
    elif p.is_dir():
      for f in sorted(p.rglob('*.py')):
        if '__pycache__' in f.parts:
          continue
        yield f


def build_info(root=None, paths=BUILD_PATHS):
  """回傳 (建置時間字串, 原始碼指紋 8 碼)。找不到任何來源檔時回 ('unknown', 'unknown')。"""
  try:
    files = sorted(_iter_source_files(root or Path(__file__).resolve().parent.parent, paths))
    if not files:
      return ('unknown', 'unknown')
    ts = max(f.stat().st_mtime for f in files)
    h = hashlib.sha1()
    for f in files:
      h.update(f.name.encode('utf-8'))
      h.update(f.read_bytes())
    return (datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'), h.hexdigest()[:8])
  except Exception:
    return ('unknown', 'unknown')
