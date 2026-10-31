"""方案二改「每月換股」+ 三組獨立選股策略回測（2022-2025, NT$500,000 單筆）— 訊號執行版

用法: python scripts/backtest_plan2_monthly_3group.py
環境覆寫: START END POOL_N TOP_N REBAL_MONTHS INITIAL MIN_PRICE MOM_DAYS
         （REBAL_MONTHS=1 每月換股＝預設；12＝一年換一次股）
         （LEVERAGE=1.26 部位放大；SCALE_TO_UTIL=100 自動把平均曝險等效拉到 100%）

設計（誠實、無事後之明、依使用者修正）:
- 候選池 = 誠實池：每季以「當時市價 × 歷史股本」重建當時市值前 POOL_N 大（無倖存者偏差）。
- 每月換股：月初選股（僅用「上個月最後交易日」及以前資料），
  **選定即買入**（等權分配當下可用資金）；持股「依策略訊號進出」——
  賣出訊號(-1) 才會出場，**不做月底強制平倉**。
- 月內賣出空出的資金回到該股 bucket；當月被剔除（deselect）的股票的 bucket 併回現金池，
  於**下個月重新選股**時分配給新選標的。
- 三組 = 三套獨立選股規則（各有不同策略池），各跑一次完整回測。
- 計入交易成本：手續費 0.1425% + 證交稅 0.3%（ETF 0.1%）。
- 每月最多 TOP_N 檔（預設 5，≤10 限制內）。
"""
import os, sys, json as _json, math
# 專案根：**不要寫死作者的家目錄**（container 內是 /app，沒有 /home/frank/...）
# 2026-09-22 修：原本 `sys.path.insert(0, "/home/frank/tw-autotrader")` ＋ `os.chdir(...)`，
#   在本機能跑、在 container 內直接 ModuleNotFoundError／FileNotFoundError
#   （`docker exec tw_selfselect_bot python scripts/monthly_rebalance_picker.py` 必炸）。
_f = globals().get("__file__", "")
_ROOT = (os.path.dirname(os.path.dirname(os.path.abspath(_f)))
         if _f and not str(_f).startswith("<") else os.getcwd())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.isdir(_ROOT):
    os.chdir(_ROOT)
# ⚠️ 環境變數覆寫保護（2026-10-05 事故的同一類問題）：
#   `scripts/stock_selector_grid` 在 **import 時**執行 `load_dotenv(override=True)`
#   （為了讓 docker exec 的工具讀到現行 `.env`）⇒ 會**蓋掉呼叫端傳入的環境變數**。
#   症狀：`POOL_N=50 python scripts/backtest_plan2_monthly_3group.py` 卻仍用 `.env` 的值，
#   表面上完全看不出來（數字漂亮、無錯誤訊息）。⇒ 先快照、import 後再套回。
from core.backtest_rules import snapshot_env_overrides, apply_env_overrides, strategy_after_exit  # noqa: E402
_ENV_OVERRIDES = snapshot_env_overrides()

# `.env` 一律以「檔案」為準（override=True）——見下方長註解；**必須在參數讀取之前**，
# 而「套回」則必須在**最後一次**載入 `.env` 之後（否則套回後又被蓋掉）。
from dotenv import load_dotenv  # noqa: E402
load_dotenv(override=True)

import pandas as pd, numpy as np
from core.cache_io import load_cache_or_raw
from core.candidate_pool import (build_quarterly_pool, include_delisted,
                                load_historical_shares)
import scripts.stock_selector_grid as ssg   # noqa: E402  ← 這個 import 也會載一次 .env

apply_env_overrides(_ENV_OVERRIDES)          # 明確指定的 env > .env（.env 只當預設來源）

# ── 口徑 profile（2026-10-28）：PROFILE=conservative|fair|levered|raw
#   只填「使用者沒有明示」的變數；明示的環境變數一律優先。
_PROFILE_NAME = os.getenv("PROFILE", "").strip()
if _PROFILE_NAME:
    from core.backtest_profiles import expand as _profile_expand, resolve as _profile_resolve
    _prof = _profile_resolve(_PROFILE_NAME)          # 名稱錯 → ValueError（大聲失敗）
    for _k, _v in _profile_expand(_PROFILE_NAME, _ENV_OVERRIDES).items():
        os.environ[_k] = _v
    print(f"口徑 profile: {_PROFILE_NAME}（{_prof['label']}）→ " +
          "、".join(f"{k}={v or '(空)'}" for k, v in _prof["env"].items()))
# ── 選股口徑 preset（2026-10-29）：PRESET=current|revenue|aggressive
#   只填「使用者沒有明示」的變數；`current` 是預設（＝與舊行為相同）。後果會印出來，不偷偷生效。
from core.selection_presets import (DEFAULT_PRESET as _DEFAULT_PRESET, HIGH_RETURN_PRESETS as _HIGH_RETURN,
                                    PRESETS as _PRESETS, active_name as _preset_name,
                                    expand as _preset_expand, warning_text as _preset_warning)

_PRESET = _preset_name()
for _k, _v in _preset_expand(_PRESET, _ENV_OVERRIDES).items():
    os.environ.setdefault(_k, _v)          # 明示的環境變數一律優先（不被 preset 蓋掉）
print(f"選股口徑 preset: {_PRESET}（{_PRESETS[_PRESET]['label']}）→ " +
      "、".join(f"{k}={os.environ.get(k)}" for k in _PRESETS[_PRESET]["knobs"]))
if _PRESET == _DEFAULT_PRESET and _PRESET in _HIGH_RETURN:
    print(_preset_warning(is_default=True, name=_PRESET))
elif _PRESET in _HIGH_RETURN:
    print(_preset_warning(name=_PRESET))

from strategies.bollinger import bollinger_reverse_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.breakout import breakout_strategy

START = os.getenv("START", "2022-01-01")
END = os.getenv("END", "2025-12-31")
POOL_N = int(os.getenv("POOL_N", "100"))
# 固定名單池（2026-10-28 新增，評估用）：`POOL_FIXED=2330,2454,...` 時**不用誠實逐季池**，
#   直接拿這份名單當候選池（用來回答「同一批人工挑的股票，換成我們的規則會怎樣」）。
#   預設空 = 走誠實池（市值前 POOL_N）。
POOL_FIXED = [x.strip() for x in os.getenv("POOL_FIXED", "").split(",") if x.strip()]
# 選不滿 N 檔時怎麼辦（2026-10-28 新增，使用者選項）：
#   proportional（預設）＝就選出的那幾檔，資金平均分配（每檔吃 1/N_selected）
#   topup             ＝補滿：仍要求技術條件（價格／動能或波動／均線位階）通過，
#                        但**放寬「過熱」與「法人」兩道濾網**，依分數順序補到 N 檔
# 兩者都完全可重現；只是「寧缺勿濫」或「寧濫勿缺」的取捨。
# AI 選股名單（2026-10-29 新增，分析用）：`AI_PICKS_FILE=path.json`，
# 格式 `{"2022-01-03": ["2330","2454",...], ...}`；**只有正常組**會用（其他組照原本規則）。
# 有對應日期的就用該清單（不看濾網），沒有的日期照原本規則選 ⇒ 可以跟「純程式」同口徑比較。
AI_PICKS_FILE = os.getenv("AI_PICKS_FILE", "").strip()
_AI_PICKS = {}
_AI_KEYS = []
if AI_PICKS_FILE:
    import json as _json
    try:
        with open(AI_PICKS_FILE, encoding="utf-8") as _f:
            _raw = _json.load(_f)
        _AI_PICKS = {str(k): [str(x) for x in v] for k, v in (_raw.get("picks") or _raw).items()
                     if isinstance(v, (list, tuple))}
        print(f"AI 名單檔：{AI_PICKS_FILE}（{len(_AI_PICKS)} 個日期；僅正常組使用）")
        _AI_KEYS = sorted(_AI_PICKS)
    except Exception as _e:
        raise SystemExit(f"❌ 讀不到 AI_PICKS_FILE（{_e}）")

# 評分模型（2026-10-29 新增）：
#   legacy（預設）＝現行的 ssg.score_stock() 綜合分（動能＋技術面＋穩定度＋催化劑，權重見 DEFAULT_PARAMS）
#   zscore        ＝「AI 代理」用的固定公式：先篩 0 < PER ≤ 40，再以當日橫斷面 z 分數
#                    score = 0.40·z(63日報酬) + 0.25·z(20日報酬) + 0.20·z(距52週高) + 0.15·z(−PER)
#                    （2016-2025 實測：+110.0% vs legacy +57.0%，見 README 六組合段）
SCORING_MODEL = os.getenv("SCORING_MODEL", "zscore").strip().lower()
# 營收成長因子（2026-10-29）：把月營收 YoY 加進 z 分數（權重配置見 core/scoring.py WEIGHTS_REVENUE）
FACTOR_REVENUE = os.getenv("FACTOR_REVENUE", "1") == "1"
# 產業分散上限（2026-10-29）：每個產業最多取幾檔（0＝不限）。需要 cache/stock_industry.pkl
MAX_PER_SECTOR = int(os.getenv("MAX_PER_SECTOR", "0"))
if SCORING_MODEL not in ("legacy", "zscore"):
    raise SystemExit(f"❌ SCORING_MODEL 只能是 legacy 或 zscore（收到 {SCORING_MODEL!r}）")

FILL_MODE = os.getenv("FILL_MODE", "proportional").strip().lower()
if FILL_MODE not in ("proportional", "topup"):
    raise SystemExit(f"❌ FILL_MODE 只能是 proportional 或 topup（收到 {FILL_MODE!r}）")
