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
- 2026-10-30 更正：`1.1.4`～`1.1.8` 五個版號是為**教材變更**（`plans/ppt` W7 講稿版、解說腳本、mp4）誤升的，
  依使用者裁定「**非程式本身的變更不要動版號**」**撤回**，程式版本回到 `1.1.3`。
  教材／文件／`.env`／cache／報告 JSON 的變更一律不升版號；只有 `core/`、`scripts/`、`strategies/`、`data/`、`utils/`、
  `selfselect_trader.py` 這類執行期程式的修改才 +1。
- `1.1.8`（2026-10-31）**回測主表改用「實盤口徑」**（使用者裁定）：`STRAT_MODE=form`（＝實盤 `strategy:"auto"`
  型態路由）＋`IMM_OVERHEAT=1`（＝實盤買進前過熱閘門），2016-2025 為 **+926.5%／年化 26.23%／MDD −45.6%／夏普 1.01**
  （0050 +477.6%／−34.0%／1.06）；舊的輪替口徑 +1323.6%／1.15 降級為「上限參考」。
  同批修掉兩個會**默默算錯**的問題：
  ① 回測端 preset 優先序——`active_name()` 原本是 `SELFSELECT_PRESET` 優先，本機 `.env` 有 `SELFSELECT_PRESET=aggressive` 時
  `PRESET=current` 會被忽略並照跑 aggressive（實測跑 current 得到 +1323.6% 的 aggressive 結果）⇒ 回測端改為 `PRESET` 優先；
  ② `walk_forward.py` 快取不分口徑 ⇒ 換口徑重跑會沿用舊結果，現改為檔名帶 `{mode}_{imm}`。
  同步更新 `core/selection_presets.py` 的 preset 說明與啟動警語（改報實盤口徑，並寫明夏普全部輸 0050）。
- `1.1.7`（2026-10-31）新增**選股口徑實驗旋鈕**（回測端、預設全關 ⇒ 行為不變）：
  `IMM_OVERHEAT`（immediate 買進也套實盤的過熱閘門）、`PRERANK_R63_PCT`／`W_DIST`（降低追高）、
  `NONMOM_SLOTS`／`NONMOM_QUANTILE`／`NONMOM_REV_MIN`（低基期＋營收轉機名額）。
  純函式工具進 `core/scoring.py`（`prerank`／`nonmom_picks`／`pick_sleeves`），`test/test_scoring.py` 加 12 個測試。
  當批測出兩個重要事實：① 實測 600 筆選股 98% 站上 MA60／MA200、r63 中位 +31.5%，實盤 `auto` 路由有 84.8% 落到順勢策略；
  ② 回測主表的輪替口徑（+1323.6%／夏普 1.15）**不是實盤路徑**，實盤口徑（`STRAT_MODE=form` ＋過熱閘門）為
  +926.5%／MDD −45.6%／夏普 1.01。三個修正方向在 2016-2025 上全部使總報酬變差（12 組網格無一勝出）。
- `1.1.6`（2026-10-30）新增 `scripts/walk_forward.py`（前向驗證）：擴張式訓練窗逐年挑參數、只用次一年 OOS 驗證，
  輸出 OOS 串接報酬／逐年勝負／in-sample→OOS 退化，並附全期 16 組參數鄰居表（in-sample 穩健性）。
  純新增分析工具，**不改變實盤預設口徑與任何交易邏輯**。
- `1.1.5`（2026-10-30）**預設選股口徑改為 `aggressive`**（使用者裁定；先前 `revenue`）：池 150＋營收因子＋產業上限 2，
  2016-2025 +1323.6%／年化 30.42%／MDD −40.2%／夏普 1.15（0050 +477.6%／−34.0%／1.06）。
  `monthly_rebalance_picker.py` 與回測在**預設口徑**時也會印代價警語（`warning_text(is_default=True)`）；
  文件（README／使用手冊／策略說明／.env.example）同步，`.env` 的 `SELFSELECT_POOL_N` 由 100 改 150。
- `1.1.4`（2026-10-30）修 `scripts/vm/publish_dashboard.sh`：`git fetch --depth 1 origin <branch>` **不會**建立
  remote-tracking ref，原本 `checkout -B "$BRANCH" "origin/$BRANCH"` 在 VM 上實測失敗
  （`fatal: 'origin/gh-pages' is not a commit`）⇒ 改用 `FETCH_HEAD`。此修正**只需重跑
  `./scripts/vm/install_dashboard_publish.sh`**（腳本住在 VM 主機 `/usr/local/bin`，不必重新部署 image）。
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

APP_VERSION = "1.1.8"

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
