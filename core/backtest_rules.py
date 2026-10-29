"""回測用的出場規則（純函式，可獨立測試）——2026-09-16 建立。

為什麼獨立成模組：回測腳本（`scripts/backtest_plan2_monthly_3group.py`）在 **import 時就會**載入
全市場法人/價格快取（實測 ~50 秒），把它們的規則寫在腳本裡會讓單元測試同樣付出這個代價。
規則抽出來後，測試只 import 這個輕量模組（毫秒級），多個回測腳本也能共用同一份定義。

口徑：與回測一致，**日頻、以當日收盤價判定**（回測所有買賣都走 `close_at()`）。
"""
import os



def leverage_for_target(util_avg, target_pct, max_leverage=5.0) -> float:
    """把「平均曝險比例」放大到 `target_pct`% 所需的部位倍數（`LEVERAGE`）。

    為什麼要有（2026-10-28 使用者需求）：自選股腿的平均曝險只有 ~57~86%（有時在等訊號、
    有時剛換股還在空倉）⇒ 直接拿「只用 79% 資金的報酬」去比 0050 那種 100% 曝險的基準並不公平。
    這個函式算出「若要平均用滿 `target_pct`% 的資金，每筆部位要放大幾倍」。

    - `util_avg`＝量到的平均曝險（0~1；`deployed ÷ 當下權益` 的平均）
    - `target_pct`＝目標曝險（%，100 = 用滿）
    - 回傳 **>= 1.0**（不縮小部位）且 <= `max_leverage`；資料不足／目標合理時回 1.0
    - ⚠️ 放大＝需要融資（現金可能為負）或只是「把閒置現金押上去」；回撤/夏普會等比例惡化，
      不是免費午餐。回測另以 `MARGIN_RATE` 對負現金計息。
    """
    try:
        util = float(util_avg)
        target = float(target_pct)
    except (TypeError, ValueError):
        return 1.0
    if util <= 0 or target <= 0:
        return 1.0
    lev = (target / 100.0) / util
    if lev < 1.0:
        return 1.0
    return float(min(lev, float(max_leverage)))


def above_ma200(close_series, as_of, window=200):
    """大盤年線濾網：`as_of`（含）以前最後一筆收盤 > 其 MA`window` ⇒ True（可以買）。

    與實盤一致（`core/market_filter.py` + `selfselect_trader.py`：買進前檢查
    `MARKET_TREND_FILTER`，指數在年線下就**跳過買進**，賣出不受影響）。

    回傳：
    - `True`  = 在年線之上（允許買）
    - `False` = 在年線之下（攔截買進）
    - `None`  = 資料不足 `window` 筆 ⇒ **不過濾**（與實盤「資料不足 ⇒ 跳過過濾」同義）

    只用 `as_of`（含）以前的資料（不會偷看未來）。
    """
    try:
        s = close_series[close_series.index <= as_of]
    except Exception:
        return None
    if s is None or len(s) < window or window <= 0:
        return None
    try:
        ma = float(s.iloc[-window:].mean())
        px = float(s.iloc[-1])
    except (TypeError, ValueError):
        return None
    if ma <= 0 or px <= 0:
        return None
    return px > ma


def selection_month_starts(month_starts, n) -> set:
    """每 `n` 個月取一個「換股（選股）點」→ set（`n=1` ⇒ 全部月份，＝舊的每月換股）。

    `month_starts` 是「每個月第 1 個交易日」的序列（任意順序，內部排序）。
    `n=12` ⇒ 期間內第 1、13、25… 個月（**不是**日曆對齊到 1 月；對齊後的實盤規則
    在 `core/selfselect_scheduler.is_selection_month`，那邊是日曆月 1/13/25…）。

    為什麼要抽成純函式（2026-10-28）：換股頻率是**回測與實盤都要一致**的口徑，
    而回測腳本 import 時會載入全市場快取（~50 秒）⇒ 規則留在 `core/` 才能被單元測試。
    """
    try:
        step = max(1, int(n))
    except (TypeError, ValueError):
        step = 1
    return set(sorted(month_starts)[::step])