# 補滿時**只用個股**（2026-10-29 使用者裁定）：ETF 只用在「閒置資金停泊」（IDLE_CASH_ASSET），
# 不參與選股、也不拿來補滿。補滿＝先放寬「過熱／法人」，仍不足再依 63 日動能補。
TOP_N = int(os.getenv("TOP_N", "5"))
# 換股頻率（2026-10-28 新增）：每 REBAL_MONTHS 個月才「選股一次」（剔除未選中者＋補新標的）。
#   1 = 每月（預設，與舊行為完全相同）；12 = 一年換一次股（母專案「逐年檢討」那種節奏）。
#   ⚠️ 非選股月份仍照常逐日跑策略訊號：賣出、同檔回補都照舊，只是不會被換成新標的。
REBAL_MONTHS = max(1, int(os.getenv("REBAL_MONTHS", "1")))
# ── 資金利用率「等效放大」（2026-10-28 新增，使用者需求）───────────────────
# 為什麼：自選股腿的平均曝險只有 ~57~86%（等訊號、剛換股還在空倉）⇒ 直接拿「只用 79% 資金的報酬」
#   去比 0050（100% 曝險）不公平。兩個旋鈕：
#   LEVERAGE=1.26      → 每筆部位固定放大 1.26 倍（現金會轉負 ⇒ 等同融資，按 MARGIN_RATE 計息）
#   SCALE_TO_UTIL=100  → **自動兩段式**：先跑一遍量出該組 util_avg，再把部位放大到「平均用滿 100%」
#   ⚠️ 放大不是免費午餐：報酬與回撤一起放大，且超額部位要付融資利息（現金為負時）。
# ── 大盤年線濾網（2026-10-28 新增，與實盤一致）───────────────────────────
# 實盤買進前會檢查「加權指數是否在 MA200 之上」（core/market_filter.py，.env 的 MARKET_TREND_FILTER=true）；
# 回測原本**沒有這條規則** ⇒ 2018／2022 空頭年的回測比實盤更差（實盤那段時間不會買）。
# 這裡用 **MARKET_FILTER=1** 重現（刻意不用 MARKET_TREND_FILTER：.env 已設 true，
# 直接沿用會讓所有既有回測靜默改變）。只擋買進，賣出照舊（與實盤相同）。
# ── 閒置資金停泊（2026-10-28 新增）：`IDLE_CASH_ASSET=0050`
# 為什麼：自選股腿常態有 40%~55% 的資金「等訊號／被年線擋住」而領 0% ⇒ 直接跟 0050（永遠滿倉）比不公平。
# 設這個變數＝把「每天真正閒置的錢」（現金＋已分配但還沒買進的額度）改押在該標的上，
# 需要買股票時自然釋出（等於母專案 45% ETF 的結構，但不需要融資）。
# 口徑：每日把「閒置金額 × 該標的當日報酬 − 年化換手成本」記進現金（PARK_COST，預設 0.2%/年）；
#       閒置金額每天重算 ⇒ 獲利自動滾入（複利）。
IDLE_CASH_ASSET = os.getenv("IDLE_CASH_ASSET", "0050").strip()   # 預設停泊 0050；要關掉請設空字串
PARK_COST = float(os.getenv("PARK_COST", "0.002"))     # 停泊部位的換手成本（年化）
MARKET_FILTER = os.getenv("MARKET_FILTER", "0").strip().lower() in ("1", "true", "yes", "on")
MF_WINDOW = int(os.getenv("MF_WINDOW", "200"))       # 年線視窗（交易日）
LEVERAGE = max(0.0, float(os.getenv("LEVERAGE", "1")))
SCALE_TO_UTIL = float(os.getenv("SCALE_TO_UTIL", "0"))       # 0=關；100=等效把平均曝險拉到 100%
MARGIN_RATE = float(os.getenv("MARGIN_RATE", "0.06"))        # 年利率，只對負現金（融資）計息
INITIAL = float(os.getenv("INITIAL", "500000"))
DCA_MONTHLY = float(os.getenv("DCA_MONTHLY", "0"))  # >0 = 每月定額(方案一)；0 = 一筆資金(方案二/預設)
MIN_PRICE = float(os.getenv("MIN_PRICE", "5"))
MOM_DAYS = int(os.getenv("MOM_DAYS", "63"))
COMMISSION = ssg.COMMISSION_RATE
# ── 方案三濾網（可選）──────────────────────────────────
INST_CONFIRM = os.getenv("INST_CONFIRM", "1") == "1"   # 法人確認：近 N 日法人淨買超 > 0 才入選
INST_DAYS = int(os.getenv("INST_DAYS", "15"))
MIN_DRAW_BACK = float(os.getenv("MIN_DRAW_BACK", "30"))  # 股災防護：選股日總回撤 > N% 則該月不換股（續抱）
MDB_UNLIMITED = os.getenv("MDB_UNLIMITED", "0") == "1"   # 1=無限延長(>門檻就一直續抱)；0=最多延長一輪
STRAT_MODE = os.getenv("STRAT_MODE", "group")            # group=策略綁組別；form=依個股型態自適應(四種開放)
# LOCK_AT：auto 策略的「鎖定時點」（只作用 STRAT_MODE=form）
#   fill      = 進場成交當天鎖定（**預設，與實盤一致**：監控期每日重路由決定買訊、買入即鎖定）
#   selection = 選股日就鎖定（2026-09-18 前的舊口徑；實盤從未這樣做）
# ⚠️ 兩者不是「誰對誰錯」而是**規則不同**，勝負隨期間改變 ⇒ 要用它當生產規則前必須多期間驗證
#   （實測：2025-09~2026-09 正常組 selection +117.47% > fill +92.06%；但見下方 A/B 結論）
LOCK_AT = os.getenv("LOCK_AT", "fill")
SWAP_MODE = os.getenv("SWAP_MODE", "full")               # full=每月掉出前N就賣(現狀)；addonly=只依訊號出場、不強賣仍持的(C)
EXEC = os.getenv("EXEC", "immediate")                    # immediate=選股日立即買(A)；signal=等進場訊號才買(自選股/B, 等訊號)
# ── 人工降溫（過熱過濾，2026-09-06 新增）──────────────────
OVERHEAT = os.getenv("OVERHEAT", "1") == "1"             # 1=啟用過熱過濾(近52週高/YTD/高PE)；0=關(對照用)
OH_MAX_FROM_HIGH = float(os.getenv("MAX_PCT_FROM_HIGH", "7"))  # 距52週高點≤此%＝貼近52週高
OH_MAX_YTD = float(os.getenv("MAX_YTD_GAIN", "100"))          # YTD漲幅>此%＝過大
OH_MAX_PER = float(os.getenv("MAX_PER", "45"))                # 本益比>此值＝明顯偏高
OH_MIN_COUNT = max(1, min(3, int(os.getenv("MIN_OVERHEAT", "2"))))  # 1=任一 / 2=≥2(預設) / 3=三項全中『且』
OH_USE_PER = os.getenv("OVERHEAT_USE_PER", "1") == "1"    # 1=用FinMind P/E(慢/限流)；0=僅價量(近52週高+YTD)
MEGA_N = int(os.getenv("MEGA_N", "20"))                   # 權值股動能組：取當時市值前 N 大(權值股)範圍
# ── 過熱進場→自適應緊離場（2026-09-06 新增）─────────────────
HOT_EXIT = os.getenv("HOT_EXIT", "0") == "1"             # 1=過熱入場的持股用目標+移動停損提前落袋
HOT_TP_PCT = float(os.getenv("HOT_TP_PCT", "0"))          # 過熱入場：達 +此% 即(獲利目標)落袋；0=停用
HOT_TRAIL_PCT = float(os.getenv("HOT_TRAIL_PCT", "10"))   # 過熱入場：從峰值回撤 >此% 即(移動停損)出場；0=停用
HOT_THRESHOLD = max(1, min(3, int(os.getenv("HOT_THRESHOLD", "1"))))  # 過熱旗標命中≥此數視為「過熱入場」
# ── 買入當下的「過熱閘門」（策略訊號 sig==1 時拒買過熱；2026-09-08 新增，參數化）──
ENTRY_OVERHEAT = os.getenv("ENTRY_OVERHEAT", "0") == "1"   # 1=啟用(簽到買入當下拒買過熱) 0=關(對照)
OH_RSI_TH = float(os.getenv("OH_RSI_TH", "80"))            # RSI(14) >此值＝超買(拒買)
OH_DIST_WIN = int(os.getenv("OH_DIST_WIN", "63"))          # 距「N 日高」視窗
OH_DIST_TH = float(os.getenv("OH_DIST_TH", "8"))           # 距 N 日高 ≤此%＝貼近高點(拒買)
OH_ENTRY_MODE = os.getenv("OH_ENTRY_MODE", "both")         # any=任一命中拒買 / both=兩者都中才拒買(推薦, 較精準)
HOT_EXIT_GROUPS = set(x.strip() for x in os.getenv("HOT_EXIT_GROUPS", "normal,megacap,stable").split(",") if x.strip())  # 對哪些組套用緊離場(高風險/追強除外)
# ── 硬停損（2026-09-16 新增，評估用；預設 0=關閉＝基準行為）──
# 為什麼：實盤沒有個股停損（出場只靠策略訊號），使用者問「怎麼沒有虧 10% 退場」。
# 這裡提供對照組：`STOP_LOSS_PCT=10` = 收盤價 ≤ 成本 ×(1−10%) 即全部出場（日頻收盤口徑，與本檔一致）。
# 規則本體在 core/backtest_rules.py（純函式、可獨立測試，不必匯入本檔的重型快取載入）。
from core.backtest_rules import (signal_strategy, stop_hit, stop_loss_env, leverage_for_target,  # noqa: E402
                                 above_ma200)

STOP_LOSS_PCT = stop_loss_env("STOP_LOSS_PCT", 0.0)
_MF_BLOCKED = [0]      # 大盤年線濾網累計擋下的買進次數（每次跑回測重設）

# 產業對照／月營收快取（由 load_data() 填入）。這裡先給空預設值：
#   2026-10-30 預設選股口徑改成 aggressive（MAX_PER_SECTOR=2）後，`_zscore_picks()`
#   會在沒有呼叫 load_data() 的路徑（例如單元測試）直接引用 INDUSTRY ⇒ 先前的 NameError。
INDUSTRY: dict = {}
REV_ROWS: dict = {}

GROUPS = {
    "high_profit": {"label": "高風險（高波動）", "strats": ["ma_cross", "breakout"]},
    "normal":      {"label": "正常",          "strats": ["bollinger", "ma_cross", "vwap", "breakout"]},
    "stable":      {"label": "高穩定(低風險)", "strats": ["bollinger", "vwap"]},
    "megacap":     {"label": "權值股動能", "strats": ["ma_cross", "breakout"]},
}

STRAT_FUNCS = {
    "bollinger": bollinger_reverse_strategy,
    "ma_cross": ma_cross_strategy,
    "vwap": vwap_deviation_strategy,
    "breakout": breakout_strategy,
}


def load_data():
    """載入回測所需資料（**不再在 import 時執行** —— 否則光 import 就要載數百檔股票）。

    在 `main()` 一開始呼叫。回測函式仍透過模組全域取用（`data`／`pools`／`ALL_DATES`…）。
    """
    global hist
    global _
    global union
    global data
    global hist_for_pool
    global all_data_pool
    global pools
    global inst_conf
    global INST_CONFDATES
    global _mkt0full
    global FULLCAL
    global _mkt0
    global MASTER
    global ALL_DATES
    global MONTH_STARTS
    global MONTH_START_SET
    global SELECTION_MONTH_START_SET
    global IDX_CLOSE, MF_SOURCE
    global INDUSTRY, REV_ROWS
    # ── 載入資料 ─────────────────────────────────────────────
    hist, _src = load_historical_shares()
    print("歷史股本: {} 檔（{}）".format(len({k[0] for k in hist}), "+".join(_src)))
    _extra = set(POOL_FIXED)
    if IDLE_CASH_ASSET:
        _extra.add(IDLE_CASH_ASSET)
    union = sorted({k[0] for k in hist} | _extra)
    data = {}
    for sid in union:
        df = ssg.load_stock(sid)
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["close"])
        if len(df) > 60:
            data[sid] = df
    print(f"價格載入: {len(data)} 檔 (聯集池 {len(union)})")

    hist_for_pool = {(sid, q): v for (sid, q), v in hist.items()}
    all_data_pool = {}
    for sid, df in data.items():
        d2 = df.reset_index()
        d2 = d2.rename(columns={d2.columns[0]: "date"})
        all_data_pool[sid] = d2
    pools = build_quarterly_pool(hist_for_pool, all_data_pool, top_n=POOL_N)
    print(f"逐季池: {len(pools)} 季點, 空池 {sum(1 for p in pools.values() if not p)}")
    if POOL_FIXED:
        _have = [s for s in POOL_FIXED if s in data]
        print(f"⚠️ 固定名單模式（POOL_FIXED）: {len(_have)}/{len(POOL_FIXED)} 檔有價格資料 → {_have}")

    # 法人確認資料（可選）
    inst_conf = None
    INST_CONFDATES = []
    if INST_CONFIRM:
        inst_conf = ssg.load_twse_inst_merged()
        INST_CONFDATES = sorted(pd.Timestamp(d) for d in inst_conf)
        print(f"法人確認啟用: {len(INST_CONFDATES)} 交易日, DAYS={INST_DAYS}")

    # 全期交易日曆（2026-10-27 修：原本只看 0050；但 0050 快取可能只涵蓋近期
    # （實測只從 2026-02-23 起、共 167 天）⇒ 2022-2025 的選股日 sel_date 全為 None、
    # 整段回測 0 筆且不報錯。改成「所有標的日期的聯集」，0050 只當備援。）
    _mkt0full = ssg.load_stock("0050").dropna(subset=["close"])
    _all_days = sorted({d for df in data.values() for d in df.index})
    FULLCAL = _all_days if len(_all_days) >= len(_mkt0full) else sorted(set(_mkt0full.index))
    _mkt0 = _mkt0full[(_mkt0full.index >= pd.Timestamp(START)) & (_mkt0full.index <= pd.Timestamp(END))]
    MASTER = sorted(set(_mkt0.index))
    ALL_DATES = sorted(set(
        d for df in data.values() for d in df.index
        if pd.Timestamp(START) <= d <= pd.Timestamp(END)
    ))
    MONTH_STARTS = {}
    for d in ALL_DATES:
        ym = (d.year, d.month)
        if ym not in MONTH_STARTS:
            MONTH_STARTS[ym] = d
    MONTH_START_SET = set(MONTH_STARTS.values())

    # ── 產業對照（產業分散上限用）與月營收（營收成長因子用）──────────
    INDUSTRY, REV_ROWS = {}, {}
    if MAX_PER_SECTOR > 0:
        try:
            INDUSTRY, _ = load_cache_or_raw("cache/stock_industry.pkl")
            INDUSTRY = INDUSTRY or {}
            print(f"產業對照：{len(INDUSTRY)} 檔（每產業上限 {MAX_PER_SECTOR}）")
        except Exception as e:
            print(f"⚠️ 讀不到產業對照（{e}）⇒ MAX_PER_SECTOR 忽略")
            INDUSTRY = {}
    if FACTOR_REVENUE:
        try:
            from core.pit_data import load_revenue_rows
            for sid in data:
                rows = load_revenue_rows(sid, fetch=False)
                if rows:
                    REV_ROWS[sid] = rows
            print(f"月營收快取：{len(REV_ROWS)} 檔（營收成長因子啟用）")
        except Exception as e:
            print(f"⚠️ 月營收快取讀取失敗（{e}）⇒ 關閉營收因子")

    # ── 大盤指數序列（大盤年線濾網用）──────────────────────────
    # 優先用 TWSE 加權指數快取（scripts/build_market_index.py 建立）；沒有就退回 0050 收盤當代理。
    IDX_CLOSE, MF_SOURCE = None, None
    try:
        from core.cache_io import load_cache_or_raw as _lc
        _idx, _ = _lc(os.path.join("cache", "market_index", "taiex.pkl"))
        if _idx is not None and len(_idx) and "close" in _idx.columns:
            IDX_CLOSE, MF_SOURCE = _idx["close"].astype(float), "TAIEX"
    except Exception:
        pass
    if IDX_CLOSE is None:
        IDX_CLOSE = _mkt0full["close"].astype(float)
        MF_SOURCE = "0050（代理）"
    if MARKET_FILTER:
        print(f"大盤年線濾網: 啟用（來源 {MF_SOURCE}、MA{MF_WINDOW}、資料 {IDX_CLOSE.index.min().date()} ~ "
              f"{IDX_CLOSE.index.max().date()}）")
    else:
        print(f"大盤年線濾網: 關閉（MARKET_FILTER=0；實盤 .env 的 MARKET_TREND_FILTER="
              f"{os.getenv('MARKET_TREND_FILTER', '未設')} ⇒ 回測與實盤在此口徑不同）")

    # ── 換股頻率：每 REBAL_MONTHS 個月才選股一次（REBAL_MONTHS=1 ⇒ 與舊行為完全相同）──
    #   選股點 = 期間內「第 1、N+1、2N+1…」個月的月初交易日（不是日曆對齊到 1 月；
    #   所以 START=2022-03-01、N=12 ⇒ 選股月＝2022-03、2023-03…）。
    _ms_sorted = sorted(MONTH_STARTS.values())
    SELECTION_MONTH_START_SET = set(_ms_sorted[::REBAL_MONTHS])
    if REBAL_MONTHS > 1:
        print(f"換股頻率: 每 {REBAL_MONTHS} 個月選股一次 → "
              f"{len(SELECTION_MONTH_START_SET)} 個選股點（共 {len(_ms_sorted)} 個月）")


def pool_for_date(d):
    if POOL_FIXED:                      # 固定名單模式（評估用；沒有事後加碼/換股的空間）
        return [s for s in POOL_FIXED if s in data]
    cand = [q for q in sorted(pools) if pd.Timestamp(q + "-01").to_period("M").end_time <= d]
    return pools[cand[-1]] if cand else []


# ── 技術工具（只用 ≤ 指定日期的資料）────────────────────────
def snap(df, d):
    return ssg._snap_date(df, d)


def trailing_ret(df, d, days):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    sp = float(df.iloc[s]["close"]); ep = float(df.iloc[idx]["close"])
    return (ep - sp) / sp if sp > 0 else None


def vol(df, d, days=63):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    px = df.iloc[s:idx + 1]["close"].values
    return float(np.std(px / np.mean(px))) if len(px) >= 5 else None


def ma_pos(df, d, days=20):
    if d not in df.index:
        return None
    idx = df.index.get_loc(d)
    s = max(0, idx - days)
    ma = float(df.iloc[s:idx + 1]["close"].mean()); cp = float(df.iloc[idx]["close"])
    return (cp - ma) / ma if ma > 0 else None


def inst_ok(sid, sel_date):
    """法人確認濾網：近 INST_DAYS 法人累計淨買超 > 0。None（未知）→ pass-through。
    每個選股日只算一次全市場向量並快取；各股查表。"""
    if not INST_CONFIRM:
        return True
    import bisect
    key = pd.Timestamp(sel_date)
    if key not in _INST_NET_CACHE:
        idx = bisect.bisect_right(INST_CONFDATES, key)
        recent = INST_CONFDATES[max(0, idx - INST_DAYS):idx]
        acc = {}
        for ts in recent:
            row = inst_conf[ts.strftime("%Y-%m-%d")]
            for sid2, (b, s) in row.items():
                acc[sid2] = acc.get(sid2, 0) + (b - s)
        _INST_NET_CACHE[key] = pd.Series(acc) if acc else pd.Series(dtype=float)
    ser = _INST_NET_CACHE[key]
    net = ser.get(sid)
    return net is None or net > 0


_INST_NET_CACHE = {}


# ── 人工降溫（過熱過濾）helper ────────────────────────────
_OH_PER_CACHE = {}
_OH_DL = None


def _oh_dl():
    global _OH_DL
    if _OH_DL is None:
        from FinMind.data import DataLoader
        _OH_DL = DataLoader()
    return _OH_DL


# PER 磁碟快取（FinMind 有配額，重跑不要重抓）：
# `cache/stock_per/per_{代號}.pkl`（`{date_str: PER}`，經 core.cache_io 版本化）。
#
# ⚠️ 為何一定要有磁碟快取（2026-09-18 查獲）：原本只有**記憶體**快取、每次執行都重打 FinMind
#    ⇒ 抓到／抓不到 PER 會讓「過熱閘門」行為不同，**同一組參數兩次跑出 +79.2% 與 +109.6%**
#    （重跑不可重現 = 回測結論不可信）。改為磁碟快取後：第一次跑會抓並落地，之後完全可重現。
_PER_DIR = "cache/stock_per"
_OH_PER_MISS = {"n": 0}          # 抓不到 PER 的查詢次數（跑完印出來，供判讀可信度）