def stop_hit(px, entry, stop_pct) -> bool:
    """硬停損是否觸發：`px <= entry × (1 − pct/100)`（以當日收盤價判定）。

    - `stop_pct <= 0`／無法解析 → 停用（回 False，維持基準行為）。
    - `entry <= 0`（尚無成本基礎）或 `px <= 0`（無價格）→ 不觸發。
    """
    try:
        pct = float(stop_pct)
    except (TypeError, ValueError):
        return False
    if pct <= 0:
        return False
    try:
        px = float(px)
        entry = float(entry)
    except (TypeError, ValueError):
        return False
    if px <= 0 or entry <= 0:
        return False
    return px <= entry * (1 - pct / 100.0)


def stop_loss_env(key: str = "STOP_LOSS_PCT", default: float = 0.0) -> float:
    """從環境讀硬停損百分比（未設或壞值 → `default`，0＝停用）。"""
    raw = os.getenv(key, None)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def skip_quarter_value(held_values, early_cash) -> float:
    """MDB「跳過換股、續抱」那一季的帳戶價值 = **續抱持股市值 ＋ 提前出場回籠的現金**。

    為什麼要有這個函式（2026-09-16 修 bug）：`stock_selector_grid.backtest_selector` 的
    skip 分支原本只把「還在手上的持股」加總當成帳戶價值，**把提前出場（`max_profit` 停利、
    或新加的停損）回籠的現金整包丟掉** ⇒ 帳戶憑空縮水。
    平時看不出來（沒有提前出場時帳戶本來就 100% 在股票上），但只要有任何提前出場
    （現金部位 > 0），該路徑就會把現金吃掉：實測 −10% 停損 2015-2025 因此從
    NT$8.6M 變成 NT$94K（−81%）、MDD −98.6% —— 數字荒謬到一看就知道不對。
    """
    return float(sum(held_values)) + float(early_cash or 0.0)


def first_stop_date(window, buy_px, stop_pct):
    """回傳 `window`（日期索引的收盤價序列）中**第一個**觸發硬停損的日期；無則 `None`。

    給回測引擎用（`scripts/stock_selector_grid.py::backtest_selector`）：在「買進 → 下次換股」
    之間逐日掃描，找到就**當日收盤出場**、現金回籠參與下一次再配置（與該引擎既有的
    `max_profit` 提前出場同語意 ⇒ **會複利**）。這正是 2026-09-16 第一版「事後重建曲線」
    做法量不出來的地方（重建曲線每段資本取自官方未停損帳戶值，損益不跨季累積）。
    """
    if not stop_pct:
        return None
    try:
        if float(stop_pct) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    for ts, px in window.items():
        if stop_hit(px, buy_px, stop_pct):
            return ts
    return None


def signal_strategy(locked, route_fn, sid, dts):
    """該日「算訊號要用哪個策略」——**自選股(auto) 進場鎖定的口徑**（2026-09-18 新增）。

    為什麼放在這裡：回測腳本 import 時會載入全市場快取（~50 秒），規則留在腳本裡會讓測試
    跟著變慢（同本模組開頭的說明）。這條規則是「實盤 vs 回測」對齊的關鍵之一。

    · `locked` 有值  → 回傳鎖定值（持有期間固定；對應實盤 `AUTO_FIXED_CACHE`）
    · `locked=None` → 回傳 `route_fn(sid, dts)`（**當日**型態路由；對應實盤監控期每日重路由）

    ⚠️ 舊回測在**選股日**就用 `pick_strategy_by_form(sid, sel_date)` 定策略並全程固定，
    但實盤是「買入那一刻才 `route_strategy()`」；`EXEC=signal`（等訊號）下兩者可能相隔數日
    ⇒ 會選到不同策略（口徑不一致）。改成本函式後：未進場每日重路由、**進場成交當天鎖定**。
    """
    return locked if locked else route_fn(sid, dts)


def strategy_after_exit(locked, shares):
    """**賣出（部位歸零）後是否還保有策略鎖定** —— 2026-09-22 對齊實盤。

    · 實盤：`live_trader_multi.py` 在 auto 股 `holdings <= 0` 時
      `AUTO_FIXED_CACHE.pop(symbol)` ⇒ 下次進場**重新路由**（2006 實例：9/16 ma_cross 賣、
      9/18 由 breakout 買回）。
    · 舊回測：賣出只把 `shares` 設 0、`strat` 留著 ⇒ 同月再次進場沿用舊策略、不重路由
      ⇒ 與實盤不一致（實測 2015-2025 正常組 +257.5% → +291.0%、高獲利 +228.1% → +183.2%）。

    回傳值直接寫回 `positions[sid]["strat"]`：持有中回傳原鎖定值，歸零則回 `None`（未鎖定 → 每日重路由）。
    """
    try:
        return locked if float(shares) > 0 else None
    except (TypeError, ValueError):
        return locked