def per_at(series, sel_date):
    """{date_str: PER} → 最近一筆 ≤ sel_date 的 PER（無 → None）。純函式，可單獨測試。"""
    if not series:
        return None
    cut = pd.Timestamp(sel_date).normalize()
    best_d, best_v = None, None
    for d, v in series.items():
        try:                                   # 容忍 ISO / 'YYYY/MM/DD' / Timestamp 三種鍵
            ds = pd.Timestamp(d)
            if ds.tz is not None:
                ds = ds.tz_localize(None)
        except Exception:
            continue
        if ds <= cut and (best_d is None or ds > best_d):
            try:
                best_v = float(v)
            except (TypeError, ValueError):
                continue
            best_d = ds
    return best_v


_PER_STALE_DAYS = 10          # 快取最後一筆 PER 距選股日超過此天數 → 視為過期、重抓
_OH_PER_STALE = {"n": 0}      # 用到「過期 PER」的查詢次數（跑完印出）


def _oh_per_disk(sid):
    from core.cache_io import load_cache
    d, _ = load_cache(os.path.join(_PER_DIR, f"per_{sid}.pkl"))
    return d if isinstance(d, dict) and d else None


def series_max_date(series):
    """{date: PER} → 最大日期（Timestamp）；無 → None。"""
    best = None
    for d in (series or {}):
        try:
            ds = pd.Timestamp(d)
            if ds.tz is not None:
                ds = ds.tz_localize(None)
        except Exception:
            continue
        if best is None or ds > best:
            best = ds
    return best


def _oh_per_fetch(sid):
    """FinMind TaiwanStockPER（2015 起全段，抓一次即可長期重用）→ {date_str: PER}。"""
    try:
        dl = _oh_dl()
        d = dl.taiwan_stock_per_pbr(stock_id=sid, start_date="2015-01-01",
                                    end_date=pd.Timestamp.today().strftime("%Y-%m-%d"))
        if d is None or not len(d):
            return None
        d = d.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        return dict(zip(d["date"], d["PER"]))
    except Exception:
        return None


def _oh_get_per(sid, sel_date):
    """PER（≤ sel_date）→ 先讀磁碟快取，缺才打 FinMind 並落地（之後可重現）。"""
    key = (sid, sel_date.strftime("%Y-%m"))
    if key in _OH_PER_CACHE:
        return _OH_PER_CACHE[key]
    per = None
    if OH_USE_PER:
        series = _oh_per_disk(sid)
        # ⚠️ 快取可能「太舊」：實測既有 259 檔全部只到 2025-12-31 ⇒ 拿它過濾 2026 年的選股
        #    等於閘門失效（用 9 個月前的 PER 判斷今天貴不貴）。過期就重抓並更新快取。
        fresh_enough = (series is not None
                        and (series_max_date(series) or pd.Timestamp("1970-01-01"))
                        >= pd.Timestamp(sel_date) - pd.Timedelta(days=_PER_STALE_DAYS))
        if not fresh_enough:
            fetched = _oh_per_fetch(sid)
            if fetched:
                merged = {**(series or {}), **fetched}
                from core.cache_io import dump_cache
                try:
                    os.makedirs(_PER_DIR, exist_ok=True)
                    dump_cache(os.path.join(_PER_DIR, f"per_{sid}.pkl"), merged,
                               meta={"dataset": "TaiwanStockPER", "symbol": sid})
                except Exception:
                    pass
                series = merged
            elif series is None:
                _OH_PER_MISS["n"] += 1
            else:
                _OH_PER_STALE["n"] += 1        # 抓不到新資料 → 退回舊值（可重現但已過期）
        per = per_at(series, sel_date)
        if per is None and series is not None:
            _OH_PER_MISS["n"] += 1
    _OH_PER_CACHE[key] = per
    return per


def overheat_flags(sid, sel_date):
    """過熱旗標（永遠算，供 HOT_EXIT 與排除用；只算 ≤ sel_date，無前瞻）。"""
    df = data.get(sid)
    if df is None:
        return None
    sd = snap(df, sel_date)
    if sd is None or sd not in df.index:
        return None
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    if cp <= 0:
        return None
    win = df.iloc[max(0, idx - 251):idx + 1]
    hi = float(win["high"].max())
    pct_from_high = (hi - cp) / hi * 100 if hi > 0 else 0.0
    near_high = (hi > 0 and cp >= hi * (1 - OH_MAX_FROM_HIGH / 100.0))
    ys = df[df.index <= pd.Timestamp(str(sd.year) + "-01-01")]
    ytd = (cp / float(ys.iloc[-1]["close"]) - 1) if len(ys) and float(ys.iloc[-1]["close"]) > 0 else 0.0
    huge_ytd = ytd > OH_MAX_YTD / 100.0
    per = _oh_get_per(sid, sd) if (near_high or huge_ytd) else None
    high_pe = per is not None and per > OH_MAX_PER
    count = int(near_high) + int(huge_ytd) + int(high_pe)
    return {"sid": sid, "near_high": near_high, "huge_ytd": huge_ytd, "high_pe": high_pe,
            "count": count, "overheated": count >= OH_MIN_COUNT}


def overheated(sid, sel_date):
    if not OVERHEAT:
        return False
    f = overheat_flags(sid, sel_date)
    return bool(f and f["overheated"])


def _rsi14(df, idx):
    """簡單 RSI(14)。回傳 0-100 或 None（資料不足）。"""
    if idx < 15:
        return None
    seg = df.iloc[idx - 14:idx + 1]
    delta = seg["close"].diff()
    up = float(delta[delta > 0].sum())
    dn = float(-delta[delta < 0].sum())
    if up + dn <= 0:
        return 50.0
    rs = up / dn if dn > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def entry_overheat(sid, d):
    """買入當下是否過熱（只算 ≤ d，無前瞻）。供 sig==1 時拒買用。
    參數化：RSI 超買（OH_RSI_TH）與/或 距 N 日高太近（OH_DIST_WIN/OH_DIST_TH）。
    """
    if not ENTRY_OVERHEAT:
        return False
    df = data.get(sid)
    if df is None:
        return False
    sd = snap(df, d)
    if sd is None or sd not in df.index:
        return False
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    if cp <= 0:
        return False
    rsi = _rsi14(df, idx)
    rsi_over = rsi is not None and rsi > OH_RSI_TH
    win = df.iloc[max(0, idx - OH_DIST_WIN):idx + 1]
    hi = float(win["high"].max())
    near_high = hi > 0 and ((hi - cp) / hi * 100.0) <= OH_DIST_TH
    if OH_ENTRY_MODE == "both":
        return rsi_over and near_high
    return rsi_over or near_high


# ── 三組選股規則 ─────────────────────────────────────────
_FILL_STATS = {"months": 0, "month_short": 0, "names_added": 0}


def _fallback_rank(pool, sel_date):
    """補滿用的備援排序：**同一池**，以 63 日動能排序（不看過熱/法人/MA20），排除資料不足者。

    為什麼需要它（2026-10-29 實測）：`ssg.score_stock()` 在「跌破 MA20」或流動性不足時**回傳 None**
    ⇒ 有些月份整個池子一檔都打不出分數（例 2023-11 全部 None、最後只選出 2 檔），
    這時只放寬「過熱／法人」濾網仍然補不滿 ⇒ 必須有第二層備援排序。
    """
    out = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        r = trailing_ret(df, sd, MOM_DAYS)
        if r is None:
            continue
        out.append((sid, r))
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out]


def _fill(ranked, pool=None, sel_date=None, top_n=None):
    """把「嚴格通過濾網」的清單補到 N 檔（`FILL_MODE=topup`）。

    `ranked`：`[(sid, score, strict_ok)]`，已依分數排好序。
    - `proportional`：只回傳 strict_ok 的前 N 檔（＝現況：可能少於 N，資金平均分給這幾檔）。
    - `topup`：strict 不足 N 時，先依分數順序補「被過熱／法人擋掉」的，
      仍不足再依 `_fallback_rank()`（63 日動能）補滿。
    回傳 `(list_of_sids, n_topped_up)`。
    """
    n = TOP_N if top_n is None else int(top_n)
    strict = [sid for sid, _s, ok in ranked if ok][:n]
    _FILL_STATS["months"] += 1
    if len(strict) < n:
        _FILL_STATS["month_short"] += 1
    if FILL_MODE != "topup" or len(strict) >= n:
        return strict, 0
    out = list(strict)
    for sid, _score, ok in ranked:
        if len(out) >= n:
            break
        if not ok and sid not in out:
            out.append(sid)
    if len(out) < n and pool is not None and sel_date is not None:
        for sid in _fallback_rank(pool, sel_date):
            if len(out) >= n:
                break
            if sid not in out:
                out.append(sid)
    _FILL_STATS["names_added"] += len(out) - len(strict)
    return out, len(out) - len(strict)


def pick_high_profit(pool, sel_date):
    cands = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        r = trailing_ret(df, sd, MOM_DAYS)
        mp = ma_pos(df, sd, 20)
        if r is None or mp is None or mp < 0:
            continue
        ok = inst_ok(sid, sel_date) and not overheated(sid, sel_date)
        cands.append((sid, r, ok))
    cands.sort(key=lambda x: -x[1])
    return _fill(cands, pool, sel_date)[0]


def _ai_picks_for(sel_date):
    """取 AI 名單：封包的 `as_of` 是「當月第 1 個交易日」，而引擎的 `sel_date` 是它前一個交易日
    ⇒ 用「≥ sel_date 的最近一個 key（10 天內）」對應。"""
    import bisect

    key = str(sel_date)[:10]
    if key in _AI_PICKS:
        return _AI_PICKS[key]
    i = bisect.bisect_left(_AI_KEYS, key)
    if i < len(_AI_KEYS):
        cand = _AI_KEYS[i]
        if (pd.Timestamp(cand) - pd.Timestamp(key)).days <= 10:
            return _AI_PICKS[cand]
    return None


def _zscore_rows(pool, sel_date):
    """收集 z 分數模型需要的欄位（只用 ≤ sel_date 的資料）。"""
    rows = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        per = _oh_get_per(sid, sd)
        idx = df.index.get_loc(sd)
        win = df.iloc[max(0, idx - 251):idx + 1]
        hi = float(win["high"].max())
        cp = float(df.loc[sd, "close"])
        rev = None
        if FACTOR_REVENUE and REV_ROWS.get(sid):
            try:
                from core.pit_data import revenue_pack
                _rp = revenue_pack(REV_ROWS[sid], sd)
                if _rp.get("available") and _rp["items"]:
                    rev = _rp["items"][-1].get("yoy")
            except Exception:
                rev = None
        rows.append({"sid": sid, "per": per, "rev": rev,
                     "r63": trailing_ret(df, sd, 63), "r20": trailing_ret(df, sd, 20),
                     "dist": (cp / hi - 1.0) if hi > 0 else None})
    return rows


def _zscore_picks(pool, sel_date):
    """`SCORING_MODEL=zscore` 的排序（共用 `core.scoring`；回傳 `[(sid, score, True)]`）。

    可選：`FACTOR_REVENUE=1` 加入月營收 YoY 因子、`MAX_PER_SECTOR>0` 套用產業分散上限。
    """
    from core.scoring import apply_sector_cap, score_rows

    ranked = score_rows(_zscore_rows(pool, sel_date), use_revenue=FACTOR_REVENUE)
    if MAX_PER_SECTOR > 0 and INDUSTRY:
        capped = apply_sector_cap(ranked, INDUSTRY, MAX_PER_SECTOR)     # 依原順序、超過上限者剔除
        pos = {sid: i for i, (sid, _s) in enumerate(ranked)}
        ranked = [(sid, pos[sid]) for sid in capped]                     # 分數位置保留（只影響取前 N）
    return [(sid, sc, True) for sid, sc in ranked]


def pick_normal(pool, sel_date):
    _ai = _ai_picks_for(sel_date)
    if _ai:
        ok = [s for s in _ai if s in data and snap(data[s], sel_date) is not None]
        if ok:
            return ok[:TOP_N]
    if SCORING_MODEL == "zscore":
        return _fill(_zscore_picks(pool, sel_date), pool, sel_date)[0]
    scored = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        s = ssg.score_stock(sid, df, sd, dict(ssg.DEFAULT_PARAMS))
        if s is None:
            continue
        ok = inst_ok(sid, sel_date) and not overheated(sid, sel_date)
        scored.append((s["symbol"], float(s.get("total") or 0), ok))
    scored.sort(key=lambda x: -x[1])
    return _fill(scored, pool, sel_date)[0]


def pick_stable(pool, sel_date):
    cands = []
    for sid in pool:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        v = vol(df, sd, 63)
        mp200 = ma_pos(df, sd, 200)
        if v is None or mp200 is None or mp200 < 0:
            continue
        ok = inst_ok(sid, sel_date)
        cands.append((sid, v, ok))
    cands.sort(key=lambda x: x[1])
    return _fill(cands, pool, sel_date)[0]


def pick_megacap_momentum(pool, sel_date):
    """權值股動能：從「當時市值前 MEGA_N 大」(權值股)挑動能最強者。"""
    sub = pool[:MEGA_N]
    cands = []
    for sid in sub:
        df = data.get(sid)
        if df is None:
            continue
        sd = snap(df, sel_date)
        if sd is None or sd not in df.index:
            continue
        cp = float(df.loc[sd, "close"])
        if cp < MIN_PRICE:
            continue
        r = trailing_ret(df, sd, MOM_DAYS)
        mp = ma_pos(df, sd, 20)
        if r is None or mp is None or mp < 0:
            continue
        ok = inst_ok(sid, sel_date) and not overheated(sid, sel_date)
        cands.append((sid, r, ok))
    cands.sort(key=lambda x: -x[1])
    return _fill(cands, pool, sel_date)[0]


PICKERS = {"high_profit": pick_high_profit, "normal": pick_normal, "stable": pick_stable,
           "megacap": pick_megacap_momentum}


# ── 訊號快取（全期一次算，rolling 皆回看歷史 → 無未來函數）──
_SIG = {}
_ROLL = {}
_STRATS = set(s for s in STRAT_FUNCS)


def _roll(sid):
    if sid not in _ROLL:
        df = data[sid]
        r = df.reindex(ALL_DATES)
        r["close"] = r["close"].ffill()
        _ROLL[sid] = r
    return _ROLL[sid]


def sig_at(sid, strat, d):
    if (sid, strat) not in _SIG:
        df = data[sid]
        _SIG[(sid, strat)] = STRAT_FUNCS[strat](df)["signal"].reindex(ALL_DATES).ffill().fillna(0)
    return int(_SIG[(sid, strat)].get(d, 0))


def close_at(sid, d):
    r = _roll(sid)
    return float(r.loc[d, "close"]) if d in r.index else 0.0


def strat_for(group, idx):
    return GROUPS[group]["strats"][idx % len(GROUPS[group]["strats"])]


def pick_strategy_by_form(sid, sel_date):
    """依個股當下型態自適應選策略（四種全開放，只用 ≤ 選股日資料）。
    型態=趨勢/盤整，選順勢(ma_cross/breakout)或回歸(bollinger/vwap)。
    """
    df = data.get(sid)
    if df is None:
        return "ma_cross"
    sd = snap(df, sel_date)
    if sd is None or sd not in df.index:
        return "ma_cross"
    idx = df.index.get_loc(sd)
    cp = float(df.loc[sd, "close"])
    ma20 = float(df.iloc[max(0, idx - 19):idx + 1]["close"].mean())
    ma60 = float(df.iloc[max(0, idx - 59):idx + 1]["close"].mean())
    mom20 = trailing_ret(df, sd, 20) or 0.0
    trend_up = (cp > ma20) and (ma20 > ma60) and (mom20 > 0)
    if trend_up:
        # 順勢：強勢(20d>5%)用突破，否則均線交叉
        return "breakout" if mom20 > 0.05 else "ma_cross"
    # 盤整/下跌 → 回歸：回檔超跌用布林(買低)，否則 VWAP
    return "bollinger" if cp < ma20 else "vwap"


def buy_cost(cash, px):
    return cash - cash * COMMISSION  # 實際可用於買股（預留手續費）


def sell_net(proceeds, sid):
    return proceeds * (1 - COMMISSION - ssg.tax_rate(sid))


def buy_allowed(dts):
    """大盤年線濾網的買進守門（與實盤 `MARKET_TREND_FILTER` 同義）：回 False = 這筆不買。

    只有 MARKET_FILTER=1 時才有作用；資料不足 MA 視窗時不擋（與實盤「資料不足→跳過過濾」一致）。
    只在「本來就要買」的呼叫點被呼叫，所以計數＝被擋下的買進次數。
    """
    if not MARKET_FILTER:
        return True
    if above_ma200(IDX_CLOSE, dts, MF_WINDOW) is False:
        _MF_BLOCKED[0] += 1
        return False
    return True