# ── 環境變數覆寫保護（2026-10-05 事故後新增）─────────────────────────────
# 事故：回測腳本在讀參數**之前**就
#   `import stock_selector_grid`，而後者在 **import 時**執行 `load_dotenv(override=True)`
#   （2026-10-01 為了讓 `docker exec` 的工具讀到「現行 `.env`」而刻意如此）
#   ⇒ **`.env` 的值會蓋掉呼叫端傳入的環境變數覆寫**。
#   實測症狀：`MIN_DRAW_BACK=0 python 回測腳本 ...` 的輸出卻是
#   `"min_drawback": 30.0`（`.env` 的值）、`skipped_quarters` 照樣跳過 4 季 —— 該維度整批掃描無效，
#   而且**沒有任何錯誤訊息**（數字漂亮、看起來正常）。
# 修法：呼叫端在 import 前 `snapshot_env_overrides()`、import 後 `apply_env_overrides()`
#   ⇒ 語義＝「明確指定的 env 參數 > `.env`」（`.env` 只當預設值來源）。
ENV_OVERRIDE_KEYS = (
    # 回測腳本的環境變數旋鈕
    "MW", "TW", "SW", "MAF", "MP", "MOM_DAYS", "CW", "M2D", "M2W",
    "AUTO", "MODE", "INST_CONFIRM", "INST_DAYS",
    "MIN_DRAW_BACK", "MIN_DRAW_BACK_UNLIMITED", "STOP_LOSS_PCT", "MAX_PROFIT",
    # 每月換股回測（backtest_plan2_monthly_3group.py）的旋鈕
    "START", "END", "POOL_N", "TOP_N", "INITIAL", "MIN_PRICE", "DCA_MONTHLY",
    "STRAT_MODE", "SWAP_MODE", "EXEC", "LOCK_AT", "MEGA_N", "MDB_UNLIMITED",
    "OVERHEAT", "OVERHEAT_USE_PER", "MAX_PCT_FROM_HIGH", "MAX_YTD_GAIN", "MAX_PER",
    "MIN_OVERHEAT", "ENTRY_OVERHEAT", "OH_RSI_TH", "OH_DIST_WIN", "OH_DIST_TH",
    "OH_ENTRY_MODE", "HOT_EXIT", "HOT_EXIT_GROUPS", "HOT_TP_PCT", "HOT_TRAIL_PCT",
    "HOT_THRESHOLD", "GROUPS_ONLY",
    # 2026-10-28 新旋鈕（換股頻率／大盤年線／閒置停泊／部位放大／口徑 profile／固定名單）
    "REBAL_MONTHS", "MARKET_FILTER", "MF_WINDOW", "IDLE_CASH_ASSET", "PARK_COST",
    "LEVERAGE", "SCALE_TO_UTIL", "MARGIN_RATE", "PROFILE", "POOL_FIXED",
    "FILL_MODE", "SELFSELECT_FILL_MODE",
    # 2026-10-29：選股口徑（評分模型／因子／宇宙）——這些也必須「明示優先」，
    #   否則 `PRESET=aggressive FACTOR_REVENUE=0` 會被 preset 覆寫，跟文件寫的規則相反。
    "SCORING_MODEL", "FACTOR_REVENUE", "MAX_PER_SECTOR", "UNIVERSE_DELISTED",
    "PRESET", "SELFSELECT_PRESET", "SELFSELECT_FACTOR_REVENUE", "SELFSELECT_MAX_PER_SECTOR",
    # 資料來源／選股工具
    "HIST_SHARES", "SELECTOR_LOOKBACK_DAYS",
)


def snapshot_env_overrides(keys=ENV_OVERRIDE_KEYS, env=None) -> dict:
    """把「呼叫端明確設定」的參數值拍快照（只取有設定的鍵）。"""
    src = os.environ if env is None else env
    return {k: src[k] for k in keys if k in src}


def apply_env_overrides(snapshot, env=None) -> None:
    """把快照套回（覆蓋 `.env` 蓋掉的值）；不新增／不刪除其他鍵。"""
    dst = os.environ if env is None else env
    dst.update(snapshot or {})