def run_group(gkey, leverage=None):
    lev = LEVERAGE if leverage is None else max(0.0, float(leverage))   # 部位放大倍數（1=不放大）
    _MF_BLOCKED[0] = 0                                                  # 每組重新計數
    _FILL_STATS.update({"months": 0, "month_short": 0, "names_added": 0})
    cash = 0.0 if DCA_MONTHLY > 0 else INITIAL   # DCA：空手起、每月投入；一筆：INITIAL
    deposited = 0.0                               # 已投入總額（DCA 用）
    positions = {}   # sid -> {'strat': s, 'shares': float}
    bucket = {}      # sid -> 未投資的該股資金（可再進場）
    _hot_exit = HOT_EXIT and gkey in HOT_EXIT_GROUPS   # 僅對指定組(正常/權值股動能/高穩定)套用緊離場
    curve = {}
    selection_log = []
    peak = 0.0
    extended_once = False
    deployed_hist = {}   # dts -> 實際投入在「持股」的資金（shares × 價）
    alloc_hist = {}      # dts -> 分配到「股票桶」的資金（bucket + 持股）＝已承諾但尚未全買
    stop_count = [0]     # 硬停損觸發次數（STOP_LOSS_PCT>0 時才有意義）
    park_prev = [0.0]    # 前一日停泊金額（閒置資金押 IDLE_CASH_ASSET 用）
    _PARK_PREV_DATE = [None]   # 停泊報酬結算所用的前一日（交易日）
    park_hist = {}       # dts -> 當日停泊金額（供報告利用率）

    def debt_total():
        return sum(p.get("debt", 0.0) for p in positions.values())

    def equity(dts):
        e = cash + sum(bucket.values()) - debt_total()   # 扣掉融資部位（LEVERAGE>1 時才有）
        for sid, p in positions.items():
            if p["shares"] > 0:
                e += p["shares"] * close_at(sid, dts)
        return e

    for d in ALL_DATES:
        dts = pd.Timestamp(d)

        # 閒置資金停泊結算（用「昨日停泊金額 × 今日報酬」記進現金；報酬來自停泊標的的收盤序列）
        if IDLE_CASH_ASSET and park_prev[0] > 0:
            _d0 = _PARK_PREV_DATE[0] or dts
            _pp, _pn = close_at(IDLE_CASH_ASSET, _d0), close_at(IDLE_CASH_ASSET, dts)
            if _pp and _pn and _pp > 0:
                cash += park_prev[0] * (_pn / _pp - 1.0 - PARK_COST / 252.0)
            _PARK_PREV_DATE[0] = dts

        # 日初權益（供股災防護回撤評估）
        eq0 = equity(dts)
        peak = max(peak, eq0)

        # 融資利息（只有 LEVERAGE>1 才會產生負債；年利率 MARGIN_RATE，日計息）
        _dt = debt_total()
        if MARGIN_RATE > 0 and _dt > 0:
            cash -= _dt * MARGIN_RATE / 252.0

        # ── 每月月初：DCA 定額投入（與換股頻率無關，每月都投）──
        if dts in MONTH_START_SET and DCA_MONTHLY > 0:
            cash += DCA_MONTHLY
            deposited += DCA_MONTHLY

        # ── 換股事件（每 REBAL_MONTHS 個月一次；REBAL_MONTHS=1 ＝每個月初，即舊行為）──
        if dts in SELECTION_MONTH_START_SET:
            # 股災防護：選股日總回撤 > MIN_DRAW_BACK% 時「最多延長一輪」續抱未換。
            # 邏輯同原版 backtest_selector：首次觸發才延長(extended_once)，下輪恢復正常換倉。
            skip = False
            if MIN_DRAW_BACK > 0 and peak > 0:
                dd = eq0 / peak - 1.0
                if dd < -MIN_DRAW_BACK / 100.0:
                    if MDB_UNLIMITED:
                        skip = True
                    elif not extended_once:
                        skip = True
                        extended_once = True
                    else:
                        extended_once = False
                else:
                    extended_once = False
            if skip:
                selection_log.append({"date": dts.strftime("%Y-%m-%d"), "S": None, "skipped": True})
            else:
                prior = [x for x in FULLCAL if x < dts]
                sel_date = prior[-1] if prior else None
                S = PICKERS[gkey](pool_for_date(sel_date), sel_date) if sel_date is not None else []
                selection_log.append({"date": dts.strftime("%Y-%m-%d"), "S": list(S), "skipped": False})

                # Drop（A=full）：剔除未再選入的持股 → 賣出並把 bucket 併回現金池。
                # C=addonly：不強制賣出「仍在持(shares>0)」的股票；只清理「已出場(flat)且不在新選股」的。
                if SWAP_MODE == "full":
                    for sid in list(positions.keys()):
                        if sid not in S:
                            sh = positions[sid]["shares"]
                            px = close_at(sid, dts)
                            if sh > 0 and px > 0:
                                # 換出時同樣要先還融資（否則借來的錢會經 bucket 流回現金，槓桿失控）
                                bucket[sid] = (bucket.get(sid, 0) + sell_net(sh * px, sid)
                                               - positions[sid].get("debt", 0.0))
                            cash += bucket.pop(sid, 0.0)
                            del positions[sid]
                else:  # addonly (C)
                    for sid in list(positions.keys()):
                        if positions[sid]["shares"] == 0 and sid not in S:
                            cash += bucket.pop(sid, 0.0)
                            del positions[sid]

                # Add：新選入且未持有 → 用現金池等權分配本金。
                # C 只補到 TOP_N（active 未滿才加），不強制賣出/換出。
                new = [sid for sid in S if sid not in positions]
                if SWAP_MODE == "addonly":
                    active = sum(1 for s in positions if positions[s]["shares"] > 0)
                    new = new[:max(0, TOP_N - active)]
                if new and cash > 0:
                    alloc = cash / len(new)
                    for i, sid in enumerate(new):
                        px = close_at(sid, dts)
                        # STRAT_MODE=form（＝實盤 strategy=auto）：
                        #   EXEC=immediate(A) → 選股日就買，當場鎖定；EXEC=signal(B) → **進場當天才鎖**
                        #   （與實盤「買入那一刻 route_strategy()」一致；見 signal_strategy_for）。
                        if STRAT_MODE == "form":
                            # EXEC=immediate(A) 或 LOCK_AT=selection ⇒ 選股日就選定策略；
                            # 否則（B 等訊號＋與實盤一致）先不鎖，等進場成交當天鎖定。
                            _lock_now = (EXEC != "signal") or (LOCK_AT == "selection")
                            _st = pick_strategy_by_form(sid, sel_date) if _lock_now else None
                        else:
                            _st = strat_for(gkey, i)
                        _oh = overheat_flags(sid, sel_date)
                        _hot = _hot_exit and bool(_oh and _oh["count"] >= HOT_THRESHOLD)
                        positions[sid] = {"strat": _st, "shares": 0.0, "hot": _hot,
                                          "entry": 0.0, "peak": 0.0, "debt": 0.0}
                        bucket[sid] = alloc
                        cash -= alloc
                        # EXEC=immediate(A)：選股日立即買滿；EXEC=signal(B, 自選股=等訊號)：留空倉等進場訊號(由下方逐日訊號買進)
                        if ((EXEC != "signal") and (px > 0) and (bucket[sid] > 5)
                                and buy_allowed(dts)):
                            budget = bucket[sid]
                            notional = budget * lev      # 利用率等效放大（LEVERAGE／SCALE_TO_UTIL）
                            bought = buy_cost(notional, px)
                            positions[sid]["shares"] = bought / px
                            positions[sid]["debt"] = max(0.0, notional - budget)   # 融資金額
                            positions[sid]["entry"] = px
                            positions[sid]["peak"] = px
                            bucket[sid] = max(0.0, budget - notional)   # lev<1 時未用完的額度

            # 記錄實際持有（代號＋策略）
            selection_log[-1]["holdings"] = [
                {"sid": s, "strat": positions[s]["strat"] or "pending"} for s in positions
            ]

        # ── 逐日訊號進出 ──
        for sid in list(positions.keys()):
            px = close_at(sid, dts)
            if px <= 0:
                continue
            # 未鎖定（等訊號尚未進場）→ 每日重路由；已鎖定 → 固定策略（與實盤一致）
            _st_today = signal_strategy(positions[sid]["strat"], pick_strategy_by_form, sid, dts)
            sig = sig_at(sid, _st_today, dts)
            sh = positions[sid]["shares"]
            hot = positions[sid].get("hot", False)
            do_sell = (sh > 0 and sig == -1)
            # 硬停損（2026-09-16 評估；STOP_LOSS_PCT=0 → 完全不影響基準）
            if sh > 0 and stop_hit(px, positions[sid].get("entry", 0.0), STOP_LOSS_PCT):
                do_sell = True
                stop_count[0] += 1
            # 過熱入場的自適應離場：獲利目標 + 移動停損（避免卡高點；僅對啟用組）
            if _hot_exit and hot and sh > 0:
                positions[sid]["peak"] = max(positions[sid].get("peak", 0.0), px)
                if HOT_TP_PCT > 0 and px >= positions[sid]["entry"] * (1 + HOT_TP_PCT / 100.0):
                    do_sell = True
                if HOT_TRAIL_PCT > 0 and px <= positions[sid]["peak"] * (1 - HOT_TRAIL_PCT / 100.0):
                    do_sell = True
            if do_sell and sh > 0:
                proceeds = sell_net(sh * px, sid)
                _debt = positions[sid].get("debt", 0.0)
                # ⚠️ 融資要從「這筆部位的回款」扣掉（不是記回 bucket），否則下一輪買進會把
                #    借來的錢當自有資金再放大一次 ⇒ 槓桿隨回合數指數成長（2026-10-28 踩過）。
                bucket[sid] = bucket.get(sid, 0.0) + proceeds - _debt
                positions[sid]["debt"] = 0.0
                positions[sid]["shares"] = 0.0
                # 2026-09-22 對齊實盤：賣出（部位歸零）要**釋放 auto 鎖定**，
                #   下次進場重新路由（實盤 AUTO_FIXED_CACHE.pop；2006 實例：ma_cross 賣 → breakout 買回）。
                #   舊版留著舊 strat ⇒ 回測低估「出場後換策略重進」的效果。
                positions[sid]["strat"] = strategy_after_exit(positions[sid]["strat"], positions[sid]["shares"])
            elif sh == 0 and sig == 1 and bucket.get(sid, 0.0) > 5:
                if entry_overheat(sid, dts):
                    continue   # 過熱拒買（策略訊號在、但買入當下過熱(RSI超買/距高點近)）
                if not buy_allowed(dts):
                    continue   # 大盤在年線下 → 不買（訊號還在就之後再說）
                budget = bucket[sid]
                notional = budget * lev                      # 利用率等效放大
                bought = buy_cost(notional, px)
                positions[sid]["shares"] = bought / px
                positions[sid]["debt"] = max(0.0, notional - budget)   # 融資金額
                positions[sid]["entry"] = px
                positions[sid]["peak"] = px
                bucket[sid] = max(0.0, budget - notional)
                if positions[sid]["strat"] is None:
                    # **進場當下鎖定**（這一輪用來產生買訊的策略）——與實盤買入即鎖定一致
                    positions[sid]["strat"] = _st_today

        # ── 權益紀錄 ──
        curve[dts] = equity(dts)
        _inv = sum(p["shares"] * close_at(sid, dts) for sid, p in positions.items() if p["shares"] > 0)
        deployed_hist[dts] = _inv
        alloc_hist[dts] = _inv + sum(bucket.values())
        if IDLE_CASH_ASSET:
            _idle = equity(dts) - _inv                     # 現金＋已分配未買的額度
            park_hist[dts] = max(0.0, _idle)
            park_prev[0] = max(0.0, _idle)
            _PARK_PREV_DATE[0] = dts

    curve = pd.Series(curve).sort_index()
    _avg_inv = (pd.Series(deployed_hist).mean() if deployed_hist else 0.0)
    _avg_alloc = (pd.Series(alloc_hist).mean() if alloc_hist else 0.0)
    # 尖峰動用（2026-09-18 新增，使用者指正）：**實際需要準備多少資金**看的是最高峰、不是平均。
    # 「平均 58%」只說明平均；要回答「50 萬是不是真的需要」得看 peak_deployed。
    _peak_inv = max(deployed_hist.values()) if deployed_hist else 0.0
    _peak_d = max(deployed_hist, key=deployed_hist.get) if deployed_hist else None
    # ⚠️ 「相對初始本金」的動用金額會隨複利超過 100%（帳戶長大後本來就會），**不能**用來回答
    #    「需要準備多少資金」。正確指標是 **deployed ÷ 當下權益**（曝險比例），取其平均與尖峰。
    _ratios = [deployed_hist[d] / curve[d] for d in deployed_hist
               if d in curve.index and curve[d] > 0]
    _rs = sorted(_ratios)
    _util_avg = (sum(_ratios) / len(_ratios)) if _ratios else 0.0
    _util_peak = max(_ratios) if _ratios else 0.0
    # 中位數/p90：平均會被「剛換股後大量空倉」拉低，中位數與 p90 才看得出「平常要準備多少」
    def _pct(q):
        if not _rs:
            return 0.0
        i = min(len(_rs) - 1, max(0, int(round(q * (len(_rs) - 1)))))
        return _rs[i]
    _util_p50, _util_p90 = _pct(0.5), _pct(0.9)
    _util_peak_d = (max(deployed_hist, key=lambda d: deployed_hist[d] / curve[d])
                    if _ratios else None)
    return {"curve": curve, "final": curve.iloc[-1] if len(curve) else cash,
            "deployed_series": pd.Series(deployed_hist).sort_index(),
            "allocated_series": pd.Series(alloc_hist).sort_index(),
            "leverage": lev,
            "mf_blocked": _MF_BLOCKED[0],
            "park_avg": round(float(pd.Series(park_hist).mean())) if park_hist else 0,
            "util_total_avg": (round(float(sum(
                (deployed_hist[d] + park_hist.get(d, 0.0)) / curve[d]
                for d in deployed_hist if d in curve.index and curve[d] > 0)) / max(1, len(deployed_hist)), 4)
                if (IDLE_CASH_ASSET and deployed_hist) else None),
            "deposited": deposited, "selection_log": selection_log,
            "avg_deployed": round(float(_avg_inv)),
            "avg_allocated": round(float(_avg_alloc)),
            "peak_deployed": round(float(_peak_inv)),
            "peak_deployed_date": (str(_peak_d)[:10] if _peak_d is not None else None),
            "util_avg": round(float(_util_avg), 4),        # 平均曝險比例（÷當下權益）
            "util_p50": round(float(_util_p50), 4),        # 中位數曝險比例
            "util_p90": round(float(_util_p90), 4),        # p90 曝險比例
            "util_peak": round(float(_util_peak), 4),      # 尖峰曝險比例（÷當下權益）
            "util_peak_date": (str(_util_peak_d)[:10] if _util_peak_d is not None else None),
            "stop_count": stop_count[0]}


# ── 0050 基準 ───────────────────────────────────────────
def benchmark(initial=INITIAL):
    df = _mkt0
    idx = df.index[(df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(END))]
    if len(idx) == 0:
        return pd.Series(dtype=float)
    t0 = idx[0]; b0 = float(df.loc[t0, "close"])
    curve = df.loc[idx, "close"] * (initial / b0)
    curve = curve * (1 - ssg.COMMISSION_RATE)
    daily = 0.0032 / 252.0
    curve = curve * ((1 - daily) ** np.arange(len(curve)))
    curve = curve * (1 - ssg.COMMISSION_RATE - ssg.ETF_TAX)
    return curve


def benchmark_dca(monthly=DCA_MONTHLY):
    """每月定額折入 0050：每個月第一個交易日買入 monthly，持有到期末。回傳(終值, 已投入)。"""
    df = _mkt0
    idx = list(df.index[(df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(END))])
    if not idx:
        return 0.0, 0.0
    sep = {}
    for d in idx:
        ym = (d.year, d.month)
        if ym not in sep:
            sep[ym] = d
    last = float(df.loc[idx[-1], "close"])
    final = 0.0
    contrib = 0.0
    for d in sep.values():
        px = float(df.loc[d, "close"])
        if px <= 0:
            continue
        contrib += monthly
        final += monthly * (last / px)   # 當日買入的 0050 持股到期末價值（未計成本，近似）
    final = final * (1 - ssg.COMMISSION_RATE - ssg.ETF_TAX)   # 簡化單次成本
    return final, contrib


def perf(curve):
    curve = curve.dropna()
    if len(curve) < 3:
        return None
    rets = curve.pct_change().dropna()
    sd = rets.std(ddof=1)
    sharpe = float(rets.mean() / sd * math.sqrt(252)) if sd and sd > 0 else float("nan")
    run_max = curve.cummax()
    mdd = float(((curve - run_max) / run_max).min())
    return {"sharpe": sharpe, "mdd": mdd}


def yearly(curve):
    if curve is None or len(curve) == 0:
        return {}
    return {int(yr): float(grp.iloc[-1] / grp.iloc[0] - 1)
            for yr, grp in curve.groupby(curve.index.year)}


def main():
    load_data()
    results = {}
    ONLY = [x.strip() for x in os.getenv("GROUPS_ONLY", "").split(",") if x.strip()]
    gkeys = ONLY if ONLY else list(GROUPS.keys())
    for gkey in gkeys:
        meta = GROUPS[gkey]
        res = run_group(gkey)
        if SCALE_TO_UTIL > 0:
            # 多段式：用上一段量到的 util_avg 反推倍數，逐步逼近「平均曝險 = SCALE_TO_UTIL%」。
            # （util 對 L 不是嚴格線性：融資部位的損益也會改變權益 ⇒ 一次通常差幾個 %，迭代到 2% 內）
            _raw_util, _raw_final = res.get("util_avg"), res.get("final")
            _lev = leverage_for_target(_raw_util, SCALE_TO_UTIL)
            _tries = 0
            while _lev > 1.0 and _tries < 3:
                res = run_group(gkey, leverage=_lev)
                _tries += 1
                _u = res.get("util_avg") or 0.0
                if abs(_u - SCALE_TO_UTIL / 100.0) <= 0.02:
                    break
                _nudged = _lev * (SCALE_TO_UTIL / 100.0) / _u if _u > 0 else _lev
                if _nudged <= 1.0 or abs(_nudged - _lev) / _lev < 0.005:
                    break
                _lev = min(_nudged, 5.0)
            if _tries:
                print(f"  🔧 等效 {SCALE_TO_UTIL:g}% 利用率：LEVERAGE={_lev:.3f}（迭代 {_tries} 次）"
                      f"｜原 util {(_raw_util or 0):.1%}／終值 NT${(_raw_final or 0):,.0f}"
                      f" → 放大後 util {res.get('util_avg', 0):.1%}／NT${res.get('final', 0):,.0f}"
                      f"（融資年息 {MARGIN_RATE:.1%}）")
            else:
                print(f"  🔧 等效 {SCALE_TO_UTIL:g}% 利用率：原 util 已 >= 目標，不放大")
        curve = res["curve"]
        years = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
        base = res["deposited"] if DCA_MONTHLY > 0 else INITIAL   # DCA 用已投入總額；一筆用 INITIAL
        total = res["final"] / base - 1
        ann = (res["final"] / base) ** (1 / years) - 1 if total > -1 else -1
        p = perf(curve) or {}
        results[gkey] = {
            "label": meta["label"],
            "final_value": round(res["final"]),
            "contributed": round(base),
            "total_return": round(total, 4),
            "annualized": round(ann, 4),
            "sharpe": round(p.get("sharpe", float("nan")), 2),
            "max_drawdown": round(p.get("mdd", float("nan")), 4),
            "avg_deployed": res["avg_deployed"],      # 平均實際投入在持股的資金
            "peak_deployed": res.get("peak_deployed"),          # 尖峰實際投入金額
            "peak_deployed_date": res.get("peak_deployed_date"),
            "util_avg": res.get("util_avg"),                    # **平均曝險比例（÷當下權益）**
            "util_p50": res.get("util_p50"), "util_p90": res.get("util_p90"),
            "util_peak": res.get("util_peak"),                  # **尖峰曝險比例（÷當下權益）**
            "util_peak_date": res.get("util_peak_date"),
            "leverage": res.get("leverage", LEVERAGE),          # 部位放大倍數（1=未放大）
            "mf_blocked": res.get("mf_blocked", 0),             # 大盤年線濾網擋下的買進次數
            "park_avg": res.get("park_avg", 0),                 # 平均停泊金額（IDLE_CASH_ASSET）
            "util_total_avg": res.get("util_total_avg"),        # **總曝險**（股票＋停泊）÷ 權益
            "avg_allocated": res["avg_allocated"],    # 平均分配到股票桶的資金（含空等訊號）
            "stop_loss_pct": STOP_LOSS_PCT,           # 本次回測的硬停損設定（0=關）
            "stop_count": res.get("stop_count", 0),   # 硬停損觸發次數
            # DCA 模式下權益曲線含每月投入，年度報酬會失真 → 不輸出
            "yearly": ({} if DCA_MONTHLY > 0 else {k: round(v, 4) for k, v in yearly(curve).items()}),
            "selection_log": res["selection_log"],
        }
        _deploy_pct = res["avg_deployed"] / INITIAL * 100 if INITIAL > 0 else 0.0
        _alloc_pct = res["avg_allocated"] / INITIAL * 100 if INITIAL > 0 else 0.0
        _mode = "dca" if DCA_MONTHLY > 0 else "lump"
        # ⚠️ 2026-09-21 修：原本寫**固定檔名**（`results/daily_<group>_<mode>.csv`）⇒ 跑其他窗口會
        #   覆蓋 11 年那條曲線（實際發生過：分析腳本讀到的曲線
        #   其實是別的窗口的）。改為一律寫**窗口專屬檔名**，canonical(2015-01-01/2025-12-31)
        #   另外再寫一份舊檔名，讓既有工具與文件仍可讀
        #   （2026-09-18 修法）。
        # 檔名含口徑（EXEC／DCA／鎖定時點）——2026-09-22 補：只帶窗口的話，
        #   同窗口的 signal 與 immediate 會互相覆蓋（實際發生：混合分析差點混到 A 的曲線）。
        _suffix = f"{EXEC}" + (f"_dca{DCA_MONTHLY:g}" if DCA_MONTHLY > 0 else "") \
                  + ("" if LOCK_AT == "fill" else f"_{LOCK_AT}") \
                  + (f"_rebal{REBAL_MONTHS}" if REBAL_MONTHS > 1 else "") \
                  + (f"_top{TOP_N}" if TOP_N != 5 else "") \
                  + (f"_fixed{len(POOL_FIXED)}" if POOL_FIXED else "") \
                  + (f"_lev{LEVERAGE:g}" if LEVERAGE != 1 else "") \
                  + (f"_scale{SCALE_TO_UTIL:g}" if SCALE_TO_UTIL > 0 else "") \
                  + (f"_mf{MF_WINDOW}" if MARKET_FILTER else "") \
                  + (f"_park{IDLE_CASH_ASSET}" if IDLE_CASH_ASSET else "") \
                  + (f"_fill{FILL_MODE}" if FILL_MODE != "proportional" else "") \
                   + (f"_score{SCORING_MODEL}" if SCORING_MODEL != "legacy" else "") \
                   + ("_norev" if (SCORING_MODEL == "zscore" and not FACTOR_REVENUE) else "") \
                   + (f"_sec{MAX_PER_SECTOR}" if MAX_PER_SECTOR > 0 else "") \
                   + ("" if include_delisted() else "_surv") \
                   + (f"_pool{POOL_N}" if POOL_N != 50 else "")
        curve.to_csv(f"results/daily_{gkey}_{START}_{END}_{_suffix}.csv")
        # 每日曝險明細（equity / 持股市值 / 已分配額度）——「閒置資金押 0050」的合成需要它
        try:
            pd.DataFrame({"equity": curve,
                          "deployed": res.get("deployed_series"),
                          "allocated": res.get("allocated_series")}).to_csv(
                f"results/exposure_{gkey}_{START}_{END}_{_suffix}.csv")
        except Exception as _e:
            print(f"⚠️ 曝險明細匯出失敗（不影響回測）：{_e}")
        # 舊檔名（不含口徑）只為「已文件化的 canonical 基線」保留：2015-2025 + signal + fill + 單筆
        if (START, END) == ("2015-01-01", "2025-12-31") and _suffix == "signal":
            curve.to_csv(f"results/daily_{gkey}_{_mode}.csv")
        print(f"\n[{meta['label']}] 投入 NT${base:,.0f} → 終值 NT${res['final']:,.0f}  "
              f"總報酬 {total:+.2%} 年化 {ann:+.2%} MDD {p.get('mdd', float('nan')):.2%} "
              f"夏普 {p.get('sharpe', float('nan')):.2f}")
        _pk = res.get("peak_deployed") or 0
        print(f"  平均動用(持股中) NT${res['avg_deployed']:,.0f}（{_deploy_pct:.1f}% of {INITIAL:,.0f}）｜"
              f"平均分配到股票桶 NT${res['avg_allocated']:,.0f}（{_alloc_pct:.1f}%）")
        print(f"  尖峰動用 NT${_pk:,.0f}（{_pk / INITIAL * 100:.1f}% of 初始 {INITIAL:,.0f}"
              f"；{res.get('peak_deployed_date') or '?'}）")
        print(f"  🔑 曝險比例（÷當下權益）：平均 {res.get('util_avg', 0):.1%}"
              f"｜中位 {res.get('util_p50', 0):.1%}｜p90 {res.get('util_p90', 0):.1%}"
              f"｜尖峰 {res.get('util_peak', 0):.1%}（{res.get('util_peak_date') or '?'}）"
              f" ← 這才是回答「要準備多少資金」的數字（T+2 淨額交割下現金需求更低）")
        if STOP_LOSS_PCT > 0:
            print(f"  硬停損 −{STOP_LOSS_PCT:g}%：觸發 {res.get('stop_count', 0)} 次")
        if MARKET_FILTER:
            print(f"  大盤年線濾網（{MF_SOURCE}、MA{MF_WINDOW}）：擋下 {res.get('mf_blocked', 0)} 次買進")
        if FILL_MODE == "topup":
            print(f"  補滿模式（放寬過熱／法人＋63 日動能）：{_FILL_STATS['month_short']}/{_FILL_STATS['months']} 次選股"
                  f"本來不足 N 檔，共補進 {_FILL_STATS['names_added']} 檔")
        elif _FILL_STATS["month_short"]:
            print(f"  比例模式：{_FILL_STATS['month_short']}/{_FILL_STATS['months']} 次選股不足 N 檔"
                  f"（資金平均分配給選出的檔數）")
        if IDLE_CASH_ASSET:
            print(f"  閒置停泊（{IDLE_CASH_ASSET}）：平均停泊 NT${res.get('park_avg', 0):,.0f}"
                  f"｜總曝險（股票＋停泊）平均 {res.get('util_total_avg') or 0:.1%}")
        if DCA_MONTHLY == 0:
            print("  年度:", {k: f"{v:+.2%}" for k, v in yearly(curve).items()})

    years = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
    if DCA_MONTHLY > 0:
        b_final, b_contrib = benchmark_dca(DCA_MONTHLY)
        b_total = b_final / b_contrib - 1
        b_ann = (b_final / b_contrib) ** (1 / years) - 1 if b_total > -1 else -1
        print(f"\n[0050 DCA 基準] 投入 NT${b_contrib:,.0f} → 終值 NT${b_final:,.0f}  "
              f"總報酬 {b_total:+.2%} 年化 {b_ann:+.2%}")
        bench_meta = {"final_value": round(b_final), "contributed": round(b_contrib),
                      "total_return": round(b_total, 4), "annualized": round(b_ann, 4)}
    else:
        bench = benchmark()
        if len(bench) == 0:
            print("\n[0050 買進持有] 略過：0050 快取沒有涵蓋本次回測期間（基準無法計算）")
            bench_meta = None
        else:
            b_total = bench.iloc[-1] / INITIAL - 1
            b_ann = (bench.iloc[-1] / INITIAL) ** (1 / years) - 1
            bp = perf(bench) or {}
            print(f"\n[0050 買進持有] NT${INITIAL:,.0f} → NT${bench.iloc[-1]:,.0f}  "
                  f"總報酬 {b_total:+.2%} 年化 {b_ann:+.2%} MDD {bp.get('mdd', float('nan')):.2%} "
                  f"夏普 {bp.get('sharpe', float('nan')):.2f}")
            bench_meta = {"final_value": round(bench.iloc[-1]), "total_return": round(b_total, 4),
                          "annualized": round(b_ann, 4), "sharpe": round(bp.get("sharpe", float("nan")), 2),
                          "max_drawdown": round(bp.get("mdd", float("nan")), 4)}

    if OH_USE_PER:
        print(f"\n[PER 快取] 完全查不到 PER {_OH_PER_MISS['n']} 次、"
              f"退回過期 PER {_OH_PER_STALE['n']} 次（兩者皆＝過熱閘門在該查詢上失效；0/0＝完全可信）")
    out = {"start": START, "end": END, "initial": INITIAL, "dca_monthly": DCA_MONTHLY,
           "exec": EXEC, "strat_mode": STRAT_MODE, "swap_mode": SWAP_MODE,
           "overheat_use_per": OH_USE_PER, "lock_at": LOCK_AT,
           "per_miss": _OH_PER_MISS["n"] if OH_USE_PER else 0,
           "per_stale": _OH_PER_STALE["n"] if OH_USE_PER else 0,
           "pool_n": POOL_N, "top_n": TOP_N, "rebal_months": REBAL_MONTHS, "fill_mode": FILL_MODE,
           "scoring_model": SCORING_MODEL, "factor_revenue": FACTOR_REVENUE,
           "max_per_sector": MAX_PER_SECTOR,
           "pool_fixed": POOL_FIXED or None,
           "leverage": LEVERAGE, "scale_to_util": SCALE_TO_UTIL, "margin_rate": MARGIN_RATE,
           "market_filter": MARKET_FILTER, "mf_window": MF_WINDOW, "mf_source": MF_SOURCE,
           "idle_cash_asset": IDLE_CASH_ASSET or None, "park_cost": PARK_COST,
           "momentum_days": MOM_DAYS, "inst_confirm": INST_CONFIRM, "inst_days": INST_DAYS,
           "min_draw_back": MIN_DRAW_BACK, "strat_mode": STRAT_MODE, "swap_mode": SWAP_MODE,
           "overheat": OVERHEAT, "oh_max_from_high": OH_MAX_FROM_HIGH, "oh_max_ytd": OH_MAX_YTD,
           "oh_max_per": OH_MAX_PER, "oh_min_count": OH_MIN_COUNT, "oh_use_per": OH_USE_PER,
           "groups": results,
           "benchmark_0050": bench_meta}
    os.makedirs("results", exist_ok=True)
    with open("results/plan2_monthly_3group.json", "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    # 2026-09-21：另存**窗口／口徑專屬**檔名，避免「同一個檔名被不同窗口覆蓋」導致事後無法覆核
    #   （`plan2_monthly_3group.json` 保留為最新一次執行的通用檔）。
    _tag = f"{START}_{END}_{EXEC}" + (f"_dca{DCA_MONTHLY:g}" if DCA_MONTHLY > 0 else "") \
           + ("" if LOCK_AT == "fill" else f"_{LOCK_AT}") \
           + (f"_rebal{REBAL_MONTHS}" if REBAL_MONTHS > 1 else "") \
           + (f"_top{TOP_N}" if TOP_N != 5 else "") \
           + (f"_fixed{len(POOL_FIXED)}" if POOL_FIXED else "") \
           + (f"_lev{LEVERAGE:g}" if LEVERAGE != 1 else "") \
           + (f"_scale{SCALE_TO_UTIL:g}" if SCALE_TO_UTIL > 0 else "") \
           + (f"_mf{MF_WINDOW}" if MARKET_FILTER else "") \
           + (f"_park{IDLE_CASH_ASSET}" if IDLE_CASH_ASSET else "") \
           + (f"_fill{FILL_MODE}" if FILL_MODE != "proportional" else "") \
           + (f"_score{SCORING_MODEL}" if SCORING_MODEL != "legacy" else "") \
           + ("_norev" if (SCORING_MODEL == "zscore" and not FACTOR_REVENUE) else "") \
           + (f"_sec{MAX_PER_SECTOR}" if MAX_PER_SECTOR > 0 else "") \
           + ("" if include_delisted() else "_surv") \
           + (f"_pool{POOL_N}" if POOL_N != 50 else "")
    _out_path = f"results/plan2_monthly_3group_{_tag}.json"
    with open(_out_path, "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n已存 results/plan2_monthly_3group.json 與 {_out_path}")


if __name__ == "__main__":
    main()
