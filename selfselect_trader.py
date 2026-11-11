# TW SelfSelect Trader — 台股「自選股（每月換股）」自動交易主程式
# 由 tw-autotrader 拆出：只保留自選股腿（母專案其他策略腿已移除）
#【軟體使用與免責聲明】本軟體係依「現狀（AS-IS）」提供，不帶有任何形式的明示或暗示之保證（包括但不限於對適銷性、特定目的之適用性以及不侵權的暗示保證）。
# 開發團隊（或本公司）在任何情況下，均不對因使用或無法使用本軟體所引起的任何直接、間接、偶發、特殊、懲罰性或衍生性損失（包括但不限於利潤損失、業務中斷、資料遺失、設備損壞或電腦故障）承擔任何法律及賠償責任，亦不對任何第三方提出的索賠負責。
# 使用者須自行承擔使用本軟體之所有風險。
import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(override=True)
SYS_TELEGRAM_BOT_TOKEN = os.getenv('SYS_TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN', '')
SYS_TELEGRAM_CHAT_ID = os.getenv('SYS_TELEGRAM_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')
from core.config_loader import load_portfolio_config, STRATEGY_PARAM_KEYS, get_strategy_params
PORTFOLIO_CONFIG = load_portfolio_config()
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.breakout import breakout_strategy
from strategies.keep_wait import keep_wait_strategy
from strategies.auto_sensing import auto_sensing_strategy, route_strategy
from utils.telegram import send_trade_alert, send_telegram_message, escape_md
from core.risk_manager import RiskManager
from core.live_state import load_json, save_json, load_monthly_budget, save_monthly_budget, check_monthly_budget, update_monthly_spending, load_stock_allocation, save_stock_allocation, ensure_symbol_ledgers, check_stock_cap, update_stock_allocation, load_holdings, save_holdings, update_holdings, load_last_trade_times, save_last_trade_times, load_daily_trades, save_daily_trades, load_processed_capital, save_processed_capital
from core.live_notifications import send_line_notification, notify_all, send_daily_report, send_closing_summary, send_sleep_notification, send_startup_holdings
from core.live_utils import get_next_market_open as _next_market_open, resolve_fill, reconcile_order_qty, order_fill_price, load_unknown_orders, record_unknown_order, clear_unknown_order, unknown_order_blocks_buy, broker_holding_qty, sell_with_fill_check, notify_order_failure, sell_stock_allocation, report_due, mark_report_sent, REPORT_STATE_PATH, is_trading_day, close_order_window_open, should_emit_idle_notice, full_position_topup, intraday_trade_window
# 整股（board lot）規則的單一出處（2026-11-09，v1.1.36）：買單 sizing 完成後先對齊，
# 金額／額度檢查才看得到「券商進位後真正會花掉多少」。見 core/lots.py 的停泊超支事故說明。
from core.lots import board_lot_qty, fit_buy_qty, sell_lot_qty
import sys

# ── 網路呼叫預設 timeout（避免主迴圈卡死）──────────────────────────────
# 根因：E.Sun / FinMind 兩支 SDK 內部的 requests 呼叫「沒有 timeout」→ 一旦連線半開
# 會永久阻塞整個主迴圈（2026-09-10 曾卡死 8 小時、整段交易時段無輸出）。
# 這裡統一 monkey-patch requests，未指定 timeout 的一律補上 `request_timeout_for(url)`。
#
# 報價端點（intraday/quote、snapshot/quotes）另外用**較短的** NET_QUOTE_TIMEOUT_SEC：
# 13:25–13:30 下單窗口內是**逐檔串行**取價，一檔卡滿 30 秒就吃掉窗口 1/10
# （2026-11-02 09:00 開盤首圈實測：api.fugle.tw 一檔 30 秒無回應才被切掉）。
_QUOTE_URL_HINTS = ('/intraday/quote/', '/snapshot/quotes/')
def request_timeout_for(url):
  """依 URL 決定要補上的 timeout（秒）；回 None 表示不補（= 沿用 requests 原本的無限等待）。

  在呼叫當下讀 env（不是 import 時讀常數）⇒ `.env` 熱重載後立即生效。
  """
  try:
    if any((h in (url or '')) for h in _QUOTE_URL_HINTS):
      sec = float(os.getenv('NET_QUOTE_TIMEOUT_SEC', '8'))
    else:
      sec = float(os.getenv('NET_TIMEOUT_SEC', '30'))
  except (TypeError, ValueError):
    sec = 30.0
  return (sec if sec > 0 else None)
_orig_session_request = requests.sessions.Session.request
def _session_request_with_timeout(self, method, url, **kwargs):
  if kwargs.get('timeout') is None:
    _t = request_timeout_for(url)
    if _t is not None:
      kwargs['timeout'] = _t
  return _orig_session_request(self, method, url, **kwargs)
requests.sessions.Session.request = _session_request_with_timeout

# ── 主迴圈 watchdog（第二層保險）────────────────────────────────────────
# 主迴圈每圈更新心跳；若 STALL_EXIT_SEC 秒無進展 → 強制結束程序，靠 docker
# restart policy（unless-stopped）自動拉起。0=停用。
_STALL_EXIT_SEC = float(os.getenv('STALL_EXIT_SEC', '600'))
_HEARTBEAT = {'ts': time.time()}
def start_watchdog():
  if _STALL_EXIT_SEC <= 0:
    return
  import threading
  def _wd():
    while True:
      time.sleep(60)
      _idle = time.time() - _HEARTBEAT['ts']
      if _idle > _STALL_EXIT_SEC:
        print(f'🛑 watchdog: 主迴圈已 {_idle:.0f}s 無進展（>{_STALL_EXIT_SEC:.0f}s）→ 強制結束程序（docker 會重啟）', flush=True)
        try:
          send_telegram_message(f'🛑 *watchdog*：主迴圈卡住 {_idle:.0f}s，強制重啟')
        except Exception:
          pass
        os._exit(1)
  threading.Thread(target=_wd, daemon=True).start()
  print(f'🐕 watchdog 已啟動（> {_STALL_EXIT_SEC:.0f}s 無進展則重啟）')


def book_price(order_ret, decision_px, label=''):
  """記帳價＝provider 回報的**實際送單價**（`sent_price`）；沒有就沿用作業價。

  為什麼要有這個 helper（2026-11-03）：`place_order()` 內送單前會**自己再取一次現價**當限價，
  所以「上層先取到的報價」與「券商實際收到的價」可能不同（實測 6505 孤兒清倉：
  上層取到 99.9、實際送單 99.60 ⇒ 帳本多記約 NT$600，對帳每天報「CSV 價 ≠ 券商價」）。
  策略訊號那條 2026-10-19 就改用 `order_fill_price()`；本 helper 讓其餘記帳路徑共用同一條規則。
  價格有變時印一行 📌，方便事後從 log 追。
  """
  try:
    _p = float(order_fill_price(order_ret, decision_px))
  except Exception:
    return decision_px
  if _p > 0 and abs(_p - float(decision_px)) >= 0.005:
    print(f'📌 {label} 記帳價改用實際送單價 {float(decision_px):.2f} → {_p:.2f}')
    return _p
  return decision_px


def keep_wait_tier_hit(tiers, fired, px, profit_pct):
  """keep_wait 分層停利：回傳 (index, tier) 或 None。

  `tp_tiers` 每一層支援兩種寫法（可混用，依陣列順序檢查、先符合者先觸發）：
    {"pct": 15, "ratio": 50}    → 相對均價漲幅 ≥ 15% 觸發
    {"price": 280, "ratio": 50} → 現價 ≥ 280 觸發（絕對價位，2026-10 新增）
  ratio 為該層賣出比例（最後一層＝全數出清）；缺省 ratio=50、pct=15。
  """
  for idx, tier in enumerate(tiers or []):
    if not isinstance(tier, dict) or (idx in fired):
      continue
    try:
      if 'price' in tier:
        if px >= float(tier['price']):
          return idx, tier
      elif profit_pct >= float(tier.get('pct', 15)):
        return idx, tier
    except (TypeError, ValueError):
      continue
  return None

from core.live_broker import create_broker as _create_broker
from core.live_capital import read_capital_file, check_capital_injections as _check_capital_injections, execute_keep_wait_on_profit_roll as _execute_keep_wait_on_profit_roll
STRATEGY_FUNCS = {'vwap': vwap_deviation_strategy, 'ma_cross': ma_cross_strategy, 'bollinger': bollinger_reverse_strategy, 'breakout': breakout_strategy, 'keep_wait': keep_wait_strategy, 'auto': auto_sensing_strategy}
try:
  from user_strategies import USER_STRATEGY_MAP
  STRATEGY_FUNCS.update(USER_STRATEGY_MAP)
except ImportError:
  pass
# 固定式 auto：symbol -> 已鎖定的策略名（買入時定一次、持有期間不換；持久化避免重啟重選）
AUTO_FIXED_CACHE = load_json("logs/auto_resolved.json", {})
# 自選股執行模式：'signal'=B（等 auto 進場訊號，預設）| 'immediate'=A（選股後立即進場一次 → 之後由訊號管理）
SELFSELECT_EXEC_MODE = os.getenv('SELFSELECT_EXEC_MODE', 'signal')
SELFSELECT_FILLED = load_json("logs/selfselect_filled.json", {})
# 「今天嘗試買進但沒成交」的落地紀錄（symbol → YYYY-MM-DD；2026-11-02 新增）。
# 用途：選到但買不到（買入過熱閘門擋下／下單失敗）時，那筆錢既不買股也不會去停泊 0050
#       ⇒ 資金空轉。把「今天試過」也算建倉已處理，停泊才能接手（見 core.park_asset.is_build_attempted）。
ENTRY_ATTEMPTS_PATH = "logs/entry_attempts.json"
entry_attempts = load_json(ENTRY_ATTEMPTS_PATH, {})
TOTAL_CAPITAL = float(os.getenv('TOTAL_CAPITAL', 500000))
BROKER = os.getenv('BROKER', 'kgi')

USE_REAL_API = (os.getenv('USE_REAL_API', 'false').lower() == 'true')
MARKET_TREND_FILTER = (os.getenv('MARKET_TREND_FILTER', 'false').lower() == 'true')
DCA_AMOUNT = float(os.getenv('DCA_AMOUNT', 0))
PROFIT_ROLL_MONTHS = int(os.getenv('PROFIT_ROLL_MONTHS', 5))
PROFIT_ROLL_PERCENTAGE = (float(os.getenv('PROFIT_ROLL_PERCENTAGE', 100)) / 100.0)
MAX_DAILY_TRADES_PER_SYMBOL = int(os.getenv('MAX_DAILY_TRADES_PER_SYMBOL', 1))
PROFIT_MARGIN = float(os.getenv('PROFIT_MARGIN', 100))
# ── 自選股買入當下過熱閘門（both 模式；2026-09-08 加，與方案二B 回測一致）──
ENTRY_OVERHEAT = os.getenv('ENTRY_OVERHEAT', '0') == '1'
OH_RSI_TH = float(os.getenv('OH_RSI_TH', '80'))
OH_DIST_WIN = int(os.getenv('OH_DIST_WIN', '63'))
OH_DIST_TH = float(os.getenv('OH_DIST_TH', '8'))
OH_ENTRY_MODE = os.getenv('OH_ENTRY_MODE', 'both')
def entry_overheat_reject(acd):
  """買入當下是否過熱（只用 acd 日K；參數化，預設 both=RSI超買 且 距N日高近 才拒買）。"""
  if not ENTRY_OVERHEAT:
    return False
  try:
    if acd is None or 'close' not in acd.columns or 'high' not in acd.columns:
      return False
    close = acd['close'].dropna()
    if len(close) < 2:
      return False
    cp = float(close.iloc[-1])
    if cp <= 0:
      return False
    seg = close.iloc[-15:]
    delta = seg.diff()
    up = float(delta[delta > 0].sum())
    dn = float(-delta[delta < 0].sum())
    if up + dn <= 0:
      rsi = 50.0
    else:
      rs = up / dn if dn > 0 else 100.0
      rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi_over = rsi > OH_RSI_TH
    hi = float(acd['high'].iloc[-OH_DIST_WIN:].max()) if len(acd) >= OH_DIST_WIN else float(acd['high'].max())
    near_high = hi > 0 and ((hi - cp) / hi * 100.0) <= OH_DIST_TH
    if OH_ENTRY_MODE == 'both':
      return rsi_over and near_high
    return rsi_over or near_high
  except Exception:
    return False
from core.version import APP_VERSION, build_info
# 建置標記＝由原始碼推導（最新 mtime ＋ 內容指紋），**不是**啟動時間（2026-09-15 修）
_BUILD_TIME, _BUILD_ID = build_info()
BUILD_DATE = _BUILD_TIME   # 舊名保留（其他訊息沿用）
def env_fingerprint(path: str = '.env'):
  """`.env` 內容指紋（md5）；讀不到回 None。

  用途（V4.36）：主迴圈拿它比對「有沒有人改了 `.env`」——原本只有每天 08:40 熱重載一次，
  手動選股/同步後要等到隔天才生效，買價會多漂一天（使用者 2026-09-23 裁定要當天生效）。
  """
  try:
    import hashlib
    return hashlib.md5(Path(path).read_bytes()).hexdigest()
  except Exception:
    return None


def get_stock_capital(symbol: str) -> float:
  cfg = PORTFOLIO_CONFIG.get(symbol, {})
  alloc_pct = float(cfg.get('alloc', 20))
  return ((TOTAL_CAPITAL * alloc_pct) / 100.0)
def main():
  global TOTAL_CAPITAL
  # ── 單實例鎖：host 與 docker 共用 logs/ 掛載（同一 inode），第二個實例直接退出 ──
  #    檔案: logs/trader.lock；flock 隨程序結束自動釋放，無殘留問題
  #    退出碼 0 = 正常結束，避免觸發 docker restart 循環加重
  import fcntl
  _lock_file = open(str(Path('logs') / 'trader.lock'), 'w')
  try:
    fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except OSError:
    print('⚠️ 已有另一個實盤實例在運行，本實例退出（單實例鎖 logs/trader.lock）')
    raise SystemExit(0)
  _started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
  print(f'🚀 TW SelfSelect v{APP_VERSION} (build {_BUILD_TIME} / {_BUILD_ID}) 多股多策略分流系統啟動')
  print(f'📦 版號：v{APP_VERSION}｜建置：{_BUILD_TIME}｜原始碼指紋：{_BUILD_ID}｜啟動：{_started_at}')
  try:
    import subprocess
    r = subprocess.run(['gcloud', 'auth', 'print-access-token'], capture_output=True, text=True, timeout=5)
    if (r.returncode != 0):
      print('⚠️  GCP 認證未通過 — 若需部署至 GCP，請執行：gcloud auth login')
  except FileNotFoundError:
    pass
  except Exception:
    pass
  print(f'📈 個股設定：共 {len(PORTFOLIO_CONFIG)} 檔')
  for (sym, cfg) in PORTFOLIO_CONFIG.items():
    cap = get_stock_capital(sym)
    print(f"   {sym} → {cfg['strategy']}（上限 NT${cap:,.0f}）")
  send_line_notification(f'''
🤖 TW SelfSelect v{APP_VERSION} 雲端主機已成功啟動！開始全天候監控台股...''')
  _startup_msg = (f'''✅ *TW SelfSelect* v{APP_VERSION} 多股多策略系統已啟動
⚙️ 啟動標記: {datetime.now().strftime('%Y%m%d-%H%M%S')}
📈 監控中: ''' + ', '.join((f"{escape_md(s)}({escape_md(c['strategy'])})"
                              for (s, c) in PORTFOLIO_CONFIG.items())))
  send_telegram_message(_startup_msg)
  env_chat_id = os.getenv('TELEGRAM_CHAT_ID', '未設定')
  try:
    requests.post(f'https://api.telegram.org/bot{SYS_TELEGRAM_BOT_TOKEN}/sendMessage', json={'chat_id': SYS_TELEGRAM_CHAT_ID, 'text': f'{env_chat_id} is running !'}, timeout=10)
  except Exception:
    pass
  MAX_RECOMMENDED_STOCKS = 15
  if (len(PORTFOLIO_CONFIG) > MAX_RECOMMENDED_STOCKS):
    print(f'⚠️  警告：投資組合中有 {len(PORTFOLIO_CONFIG)} 支股票，超過建議上限 {MAX_RECOMMENDED_STOCKS} 支。')
    print(f'   由於程式是順序處理，股票過多會導致每輪循環時間拉長，訊號失去即時性。')
    print(f'   建議將股票數降至 {MAX_RECOMMENDED_STOCKS} 支以下，或將程式改為非同步並行架構。')
  budget_file = Path('logs/monthly_budget.json')
  def load_monthly_budget():
    return load_json('logs/monthly_budget.json', {})
  def save_monthly_budget(spent):
    save_json(spent, 'logs/monthly_budget.json')
  def check_monthly_budget(symbol, cost, spent):
    cfg = PORTFOLIO_CONFIG.get(symbol, {})
    limit = float(cfg.get('monthly_budget', 0))
    if (limit <= 0):
      return True
    return ((spent.get(symbol, 0) + cost) <= limit)
  def update_monthly_spending(symbol, cost, spent):
    spent[symbol] = (spent.get(symbol, 0) + cost)
    save_monthly_budget(spent)
  def load_stock_allocation():
    f = Path('logs/stock_allocation.json')
    if f.exists():
      try:
        data = json.loads(f.read_text())
        for sym in PORTFOLIO_CONFIG:
          data.setdefault(sym, {'total_buy_cost': 0, 'total_buy_shares': 0})
        return data
      except:
        pass
    return {sym: {'total_buy_cost': 0, 'total_buy_shares': 0} for sym in PORTFOLIO_CONFIG}
  def save_stock_allocation(alloc):
    save_json(alloc, 'logs/stock_allocation.json')
  def check_stock_cap(symbol, cost, alloc):
    cap = get_stock_capital(symbol)
    if (cap <= 0):
      return True
    st = alloc.get(symbol, {'total_buy_cost': 0})
    return ((st.get('total_buy_cost', 0) + cost) <= cap)
  def load_holdings():
    return load_json('logs/holdings.json', {})
  def save_holdings(h):
    save_json(h, 'logs/holdings.json')
  def load_last_trade_times():
    return load_json('logs/last_trade_times.json', {})
  def save_last_trade_times(times):
    save_json(times, 'logs/last_trade_times.json')
  def load_daily_trades():
    data = load_json('logs/daily_trades.json', {})
    date_str = data.pop('_date', None) if isinstance(data, dict) else None
    return data, date_str
  def save_daily_trades(trades, date_str):
    trades['_date'] = date_str
    save_json(trades, 'logs/daily_trades.json')
  def cci():
    global TOTAL_CAPITAL
    nonlocal lccd, pcap, holdings
    res = _check_capital_injections(TOTAL_CAPITAL, lccd, pcap, broker, rm, holdings, PORTFOLIO_CONFIG, save_holdings, send_telegram_message)
    (TOTAL_CAPITAL, lccd, pcap, holdings) = res

  def mark_entry_attempt(symbol, day):
    """記下「今天嘗試買過這檔但沒成交」——停泊 gate 會把它算成已建倉嘗試（失敗不影響交易）。"""
    if entry_attempts.get(symbol) == day:
      return
    entry_attempts[symbol] = day
    try:
      save_json(entry_attempts, ENTRY_ATTEMPTS_PATH)
    except Exception as e:
      print(f'⚠️ 記錄買入嘗試失敗（不影響交易）: {e}')
  def ensure_park_released_for_buy(reason):
    """要下買單前先把停泊部位全部賣掉換現金（2026-11-02）。回傳釋出金額；0＝沒有停泊部位。

    停泊 0050 的錢＝「還沒買到股票」的閒置資金；真正要買時它必須先變回現金，
    否則會因為現金押在 0050 而整筆下單失敗。
    """
    try:
      if (not _park_sym()) or int((_park_state().get('shares') or 0)) <= 0:
        return 0.0
      return float(park_release_all(reason) or 0.0)
    except Exception as e:
      print(f'⚠️ 停泊釋出失敗（不影響其他交易）：{e}')
      return 0.0

  def place_buy(symbol, qty, reason=''):
    """**所有買單的唯一出口**（2026-11-02）：下單前確保停泊部位已換成現金。

    為什麼要統一出口：買單有 4 條路徑（策略/auto 訊號、mock 路徑、資金加碼、買入補足），
    原本只有「策略訊號」那條會先釋出停泊部位 ⇒ 補足／加碼會在現金仍押在 0050 時送單而失敗。
    """
    try:
      if int(qty or 0) > 0:
        ensure_park_released_for_buy(reason or f'要買 {symbol} 需要資金')
    except Exception as e:
      print(f'⚠️ 買前停泊釋出檢查失敗（照常送單）：{e}')
    return broker.place_order(symbol, 'buy', qty)

  def fit_cash(symbol, qty, px):
    """買單的「現金」上限（2026-11-09 事故後補，v1.1.37）。

    ⚠️ `check_monthly_budget`／`check_stock_cap` 比的是**額度**（alloc × 本金），不是現金
    （2026-11-05 的「額度≠現金」修法只覆蓋**停泊**一條路徑）⇒ 同一天多檔同時給訊號時，
    每一檔的額度都合格、帳戶現金卻不夠交割。

    可用現金 ＝ 本金 − 目前持股成本（`core.park_asset.cash_available()`）。**停泊部位計入可動用**：
    `place_buy()` 下單前一定會先賣掉停泊部位換現金，所以它對買單而言是準現金。
    賣出回款不另外加回（該函式刻意保守），但賣出時分帳本成本會同步調降 ⇒ 「賣掉就自動有額度」。

    估算失敗時**不套用上限**：寧可照原計畫送單，也不要因為一個估價例外讓整排買單消失。
    """
    try:
      from core.park_asset import cash_available as _ca
      _open = 0.0
      for _v in (stock_alloc or {}).values():
        try:
          _open += float((_v or {}).get('total_buy_cost') or 0.0)
        except (TypeError, ValueError):
          pass
      cap = float(_ca(TOTAL_CAPITAL, _open, already_parked_cost=0.0))
    except Exception as e:
      print(f'⚠️ {symbol} 現金上限估算失敗（本次不套用上限）：{e}')
      return int(qty or 0)
    n = fit_buy_qty(qty, px, cap)
    if (n != int(qty or 0)):
      print(f'💰 {symbol} 買單受限於可用現金 NT${cap:,.0f}：{int(qty or 0)} → {n} 股'
            f'（額度檢查已通過，但現金不夠交割）')
    return n

  def ekwr(symbol, profit_amount):
    _execute_keep_wait_on_profit_roll(symbol, profit_amount, broker, rm, holdings, PORTFOLIO_CONFIG, save_holdings, send_telegram_message)
  budget_spent = load_monthly_budget()
  alloc_file = Path('logs/stock_allocation.json')
  stock_alloc = load_stock_allocation()
  total_buy_all = 0
  total_sell_all = 0
  holdings_file = Path('logs/holdings.json')
  holdings = load_holdings()
  daily_trades_file = Path('logs/daily_trades.json')
  cooldown_file = Path('logs/last_trade_times.json')
  ltt = load_last_trade_times()
  from core.market_filter import MarketTrendFilter
  market_filter = MarketTrendFilter()
  pyramid_tracker = {}
  # ⚠️ 必須宣告 global：下一行的賦值若沒有 global，Python 會把整個 main() 內的 USE_REAL_API
  #   當成**區域變數** ⇒ BROKER 不是 esun 時那行不會執行，之後讀取就 UnboundLocalError
  #   （2026-10-25 冒煙測試實測：BROKER=kgi 啟動即崩；原 tw-autotrader 亦有此洞，
  #    只因 .env 一直寫 esun 才沒踩到）。見 test/test_module_global_binding.py。
  global USE_REAL_API
  if (BROKER == 'esun'):
    USE_REAL_API = True
  broker = _create_broker()
  rm = RiskManager(max_risk_per_trade=float(os.getenv('MAX_RISK_PER_TRADE', 0.01)), max_daily_loss=float(os.getenv('MAX_DAILY_LOSS', 0.05)), max_daily_trades=int(os.getenv('MAX_DAILY_TRADES', 10)))

  # ── 閒置資金停泊（2026-10-31 新增；**預設關閉**）──────────────────────────
  # 使用者裁定：① 預設不停泊，要用才設 SELFSELECT_PARK_ASSET=0050（預設標的 0050）；
  #            ② 只在「本月名單已建倉完成」之後才停泊剩下的閒置資金。
  # 設計邊界（見 core/park_asset.py 模組說明）：
  #   · 停泊部位記在獨立帳本 logs/park_position.json，**不進** holdings.json／分帳本
  #     ⇒ 不會被「N=5 上限／已持倉一律保留／孤兒清倉」當成自選股。
  #   · 要買股票前**先全部賣出停泊部位**（單一動作、可稽核）。
  #   · 只在 immediate 模式（signal 模式要把錢留給還沒出現的訊號）。
  def _park_sym():
    from core.park_asset import park_symbol as _ps
    return _ps()

  def _park_state():
    from core.park_asset import load_state as _ls
    return _ls()

  def _park_hold_value(st=None):
    from core.park_asset import load_state as _ls
    st = st if st is not None else _ls()
    sh = int(st.get('shares') or 0)
    if sh <= 0:
      return 0.0
    sym = st.get('symbol') or ''
    try:
      px = broker.get_current_price(sym) if sym else 0
    except Exception:
      px = 0
    return float(sh) * float(px) if px and px > 0 else float(st.get('cost') or 0.0)

  def _park_stock_value():
    total = 0.0
    for _s in PORTFOLIO_CONFIG:
      _sh = holdings.get(_s, 0) or 0
      if _sh <= 0:
        continue
      try:
        _px = broker.get_current_price(_s)
      except Exception:
        _px = 0
      if _px and _px > 0:
        total += float(_sh) * float(_px)
    return total

  def _park_leg_capital():
    return sum(get_stock_capital(_s) for _s in PORTFOLIO_CONFIG)

  def _park_log_trade(rec):
    try:
      with open('logs/park_trades.jsonl', 'a', encoding='utf-8') as _f:
        _f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
      pass

  def park_release_all(reason=''):
    """把停泊部位全部賣掉（要買股票前呼叫）。回傳實際釋出的估算現金。"""
    from core.park_asset import load_state as _ls, save_state as _ss
    try:
      st = _ls()
      sym = st.get('symbol') or _park_sym()
      sh = int(st.get('shares') or 0)
      if sh <= 0 or not sym:
        return 0.0
      px = broker.get_current_price(sym)
      if not px or px <= 0:
        print(f'⚠️ 停泊 {sym} 取不到價格，暫不賣出')
        return 0.0
      # ⚠️ 2026-11-09（v1.1.36）：賣出方向的整股進位會送出**超過庫存**的委託
      #   （持有 1,584 股送 2,000 股 ⇒ 券商只成交 1,000 股或直接退單，2026-11-05 實例）。
      #   ⇒ 送單股數先對齊整股且不超過持有；剩餘零股下一輪（走盤中零股）再賣。
      _send = sell_lot_qty(sh, sh)
      if _send <= 0:
        print(f'⚠️ 停泊 {sym} 持有 {sh} 股無法依整股規則送出，暫不賣出')
        return 0.0
      if _send != sh:
        print(f'↻  停泊釋出 {sym} 股數依整股規則調整：{sh} → {_send} 股（剩 {sh - _send} 股留待零股賣出）')
      ret = broker.place_order(sym, 'sell', _send)
      filled = resolve_fill(broker, sym, 'sell', ret, _send)
      # ⚠️ 2026-11-04（與 park_idle_if_due 同一類缺陷的鏡像）：`resolve_fill()` 回 `None` 是
      #    「成交查不到」，不是「沒成交」。舊寫法 `int(filled or 0)` 會當成 0 ⇒ 帳上仍留著停泊股
      #    ⇒ 下次買股前再賣一次（重複賣出／賣到沒有的股數）或永遠卡住賣不掉。
      #    查不到就沿用「全部賣出」記帳（與其他 3 條賣單路徑一致）。
      # ⚠️ 2026-11-06（同一類缺陷的第三次）：真正送出去的股數可能被券商整股規則改過
      #    （餘數 <500 捨去、≥500 進位）⇒ 記帳一律取 provider 回報的實際送單股數
      #    （`reconcile_order_qty`），與一般買進（1249 行）同一口徑。
      _unknown = (filled is None)
      done = int(reconcile_order_qty(_send, ret) if _unknown else (filled or 0))
      if done != int(sh):
        print(f'⚠️ 停泊釋出 {sym} 記帳股數依實際送單：{int(sh)} → {done} 股'
              f'（殘留 {max(0, int(sh) - done)} 股）')
      px = book_price(ret, px, f'停泊釋出 {sym}')   # 2026-11-03：記帳價用實際送單價
      got = done * float(px)
      left = max(0, sh - done)
      _ss({'symbol': sym, 'shares': left, 'cost': (0.0 if left == 0 else float(st.get('cost') or 0.0)),
           'opened': None if left == 0 else st.get('opened'),
           'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'last_park_ts': st.get('last_park_ts')})
      _park_log_trade({'ts': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'action': 'SELL',
                       'symbol': sym, 'shares': done, 'price': float(px),
                       'reason': reason + ('（成交未確認，先依送單股數記帳）' if _unknown else '')})
      _tag = '（成交未確認，先依送單股數記帳）' if _unknown else ''
      print(f'🅿️ 停泊釋出：賣出 {sym} {done} 股 @ {px:.2f}（{reason}，估 NT${got:,.0f}）{_tag}')
      send_telegram_message(f'🅿️ *停泊釋出*\n{escape_md(sym)} 賣出 {done} 股 @ {px:.2f}\n'
                            f'原因：{escape_md(reason)}{escape_md(_tag)}')
      return got
    except Exception as e:
      print(f'⚠️ 停泊釋出失敗（不影響其他交易）：{e}')
      return 0.0

  def park_idle_if_due():
    """名單建倉完成後，把閒置資金停泊到 SELFSELECT_PARK_ASSET（預設關閉）。

    ⚠️ 2026-11-04 修兩個會「重複下單」的缺陷（VM 實例：0050 282 股 @100.60 連 4 筆）：
      1. `resolve_fill()` 回 `None`（＝**成交查不到，不是沒成交**）時，舊版 `int(filled or 0)`
         當成 0 ⇒ 不記帳 ⇒ 停泊帳不變 ⇒ 下一圈（60 秒後）用同一個 idle 再買一次。
         改為 **None 就沿用送單股數記帳**（與 `resolve_fill` docstring「無法查詢→視為全成交」
         以及其他 4 條買單路徑一致）。
      2. 下單失敗（例如收盤後 `000017`）時沒有留任何時間戳 ⇒ 每圈重試。改為失敗也寫
         `last_park_ts`，讓 5 分鐘冷卻真正生效（冷卻的讀取端另修在 `core.park_asset.load_state`）。
      3. 送單前**再確認一次**在 13:25–13:30 窗口內（迴圈可能在 13:29 起算、送單時已過 13:30）。
    """
    from core.park_asset import (can_park_after_build as _can, idle_amount as _idle,
                                load_state as _ls, park_shares as _shares, save_state as _ss,
                                cash_available as _cash, MIN_PARK_NTD as _MINP)
    try:
      sym = _park_sym()
      if not sym:
        return 0.0
      st = _ls()
      _now_ts = time.time()
      if (_now_ts - float(st.get('last_park_ts') or 0)) < 300:   # 5 分鐘內不重複下單
        return 0.0
      if not _can(SELFSELECT_EXEC_MODE, list(PORTFOLIO_CONFIG), holdings, SELFSELECT_FILLED, sym,
                 attempted=entry_attempts, today=datetime.now().strftime('%Y-%m-%d')):
        try:
          save_json({'date': datetime.now().strftime('%Y-%m-%d'),
                     'ts': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'symbol': sym,
                     'idle': None, 'cash': None, 'cap': 0.0, 'price': 0.0, 'target_shares': 0,
                     'actual_shares': 0, 'status': 'SKIP',
                     'reason': '本月名單尚未建倉完成（等買進）', 'unknown': False},
                    'logs/park_plan.json')
        except Exception:
          pass
        _park_events.append({'action': 'SKIP', 'reason': '本月名單尚未建倉完成（等買進）'})
        return 0.0
      idle = _idle(_park_leg_capital(), _park_stock_value(), _park_hold_value(st))
      _idle_raw = float(idle)
      # ⚠️ 2026-11-05：idle 是「額度」不是「現金」。股票跌了額度會變大、現金不會變多
      #   ⇒ 以持股成本（ledger）估可用現金，取兩者較小者。
      try:
        from core.books import load_ledger as _ll, ledger_cost as _lc
        _open_cost = float(_lc(_ll('logs/stock_allocation.json')) or 0.0)
        _cash_now = _cash(TOTAL_CAPITAL, _open_cost,
                          already_parked_cost=float(st.get('cost') or 0.0))
      except Exception as _ce:
        print(f'⚠️ 停泊：現金估算失敗（保守視為 0）：{_ce}')
        _cash_now = 0.0
      if _cash_now < idle:
        print(f'🅿️ 停泊額度 {idle:,.0f} 受限於可用現金 {_cash_now:,.0f}（額度≠現金）')
        idle = _cash_now
      px = broker.get_current_price(sym)
      n = _shares(idle, px)
      # ⚠️ 2026-11-09 停泊超支事故（v1.1.36）：`_shares()` 取整到「股」，券商的整股規則卻是
      #   四捨五入到「張」（餘數 ≥500 進位）⇒ VM 當天計畫 1,561 股被送成 2,000 股，實付
      #   NT$195,200，而現金上限只有 NT$152,360 ⇒ **超支 NT$42,840（+28%）**，日誌只印了
      #   「記帳股數依實際送單：1561 → 2000（差 -439 股）」卻沒有擋下任何東西。
      #   買進方向的進位就是「多花錢」⇒ 金額上限必須在**對齊整股之後**再檢查一次。
      _n_raw = int(n)
      n = fit_buy_qty(_n_raw, px, idle) if _n_raw > 0 else 0
      if (_n_raw > 0) and (n != _n_raw):
        print(f'🅿️ 停泊股數依整股規則對齊：{_n_raw} → {n} 股'
              f'（NT${_n_raw * float(px):,.0f} → NT${n * float(px):,.0f}，'
              f'上限 NT${float(idle):,.0f}；避免券商進位超支）')
      # 「應該停泊 vs 實際停泊」（使用者 2026-11-05 要求）：每次嘗試都落地一份，報告與 TG 共用。
      _plan = {'date': datetime.now().strftime('%Y-%m-%d'),
               'ts': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'symbol': sym,
               'idle': _idle_raw, 'cash': float(_cash_now), 'cap': float(idle),
               'price': float(px or 0), 'target_shares': int(n), 'actual_shares': 0,
               'status': 'SKIP', 'reason': None, 'unknown': False}

      def _save_plan(**kv):
        _plan.update(kv)
        try:
          save_json(_plan, 'logs/park_plan.json')
        except Exception:
          pass
        return _plan

      if n <= 0 or not px or px <= 0:
        _why = ('取不到報價' if not px or px <= 0
                else f'可用金額 NT${idle:,.0f} 不足（最低門檻 NT${_MINP:,.0f}）')
        _save_plan(status='SKIP', reason=_why)
        _park_events.append({'action': 'SKIP', 'idle': idle, 'price': px, 'reason': _why})
        return 0.0
      if not close_order_window_open(datetime.now()):     # 送單前最後一次時間檢查（避免跨 13:30）
        print('⚠️ 停泊：已過下單窗口（13:25–13:30），本輪不送單')
        _save_plan(status='SKIP', reason='已過下單窗口（13:25–13:30）')
        _park_events.append({'action': 'SKIP', 'reason': '已過下單窗口（13:25–13:30）'})
        return 0.0
      ret = broker.place_order(sym, 'buy', n)
      filled = resolve_fill(broker, sym, 'buy', ret, n)
      _unknown = (filled is None)
      # ⚠️ 2026-11-06 實盤事故：計畫 4,122 股、券商整股捨去只送 4,000 股（`餘數 <500 捨去為 4 張`），
      #   帳上卻記 4,122 股／NT$381,491（實際 NT$370,200）⇒ 多記 122 股、停泊市值與總權益虛胖，
      #   下次釋出時的「估算可動用現金」也跟著偏。成交查不到 ≠ 沒成交，**且送單股數可能被整股規則改過**
      #   ⇒ 記帳一律取 provider 回報的 `sent_qty`（與一般買進同一口徑；2026-09-23 修過同類 bug，
      #   但停泊這段是 2026-10-31 才加的，沒接到那次修正）。
      done = int(reconcile_order_qty(n, ret) if _unknown else (filled or 0))
      if done > 0 and done != int(n):
        print(f'⚠️ 停泊 {sym} 記帳股數依實際送單：{int(n)} → {done} 股（差 {int(n) - done} 股）')
      if done <= 0:
        # 明確失敗（含 stock SDK 取不到報價／券商退單）：留時間戳避免每 60 秒重送
        _ss({'symbol': st.get('symbol') or sym, 'shares': int(st.get('shares') or 0),
             'cost': float(st.get('cost') or 0.0), 'opened': st.get('opened'),
             'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'last_park_ts': _now_ts})
        print(f'⚠️ 停泊 {sym} 送單未成交（{ret if isinstance(ret, dict) else ret}），'
              f'5 分鐘內不重試')
        _save_plan(status='FAIL', reason=str(ret)[:80])
        _park_events.append({'action': 'FAIL', 'shares': n, 'price': px,
                             'reason': str(ret)[:80]})
        return 0.0
      px = book_price(ret, px, f'停泊 {sym}')   # 2026-11-03：記帳價用實際送單價
      cost = done * float(px)
      _ss({'symbol': sym, 'shares': int(st.get('shares') or 0) + done,
           'cost': float(st.get('cost') or 0.0) + cost,
           'opened': st.get('opened') or datetime.now().strftime('%Y-%m-%d'),
           'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'last_park_ts': _now_ts})
      _park_log_trade({'ts': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), 'action': 'BUY',
                       'symbol': sym, 'shares': done, 'price': float(px),
                       'reason': '閒置資金停泊' + ('（成交未確認，先依送單股數記帳）' if _unknown else '')})
      _tag = '（成交未確認，先依送單股數記帳）' if _unknown else ''
      _save_plan(status='BUY', actual_shares=int(done), unknown=bool(_unknown))
      _park_events.append({'action': 'BUY', 'shares': done, 'price': float(px), 'unknown': _unknown})
      print(f'🅿️ 閒置資金停泊：買進 {sym} {done} 股 @ {px:.2f}（NT${cost:,.0f}）{_tag}')
      send_telegram_message(f'🅿️ *閒置資金停泊*\n{escape_md(sym)} 買進 {done} 股 @ {px:.2f}\n'
                            f'金額 NT${cost:,.0f}{escape_md(_tag)}')
      return cost
    except Exception as e:
      print(f'⚠️ 閒置資金停泊失敗（不影響其他交易）：{e}')
      return 0.0
  portfolio_history = {}
  for (symbol, cfg) in PORTFOLIO_CONFIG.items():
    _daily_mode = (cfg.get('strategy') != 'keep_wait')
    # v3.28: 除 keep_wait（signal=0，主程式管理買賣）外全用日K —
    # bollinger/vwap/ma_cross/user 策略回測皆日K；原用分鐘 bars 會讓
    # rolling(20) 變 20 分鐘，訊號隔天反轉亂買賣（2026-09-03 修正）
    if _daily_mode:
      df_init = broker.get_historical_data(symbol, days=260)
    else:
      df_init = (broker.get_minute_bars(symbol, minutes=60) if USE_REAL_API else broker.get_historical_data(symbol, days=30))
    if df_init.empty:
      print(f'⚠️  {symbol} 盤中資料為空，改載入日 K 資料...')
      df_init = broker.get_historical_data(symbol, days=60)
      if (not df_init.empty):
        px = broker.get_current_price(symbol)
        if (px > 0):
          new_row = pd.DataFrame({'open': [(px * 0.999)], 'high': [(px * 1.001)], 'low': [(px * 0.998)], 'close': [px], 'volume': [5000]}, index=[pd.Timestamp.now()])
          df_init = pd.concat([df_init, new_row])
    if df_init.empty:
      print(f'❌ {symbol} 無法取得任何價格資料，跳過')
      continue
    portfolio_history[symbol] = df_init
    print(f"✅ {symbol} 初始化成功 -> [{cfg['strategy'].upper()}]")
  try:
    send_startup_holdings(pd, APP_VERSION, TOTAL_CAPITAL, PORTFOLIO_CONFIG)
  except Exception as e:
    print(f'❌ 發送啟動持倉報告失敗: {e}')
  # 報告已發送日期落地（重啟不重發、跨午夜不重發）——見 core/live_utils.report_due
  _report_state = load_json(REPORT_STATE_PATH, {})
  if (not isinstance(_report_state, dict)):
    _report_state = {}
  # 非交易時段「休眠中」訊息去重（2026-09-22：同一段非交易時段只印一次，避免洗版）
  _idle_notice_state = {}
  _snapshot_tried = [False]   # 每日券商原始快照只跑一次（2026-11-05）
  _booksync_tried = [False]   # 每日「券商成交 vs 帳本」對帳只跑一次（2026-11-05）
  _park_events = []           # 當日停泊動作／跳過原因（給收盤報告與每日停泊狀態 TG 用）
  lccd = None
  pcap = load_processed_capital()
  (daily_symbol_trades, daily_symbol_trades_date) = load_daily_trades()
  if (daily_symbol_trades_date is None):
    daily_symbol_trades = {}
  _order_fail_notified = {}   # {symbol: 'YYYY-MM-DD'} 下單失敗 TG 警示去重
  _risk_notified = {}         # {symbol: 'YYYY-MM-DD'} 風險控管攔截 TG 警示去重（每日一次）
  _overheat_notified = {}     # {symbol: 'YYYY-MM-DD'} 買入過熱被擋的 TG 去重（每日一次，2026-11-02）
  _unknown_notified = {}      # {symbol: 'YYYY-MM-DD'} 「下單結果未明」相關 TG 去重（每日一次，2026-10-19）
  _buy_fill_notified = {}     # {symbol: 'YYYY-MM-DD'} 買入未補足 TG 警示去重（每日一次）
  today_str_init = datetime.now().strftime('%Y-%m-%d')
  if (daily_symbol_trades_date != today_str_init):
    daily_symbol_trades = {}
    daily_symbol_trades_date = today_str_init
    today = date.today().isoformat()
    if (lccd == today):
      pass
    lccd = today
    entries = read_capital_file()
    new_entries = [(d, a) for (d, a) in entries if (f'{d}' not in pcap)]
    if (not new_entries):
      pass
    for (date_str, amount) in new_entries:
      if (amount == 0):
        continue
      old_capital = TOTAL_CAPITAL
      TOTAL_CAPITAL += amount
      pcap.append(date_str)
      source = ('外部加碼' if (amount > 0) else '資金提領')
      msg = f'''💰 *資金變動*
日期: {escape_md(date_str)}
{escape_md(source)}: NT${amount:,.0f}
資本: NT${old_capital:,.0f} → NT${TOTAL_CAPITAL:,.0f}'''
      send_telegram_message(msg)
      print(f'💰 {date_str} {source} NT${amount:,.0f}，資本更新為 NT${TOTAL_CAPITAL:,.0f}')
      if (amount > 0):
        for (symbol, cfg) in PORTFOLIO_CONFIG.items():
          if (cfg.get('strategy') != 'keep_wait'):
            continue
          alloc_pct = float(cfg.get('alloc', 20))
          share_amount = ((TOTAL_CAPITAL * alloc_pct) / 100.0)
          initial_buy_pct = float(cfg.get('initial_buy_pct', 0.7))
          buy_amount = (share_amount * initial_buy_pct)
          px = 0
          try:
            px = broker.get_current_price(symbol)
          except Exception:
            pass
          if (px <= 0):
            continue
          buy_shares = int((buy_amount / px))
          if (buy_shares <= 0):
            continue
          # 2026-11-09（v1.1.37）：額度 ≠ 現金（見 fit_cash）——加碼同樣受可用現金限制
          buy_shares = fit_cash(symbol, buy_shares, px)
          if (buy_shares <= 0):
            print(f'⏸️  {symbol} keep_wait 加碼：可用現金不足，本次不加碼')
            continue
          try:
            _kw_ret = place_buy(symbol, buy_shares, '資金加碼需要資金')
            # 2026-11-06：記帳股數以券商實際送單為準（整股規則會改掉 buy_shares）
            _kw_done = reconcile_order_qty(buy_shares, _kw_ret)
            if int(_kw_done) != int(buy_shares):
              print(f'⚠️ {symbol} 資金加碼記帳股數依實際送單：{int(buy_shares)} → {int(_kw_done)} 股')
            if int(_kw_done) <= 0:
              print(f'⚠️ {symbol} 資金加碼未成交（{_kw_ret}），不記帳')
              continue
            buy_shares = int(_kw_done)
            px = book_price(_kw_ret, px, f'{symbol} 加碼')   # 2026-11-03：記帳價用實際送單價
            rm.log_trade(symbol, 1, px, buy_shares, exclude_from_daily=True)
            holdings[symbol] = (holdings.get(symbol, 0) + buy_shares)
            save_holdings(holdings)
            print(f'📥 {symbol} keep_wait 加碼 {buy_shares} 股 @ {px:.2f}')
            send_telegram_message(rf'📥 *{escape_md(symbol)}* keep\_wait 加碼 {buy_shares} 股 @ {px:.2f}')
          except Exception as e:
            print(f'❌ {symbol} keep_wait 加碼失敗: {e}')
    save_processed_capital(pcap)
  start_watchdog()
  # ── `.env` 熱重載（單一實作；08:40 排程與「內容變更即時套用」共用，V4.36／修正 V4.38）──
  # ⚠️ 2026-09-25 修（V4.38）：這兩個定義原本寫在 `while True:` **裡面** ⇒ `_env_fp_seen` 每圈都被
  #    「當下指紋」重新初始化，於是下一段的比對 `_env_fp_now != _env_fp_seen['v']` **永遠是 False**
  #    ⇒ 即時生效從來沒觸發過（實際退回「隔天 08:40 才生效」）。狀態必須活在迴圈外面。
  _env_fp_seen = {'v': env_fingerprint()}

  def _reload_env_config(reason):
      """重新載入 `.env` 並把 PORTFOLIO_CONFIG 換成新的一份（新標的順手初始化日K）。

      `reason` 只影響訊息（例：`08:40 熱重載`、`偵測到 .env 變更`）。
      失敗不拋例外（不可因一個設定檔問題讓主迴圈停擺）。
      """
      try:
        from dotenv import load_dotenv as _reload
        _reload(override=True)
        new_config = load_portfolio_config()
        removed = set(PORTFOLIO_CONFIG.keys()) - set(new_config.keys())
        PORTFOLIO_CONFIG.clear()
        PORTFOLIO_CONFIG.update(new_config)
        for sym in removed:
          portfolio_history.pop(sym, None)
          pyramid_tracker.pop(sym, None)
        for sym in new_config:
          if sym not in portfolio_history:
            # v3.28: 熱重載新標的比照初始化（除 keep_wait 外全用日K）
            _nm = (new_config[sym].get('strategy') != 'keep_wait')
            df_init = (broker.get_historical_data(sym, days=260) if _nm else
                       (broker.get_minute_bars(sym, minutes=60) if USE_REAL_API else broker.get_historical_data(sym, days=30)))
            if not df_init.empty:
              portfolio_history[sym] = df_init
              print(f'✅ {sym} 熱重載初始化成功')
        # ⚠️ 2026-10-01 實盤事故：新代號也要同步「分帳本」，否則買進後的
        #    `stock_alloc[symbol]['total_buy_cost'] += cost` 會 KeyError（單已成交、
        #    記帳中斷 → 分帳本缺檔 ＋ 成交通知沒發 ＋ 誤發「買入失敗」告警）。
        _missing_ledger = [s for s in new_config if s not in stock_alloc]
        if _missing_ledger:
          ensure_symbol_ledgers(stock_alloc, _missing_ledger)
          save_stock_allocation(stock_alloc)
          print(f'🧾 分帳本已補建新代號：{"、".join(_missing_ledger)}')
        print(f'🔄 {reason} .env 完成，目前監控 {len(PORTFOLIO_CONFIG)} 檔')
        return True
      except Exception as e:
        print(f'⚠️ {reason} .env 失敗（不影響其他策略）：{e}')
        return False

  while True:
    now = datetime.now()
    _HEARTBEAT['ts'] = time.time()
    is_weekday = (now.weekday() < 5)
    # 交易日＝平日且非國定假日（2026-09-15）：交易動作與報告都只在交易日執行。
    # 日曆＝core.trading_calendar（與選股工具同一份，不另寫一套）；
    # 日曆判斷異常時 is_trading_day 保守回 True ⇒ 退回原本的 is_weekday 行為（不可因日曆壞掉停掉交易）。
    is_tday = is_weekday and is_trading_day(now)
    # 日K策略的下單窗口（預設 13:25 起；交易時段至 13:30）——與回測「收盤判定/成交」同口徑
    _close_order_window = close_order_window_open(now)
    (h, m) = (now.hour, now.minute)
    cci()
    today_str = now.strftime('%Y-%m-%d')
    if is_weekday and h == 8 and m >= 40 and globals().get('_hot_reload_date') != today_str:
      try:
        _cal_file = Path('config/taiwan_holidays.json')
        _need_update = True
        if _cal_file.exists():
          try:
            _cal_data = json.loads(_cal_file.read_text(encoding='utf-8'))
            _last_upd = _cal_data.get('_last_updated', '')
            if _last_upd:
              from datetime import datetime as _dt
              _age = (datetime.now() - _dt.strptime(_last_upd, '%Y-%m-%d %H:%M:%S')).days
              _need_update = _age > 30
          except Exception:
            pass
        if _need_update:
          try:
            import subprocess as _sp
            _r = _sp.run([sys.executable, 'scripts/update_taiwan_holidays.py'], capture_output=True, text=True, timeout=60)
            if _r.returncode == 0:
              print(f'📅 休市日曆已自動更新')
            else:
              print(f'⚠️ 休市日曆更新失敗: {_r.stderr[:200]}')
          except Exception as _e:
            print(f'⚠️ 休市日曆更新異常: {_e}')
      except Exception:
        pass
      _reload_env_config('08:40 熱重載')
      globals()['_hot_reload_date'] = today_str
    # ── `.env` 內容變化「即時」生效（V4.36；使用者 2026-09-23 裁定）──────────
    # 原本只有 08:40 一天一次 ⇒ 手動 `VM_pick`／`VM_sync_env`（或自動選股、或直接改 VM 的 .env）
    # 之後要等到隔天才生效，多漂一天的價。改為：每圈比對 `.env` 的內容指紋，一有變化立刻套用
    # ⇒ 只要在 13:25 前改完，**當天** 13:25–13:30 就會用新名單下單。
    _env_fp_now = env_fingerprint()
    if _env_fp_now and _env_fp_seen['v'] and (_env_fp_now != _env_fp_seen['v']):
      print(f"📥 偵測到 .env 內容變更（{_env_fp_seen['v'][:8]} → {_env_fp_now[:8]}）⇒ 立即套用")
      _reload_env_config('偵測到 .env 變更')
    if _env_fp_now:
      _env_fp_seen['v'] = _env_fp_now
    if (daily_symbol_trades_date != today_str):
      daily_symbol_trades = {}
      daily_symbol_trades_date = today_str
      save_daily_trades(daily_symbol_trades, today_str)
      if (now.weekday() == 6):
        ltt = {}
        save_last_trade_times(ltt)
        print(f'🧹 每週自動清空冷卻紀錄 (last_trade_times.json)')
    # ── 三本帳一致性斷言（2026-09-13 新增；純比對股數，不抓價、無網路）──────
    # 抓「只寫進 performance.csv、沒進 holdings.json／分帳本」的部位 ——
    # 那種部位永遠不會被賣出（賣出與孤兒清倉只認 holdings.json），且讓總資產失真。
    # 同一個不一致指紋只通知一次（避免每分鐘洗版）；結果一律 append 到 logs/books_audit.jsonl。
    # 詳見 cairn/total-assets-reconciliation.md
    try:
      from core.books import audit_books as _audit_books, append_audit_log as _log_books
      _ab = _audit_books(holdings=holdings, alloc=stock_alloc,
                         holdings_path='logs/holdings.json')
      if _ab['signature'] != globals().get('_books_audit_sig'):
        globals()['_books_audit_sig'] = _ab['signature']
        _log_books(_ab, {'source': 'selfselect_trader', 'date': today_str})
        if not _ab['ok']:
          print(f"🚨 帳務不一致：{_ab['summary']}")
          send_telegram_message(
            f"🚨 *帳務不一致*\n{escape_md(_ab['summary'])}\n"
            f"（CSV 有、holdings 沒有的部位不會被賣出；分帳本成本缺口 {_ab['ledger_gap']:+,.0f}）")
    except Exception as _ab_e:
      print(f'⚠️ 帳務斷言異常（不影響交易）: {_ab_e}')
    # ── 孤兒持股清倉（交易日**且**交易時段；每檔每日一次）──
    # 2026-09-15：原本註解寫「不限時段」⇒ 週末/國定假日也會對休市市場下賣單，
    # 玉山退單後每天每檔發一次無意義 TG 告警。改為只在交易日執行（下一個交易日再清）。
    # 2026-10-08：再加**時段窗**（09:00–13:30）。原本只有 is_tday ⇒ VM 排程 08:00 開機後
    #   第一圈（約 08:0x）就會送出清倉／trim 委託，此時**盤中零股根本還沒開**（09:00 起）
    #   ⇒ 退單後 `_cleaned_orphans` 已被標記「當日完成」⇒ 該檔**當天不會再試**
    #   ⇒ 清倉／trim 靜默失敗，要等隔天（2026-10-08 使用者要求「主程式自己處理」時查獲）。
    _trade_window = intraday_trade_window(is_tday, h, m)
    _cleaned_orphans = globals().get('_cleaned_orphans', {})
    for old_sym in list(holdings.keys()):
      if not _trade_window:
        break                        # 非交易日／非交易時段（含 08:45 前的試撮段）不對市場下單
      old_shares = holdings.get(old_sym, 0)
      if old_shares <= 0:
        continue
      if old_sym not in PORTFOLIO_CONFIG:
        if _cleaned_orphans.get(old_sym) == today_str:
          continue                     # 這檔今天已清過
        _cleaned_orphans[old_sym] = today_str
        globals()['_cleaned_orphans'] = _cleaned_orphans
        try:
          old_px = broker.get_current_price(old_sym)
          if old_px <= 0:
            continue
          # 2026-11-09（v1.1.36）：整股規則對齊（同停泊釋出）。孤兒股數常見非整張（例：1,584 股），
          #   直接送會被券商進位成 2,000 股（超過庫存 ⇒ 只成交 1,000 股或退單）。
          _orphan_send = sell_lot_qty(old_shares, old_shares)
          if _orphan_send <= 0:
            continue
          if _orphan_send != old_shares:
            print(f'↻  清倉 {old_sym} 股數依整股規則調整：{old_shares} → {_orphan_send} 股'
                  f'（剩 {old_shares - _orphan_send} 股留待零股賣出）')
          _filled, _order_fail_notified, _order_ret = sell_with_fill_check(broker, old_sym, _orphan_send, _order_fail_notified, today_str, send_telegram_message, '清倉')
          if _filled <= 0:
            continue
          old_shares = _filled
          # 2026-11-03：記帳價改用 provider 回報的實際送單價（6505 實測：上方報價 99.9、實際送單 99.60）
          old_px = book_price(_order_ret, old_px, f'{old_sym} 清倉')
          rm.log_trade(old_sym, -1, old_px, old_shares, exclude_from_daily=True)
          send_trade_alert(old_sym, 'SELL', old_px, old_shares, 'CLEANUP')
          print(f'🧹 清倉 {old_sym} {old_shares} 股 @ {old_px:.2f}（不再在 PORTFOLIO_CONFIG 中）')
          _remaining = holdings.get(old_sym, 0) - old_shares
          if _remaining > 0:
            holdings[old_sym] = _remaining
          else:
            del holdings[old_sym]
          save_holdings(holdings)
          if old_sym in stock_alloc:
            stock_alloc[old_sym] = {'total_buy_cost': 0, 'total_buy_shares': 0}
            save_stock_allocation(stock_alloc)
            print(f'🧹 分帳本已重置 {old_sym} → 0')
          if old_sym in budget_spent:
            budget_spent.pop(old_sym, None)
            save_monthly_budget(budget_spent)
        except Exception as _e:
          print(f'⚠️ 清倉 {old_sym} 失敗: {_e}')
          _order_fail_notified = notify_order_failure(old_sym, _e, _order_fail_notified, today_str, send_telegram_message, action="清倉賣出")
    globals()['_cleaned_orphans'] = _cleaned_orphans

    if (is_tday and (((h == 8) and (m >= 45)) or ((h >= 9) and (h < 13)) or ((h == 13) and (m <= 30)))):
      # 2026-10-31：要買新名單前，先把「停泊部位」全部賣掉換現金（只在名單尚未建倉時做一次）。
      #   ⚠️ 這裡刻意不在 `if` 條件裡直接寫 `_close_order_window`：test_close_order_window.py
      #   規定「窗口閘門必須出現在 portfolio_history 更新之後」——用變數承接可保住那條不變式。
      # ── 停泊釋出（2026-11-02 改成「下單前才賣」）──────────────────────────
      # 原本在窗口一開始就把停泊部位全部賣掉；若那一檔當天其實買不到（被過熱閘門擋、
      # 下單失敗），就會變成「賣 0050 → 沒買到 → 當天再停泊回去」的每日來回 churn
      # （0050 來回約 0.39%）。改成由 `place_buy()` 在下單前一刻才釋出：
      # 沒有真的要買，就不會白白賣掉停泊部位；4 條買單路徑也都不會漏掉釋出。
      for (symbol, cfg) in PORTFOLIO_CONFIG.items():
        if (symbol not in portfolio_history):
          continue
        try:
          acd = portfolio_history[symbol]
          sn = cfg['strategy']
          if (MAX_DAILY_TRADES_PER_SYMBOL > 0):
            sym_trades_today = daily_symbol_trades.get(symbol, 0)
            if (sym_trades_today >= MAX_DAILY_TRADES_PER_SYMBOL):
              continue
          last_sell = ltt.get(symbol)
          if last_sell:
            last_sell_dt = datetime.fromisoformat(last_sell)
            if ((now - last_sell_dt).total_seconds() < 1800):
              continue
          if sn != 'keep_wait':
            # ── 日K模式（v3.28 起除 keep_wait 外全策略）：盤中價格合成當日K ──
            # （原 bollinger/vwap/ma_cross concat 分鐘 bars → rolling(20) 變 20 分鐘，
            #   訊號隔天反轉；以「交易日」為單位才與回測一致）
            px_now = broker.get_current_price(symbol)
            if px_now > 0:
              today_str_dt = now.strftime('%Y-%m-%d')
              acd = acd.copy()
              if not acd.empty and str(acd.index[-1])[:10] == today_str_dt:
                # 當日已有K → 更新 high/low/close
                acd.iloc[-1, acd.columns.get_loc('high')] = max(acd.iloc[-1]['high'], px_now)
                acd.iloc[-1, acd.columns.get_loc('low')] = min(acd.iloc[-1]['low'], px_now)
                acd.iloc[-1, acd.columns.get_loc('close')] = px_now
              else:
                new_row = pd.DataFrame({'open': [px_now], 'high': [px_now], 'low': [px_now], 'close': [px_now], 'volume': [0]}, index=[pd.Timestamp(now)])
                acd = pd.concat([acd, new_row])
            if (len(acd) > 260):
              acd = acd.iloc[(- 260):]
          elif USE_REAL_API:
            new_data = broker.get_minute_bars(symbol, minutes=1)
            if (not new_data.empty):
              acd = pd.concat([acd, new_data])
            else:
              px = broker.get_current_price(symbol)
              if (px > 0):
                new_row = pd.DataFrame({'open': [(px * 0.999)], 'high': [(px * 1.001)], 'low': [(px * 0.998)], 'close': [px], 'volume': [5000]}, index=[pd.Timestamp.now()])
                acd = pd.concat([acd, new_row])
          else:
            px = broker.get_current_price(symbol)
            new_row = pd.DataFrame({'open': [(px * 0.999)], 'high': [(px * 1.001)], 'low': [(px * 0.998)], 'close': [px], 'volume': [5000]}, index=[pd.Timestamp.now()])
            acd = pd.concat([acd, new_row])
          if (len(acd) > 100):
            acd = acd.iloc[(- 100):]
          portfolio_history[symbol] = acd
          # ── 日K策略只在「收盤前下單窗口」（預設 13:25–13:30）判定與下單（2026-09-16）──
          # 回測是「當日收盤判定、以收盤價成交」（close_at）；盤中即時判定等於拿開盤價當收盤價，
          # 會做出回測不會做的交易（2026-09-16 2006 實例）。keep_wait（純訊號型加碼）不受影響。
          if (sn != 'keep_wait') and (not _close_order_window):
            continue
          # 固定式 auto：監控期用動態路由(決定買訊)；已買入鎖定後用該固定策略(不再每日重路由)
          _was_auto = (cfg['strategy'] == 'auto')
          # 已無持倉(賣出後) → 釋放 auto 鎖定，讓下次買入時重新鎖定
          if (_was_auto and holdings.get(symbol, 0) <= 0 and symbol in AUTO_FIXED_CACHE):
            AUTO_FIXED_CACHE.pop(symbol, None)
            try:
              save_json(AUTO_FIXED_CACHE, "logs/auto_resolved.json")
            except Exception:
              pass
          if (sn == 'auto'):
            if (symbol in AUTO_FIXED_CACHE):
              _fixed = AUTO_FIXED_CACHE[symbol]
            else:
              try:
                _fixed = route_strategy(acd)
              except Exception:
                _fixed = 'ma_cross'
            sn = _fixed; cfg = dict(cfg); cfg['strategy'] = sn
          strat_func = STRATEGY_FUNCS[sn]
          strat_params = get_strategy_params(cfg, sn)
          signal = strat_func(acd, **strat_params)['signal'].iloc[(- 1)]
          px = acd['close'].iloc[(- 1)]
          # SIGNAL_DEBUG（2026-09-03）：驗證 bollinger/vwap/ma_cross 訊號是否被分鐘資料污染
          # （acd = 日K + 當日分鐘 bars 混合 → rolling(20) 變 20 分鐘而非 20 日）
          if (os.getenv('SIGNAL_DEBUG', '0') == '1') and (signal != 0) and (sn in ('bollinger', 'vwap', 'ma_cross')):
            try:
              _tail = acd.tail(20)
              _span_min = (_tail.index[-1] - _tail.index[0]).total_seconds() / 60.0
              _freq = '日K' if _span_min > 60 * 24 else f'{_span_min:.0f}分鐘(懷疑污染)'
              print(f'🔍 SIGNAL_DEBUG {symbol} {sn} signal={signal} px={px:.0f} 最後20根跨度={_span_min:.0f}分 [{_freq}] 最後一根={acd.index[-1]}')
            except Exception as _dbg_e:
              print(f'🔍 SIGNAL_DEBUG {symbol} 失敗: {_dbg_e}')
          # 自選股執行模式 A（立即買）：auto 股「選股後第一次出現即進場」→ 之後由策略訊號管理
          # 只對 mode=immediate、auto 策略、無持倉、且未記錄過「已立即進場」者
          if (SELFSELECT_EXEC_MODE == 'immediate' and _was_auto and sn != 'keep_wait'
                  and float(cfg.get('max_entry_price', 0)) != -1
                  and holdings.get(symbol, 0) <= 0
                  and symbol not in SELFSELECT_FILLED):
            signal = 1
          if (sn == 'keep_wait'):
            kw_max_entry_price = float(cfg.get('max_entry_price', 0))
            
          
            kw_initial = int(cfg.get('initial_shares', 12))
            kw_add = int(cfg.get('add_shares', 6))
            kw_drop_pct = float(cfg.get('add_drop_pct', 5))
            kw_max_add = int(cfg.get('max_additions', 2))
            kw_tp_pct = float(cfg.get('tp_trigger_pct', 15))
            kw_tp_sell = float(cfg.get('tp_sell_ratio', 50))
            kw_tp_tiers = cfg.get('tp_tiers', None)
            kw_cooldown = int(cfg.get('cooldown_days', 30))
            if (symbol not in pyramid_tracker):
              pyramid_tracker[symbol] = {'buy_count': 0, 'last_buy_price': 0.0, 'total_cost': 0.0, 'total_shares': 0, 'sold_date': None, 'notified_tp': set(), 'tp_tiers_fired': []}
            trk = pyramid_tracker[symbol]
            kw_pre_state = {'buy_count': trk['buy_count'], 'last_buy_price': trk['last_buy_price'], 'total_cost': trk['total_cost'], 'total_shares': trk['total_shares'], 'sold_date': trk['sold_date'], 'tp_tiers_fired': list(trk.get('tp_tiers_fired', []))}
            if (trk.get('sold_date') and (trk['buy_count'] == (- 1))):
              days_since_sold = (datetime.now() - trk['sold_date']).days
              if (days_since_sold < kw_cooldown):
                signal = 0
                continue
              else:
                trk['buy_count'] = 0
            if (trk['buy_count'] == 0):
              existing = holdings.get(symbol, 0)
              if (existing > 0):
                trk['total_shares'] = existing
                trk['total_cost'] = (px * existing)
                trk['last_buy_price'] = px
                trk['buy_count'] = 1
                signal = 0
                print(f'📋 {symbol} keep_wait 偵測到既有持股 {existing} 股，恢復 tracker 狀態')
                continue
              signal = 1
              if (kw_max_entry_price > 0) and (px > kw_max_entry_price):
                signal = 0
                print(f'⏸️  {symbol} keep_wait 初始進場跳過: 價格 {px:.2f} > 上限 {kw_max_entry_price:.2f}')
                continue
              position_size = kw_initial
              trk['last_buy_price'] = px
              trk['total_cost'] = (px * position_size)
              trk['total_shares'] = position_size
              trk['buy_count'] = 1
              print(f'📥 {symbol} keep_wait 初始進場 {position_size} 股 @ {px:.0f}')
            else:
              avg_cost = ((trk['total_cost'] / trk['total_shares']) if (trk['total_shares'] > 0) else px)
              drop_pct = (((trk['last_buy_price'] - px) / trk['last_buy_price']) * 100)
              profit_pct = (((px - avg_cost) / avg_cost) * 100)
              take_profit = False
              if kw_tp_tiers and isinstance(kw_tp_tiers, list) and len(kw_tp_tiers) > 0:
                # ── 多層停利 (tp_tiers)：每層可寫 pct（相對均價 %）或 price（絕對價位）──
                fired_tiers = trk.setdefault('tp_tiers_fired', [])
                tier_triggered = keep_wait_tier_hit(kw_tp_tiers, fired_tiers, px, profit_pct)
                if (tier_triggered is not None) and (trk['total_shares'] > 0):
                  owned = holdings.get(symbol, 0)
                  tier_idx, tier = tier_triggered
                  tier_ratio = float(tier.get('ratio', 50)) / 100.0
                  is_last = (tier_idx == len(kw_tp_tiers) - 1)
                  sell_qty = owned if is_last else max(1, int(owned * tier_ratio))
                  if sell_qty > 0:
                    signal = (- 1)
                    position_size = sell_qty
                    fired_tiers.append(tier_idx)
                    take_profit = True
                    if 'price' in tier:
                      _why = f'現價 {px:.1f} >= {float(tier["price"]):.1f}'
                    else:
                      _why = f'+{profit_pct:.1f}% >= +{float(tier.get("pct", 15)):.1f}%'
                    print(f'📈 {symbol} 停利 T{tier_idx+1}: {_why} 賣出 {sell_qty}/{owned} 股 ({tier.get("ratio", 50)}%)')
                    if is_last:
                      trk['buy_count'] = (- 1)
                      trk['sold_date'] = datetime.now()
              elif ((profit_pct >= kw_tp_pct) and (trk['total_shares'] > 0)):
                # ── 舊版單一停利（向下相容） ──
                owned = holdings.get(symbol, 0)
                if ((kw_tp_sell > 0) and (owned > 0)):
                  sell_qty = max(1, int(((owned * kw_tp_sell) / 100)))
                  signal = (- 1)
                  position_size = sell_qty
                  take_profit = True
                  print(f'📈 {symbol} 停利 +{profit_pct:.1f}% 賣出 {sell_qty}/{owned} 股 ({kw_tp_sell:.0f}%)')
                  trk['buy_count'] = (- 1)
                  trk['sold_date'] = datetime.now()
                elif ((kw_tp_sell == 0) and (owned > 0)):
                  signal = 0
                  if (profit_pct not in trk.setdefault('notified_tp', set())):
                    trk['notified_tp'].add(profit_pct)
                    msg = f'''📈 *{escape_md(symbol)}* 漲幅 +{profit_pct:.1f}% 已達目標 {kw_tp_pct:.0f}%
目前持有 {owned} 股，成本均價 {avg_cost:.0f}
是否手動獲利了結？'''
                    send_telegram_message(msg)
                    print(f'📢 {symbol} 漲 {profit_pct:.1f}% 達標，已通知使用者')
                else:
                  signal = 0
              if (not take_profit) and (signal == 0):
                # ── DCA 加碼檢查 ──
                # 2026-10-27：`max_additions` 的語意＝**加碼次數（不含初始建倉）**。
                #   原本判 `buy_count < max_additions`，但初始建倉／偵測既有持股就把 buy_count 設 1
                #   ⇒ max_additions=2 實際只加碼 1 次（文件與投影片都寫 2 次）。改判 `(buy_count-1)`。
                if ((drop_pct >= kw_drop_pct) and ((trk['buy_count'] - 1) < kw_max_add)):
                  if (kw_max_entry_price > 0) and (px > kw_max_entry_price):
                    print(f'⏸️  {symbol} DCA 跳過: 價格 {px:.2f} > 上限 {kw_max_entry_price:.2f}')
                    signal = 0
                  else:
                    # ⚠️ tracker 只能在真的要下單時更新（2026-10-27 修）：原本這幾行寫在 if/else 之外，
                    #   被 max_entry_price 擋掉的那次也會 ++buy_count、改寫 last_buy_price/total_cost/total_shares
                    #   ⇒ 加碼額度被吃掉、均價與股數記成沒發生的交易。
                    signal = 1
                    position_size = kw_add
                    trk['last_buy_price'] = px
                    trk['total_cost'] += (px * position_size)
                    trk['total_shares'] += position_size
                    trk['buy_count'] += 1
                    print(f"📉 {symbol} DCA 第 {trk['buy_count']} 次加碼 {position_size} 股 @ {px:.0f}（距前次 -{drop_pct:.1f}%）")
                else:
                  signal = 0
            if (signal == 0):
              continue
          if (signal != 0):
            action = ('BUY' if (signal == 1) else 'SELL')
            if ((action == 'BUY') and (sn != 'keep_wait') and entry_overheat_reject(acd)):
              print(f'⏸️  {symbol} 買入過熱(RSI>{OH_RSI_TH:.0f}且距{OH_DIST_WIN}日高{OH_DIST_TH:.0f}%內)，跳過此訊號')
              # 2026-11-02：被擋也要（1）記成「今天已嘗試」讓停泊 0050 能接手（2）發一次 TG
              #   原本只印 log ⇒ 沒看 log 的人不會知道這檔沒買到，而錢也就一直閒置。
              if (action == 'BUY'):
                mark_entry_attempt(symbol, today_str)
                if (_overheat_notified.get(symbol) != today_str):
                  _overheat_notified[symbol] = today_str
                  send_telegram_message(
                    f'⏸️ *{escape_md(symbol)}* 買入被「過熱閘門」擋下\n'
                    f'條件：RSI > {OH_RSI_TH:.0f} 且距 {OH_DIST_WIN} 日高 ≤ {OH_DIST_TH:.0f}%\n'
                    f'⇒ 今天先不買；閒置資金改去停泊，下一個交易日的 13:25–13:30 會再試一次')
              signal = 0
              continue
            if (sn == 'keep_wait'):
              pass
            else:
              position_size = 0
            if (sn != 'keep_wait'):
              # 所有非 keep_wait 策略共用同一條買入量規則（2026-10-06 併入 breakout）：
              # 買入量 = 個股資金上限（alloc × TOTAL_CAPITAL）；**滿倉不買**；賣出 = 全賣。
              # ⚠️ 回測口徑（`scripts/backtest_plan2_monthly_3group.py`）：`elif sh == 0 and sig == 1`
              #    ⇒ **只有空倉才買**、買完桶子歸零 ⇒ 重複買訊也買不動（＝滿倉不買）。
              #    2026-10-06 之前 breakout 有自己的分支（每個買訊都再買「一整個部位」、不看持倉）
              #    ⇒ 持有中再遇買訊、且帳戶有可用資金時會重複加碼超過 alloc。breakout 的訊號是
              #    **狀態型**（突破期間每天重發；實測 2884 於 2026-09 連發 8 個交易日）⇒ 已併入本分支。
              # 滿倉判定：held ≥ target×(1-BUY_AMOUNT_OFFSET) 即視為足額（2026-09-01；2026-10-06 抽成純函式）
              alloc_pct = float(cfg.get('alloc', 12.5))
              target_amount = (TOTAL_CAPITAL * alloc_pct) / 100.0
              buy_offset = float(os.getenv('BUY_AMOUNT_OFFSET', '0.02'))
              if (action == 'BUY'):
                # auto 的「買入即鎖定」已移到**下單前的共用位置**（見下方 `_lock_auto_on_fill`）。
                # ⚠️ 2026-09-18：原本只寫在這個分支裡 ⇒ **routed=breakout 的 auto 股永遠不會被鎖定**，
                #    於是持有期間每天重路由、策略可能中途被換掉（與回測不一致）。
                held = holdings.get(symbol, 0)
                target_shares = int((target_amount / px)) if px > 0 else 1
                position_size = full_position_topup(held, target_shares, buy_offset)
                if (position_size <= 0):
                  print(f'⏸️  {symbol} 持倉 {held} ≥ 目標 {target_shares}×(1-{buy_offset:.0%})，不重複買入')
                  signal = 0
                  continue
              else:
                position_size = int(holdings.get(symbol, 0))
            if (position_size <= 0):
              continue
            # ── 券商整股規則對齊（2026-11-09，v1.1.36；見 core/lots.py）────────────────
            # 買進：券商的「餘數 ≥500 進位」會讓實付金額**超過**這裡算好的計畫金額 ⇒
            #   `check_monthly_budget`／`check_stock_cap` 是在對齊後的股數上算，才不會被進位打穿
            #   （停泊 1,561→2,000 股超支 NT$42,840 就是這個漏洞）。
            # 賣出：反過來，進位會送出超過庫存的委託（持有 1,584 股送 2,000 股 ⇒ 只成交 1,000 股）。
            _asked_size = int(position_size)
            if (action == 'BUY'):
              position_size = fit_buy_qty(_asked_size, px)
            else:
              position_size = sell_lot_qty(_asked_size, holdings.get(symbol, 0))
            if (position_size != _asked_size):
              _what = '買單' if (action == 'BUY') else '賣單'
              print(f'↻  {symbol} {_what}股數依券商整股規則對齊：{_asked_size} → {position_size} 股'
                    f'（避免下單時才改股數／金額超出上限）')
            if (action == 'BUY'):
              # 2026-11-09（v1.1.37）：額度 ≠ 現金——額度檢查（月度預算／單檔上限）都通過之後，
              #   再用「可用現金」夾一次（見 fit_cash 的說明）。
              position_size = fit_cash(symbol, position_size, px)
            if (position_size <= 0):
              continue
            (allowed, reject_reason) = rm.check_trade_allowed(symbol, signal, px, total_buy=total_buy_all, total_sell=total_sell_all)
            if (not allowed):
              if (_risk_notified.get(symbol) != today_str):
                _risk_notified[symbol] = today_str
                send_telegram_message(f'🛑 *{escape_md(symbol)}* 風險控管攔截（{escape_md(reject_reason)}）')
              continue
            if (action == 'BUY'):
              trade_cost = (px * position_size)
              if not check_monthly_budget(symbol, trade_cost, budget_spent):
                continue
              if not check_stock_cap(symbol, trade_cost, stock_alloc):
                continue
            if ((action == 'BUY') and (os.getenv('MARKET_TREND_FILTER', 'true').lower() == 'true')):
              if (not market_filter.is_above_ma200()):
                print(f'🛑 {symbol} 買進被大盤年線過濾攔截')
                continue
            if (action == 'SELL'):
              owned = holdings.get(symbol, 0)
              if (owned < position_size):
                if (owned > 0):
                  print(f'⚠️  {symbol} 持有 {owned} 股，不足賣出 {position_size} 股，跳過')
                continue
            if ((PROFIT_MARGIN > 0) and (action == 'SELL')):
              alloc_data = stock_alloc.get(symbol, {})
              sell_shares = alloc_data.get('total_buy_shares', 0)
              sell_cost = alloc_data.get('total_buy_cost', 0.0)
              if (sell_shares > 0):
                avg_cost = (sell_cost / sell_shares)
              elif ((sn == 'keep_wait') and (symbol in pyramid_tracker)):
                trk = pyramid_tracker[symbol]
                avg_cost = ((trk['total_cost'] / trk['total_shares']) if (trk['total_shares'] > 0) else px)
              else:
                avg_cost = px
              expected_profit = ((px - avg_cost) * position_size)
              if (abs(expected_profit) < PROFIT_MARGIN):
                print(f'⏸️  {symbol} 預估損益 {expected_profit:+.0f} 低於門檻 {PROFIT_MARGIN:.0f}，跳過')
                continue
            # ── auto 買入即鎖定（2026-09-18 移到共用位置）──────────────────────
            # 放在「下單之前、所有風控/預算/大盤年線檢查之後」：被風控擋掉的買單不會留下鎖定
            # （且即使殘留，下一輪的「部位歸零即釋放」也會清掉）。
            # 為何要搬：原本這段只寫在 `if (sn not in ['breakout','keep_wait'])` 分支內
            # ⇒ **routed=breakout 的 auto 股永遠不會被鎖定**，持有期間每天重路由、策略可能被換掉；
            # 回測（STRAT_MODE=form）四種策略一律鎖定 ⇒ 那是實盤偏離回測。
            # 鎖定值用 `sn`：未鎖定的 auto 股，本輪 sn 就是 `route_strategy(acd)`（當下型態），
            # 與回測「進場當天定策略」一致。
            if (action == 'BUY') and _was_auto and (symbol not in AUTO_FIXED_CACHE):
              AUTO_FIXED_CACHE[symbol] = sn
              try:
                save_json(AUTO_FIXED_CACHE, "logs/auto_resolved.json")
              except Exception:
                pass
              print(f'🔒 {symbol} auto 買入鎖定策略 → {sn}（持有期間不再重路由）')
            # 2026-10-19：「下單結果未明」校正關卡（買入前）——見 core/live_utils 的說明。
            # 今日曾逾時 ⇒ 今日不再買（當日重買必重複）；隔日先問券商庫存：
            #   券商股數 > 帳本 ⇒ 補記帳（那筆其實成交了）；券商沒有 ⇒ 視為未成交，清掉紀錄。
            if (action == 'BUY'):
              _unk = load_unknown_orders()
              if symbol in _unk:
                if unknown_order_blocks_buy(symbol, _unk, today_str):
                  if (_unknown_notified.get(symbol) != today_str):
                    _unknown_notified[symbol] = today_str
                    print(f'⏸️ {symbol} 今日曾下單逾時（結果未明）⇒ 今日不再買入')
                    send_telegram_message(f'⏸️ *{escape_md(symbol)}* 今日曾下單逾時（結果未明），今日不再買入')
                  continue
                _bq = broker_holding_qty(broker, symbol)
                _had = holdings.get(symbol, 0)
                if _bq is None:
                  print(f'⚠️ {symbol} 有「結果未明」紀錄但查不到券商庫存 ⇒ 本次不買（保守）')
                  if (_unknown_notified.get(symbol) != today_str):
                    _unknown_notified[symbol] = today_str
                    # 指令本身有底線（tw_selfselect_bot／reconcile_broker_books）⇒ 靜態轉義，
                    #   使用者複製的是純文字、顯示也不會被當成斜體
                    send_telegram_message(f'⚠️ *{escape_md(symbol)}* 先前委託結果未明且查不到券商庫存，請人工對帳'
                                          rf'（docker exec tw\_selfselect\_bot python '
                                          rf'scripts/reconcile\_broker\_books.py）')
                  continue
                if _bq > _had:
                  _delta = _bq - _had
                  print(f'🧾 {symbol} 先前逾時委託其實已成交 {_delta} 股 ⇒ 補記帳（{_had} → {_bq} 股 @ {px:.2f}）')
                  holdings[symbol] = _bq
                  save_holdings(holdings)
                  rm.log_trade(symbol, 1, px, _delta, exclude_from_daily=True)
                  _led_u = ensure_symbol_ledgers(stock_alloc, [symbol])[symbol]
                  _led_u['total_buy_cost'] += (px * _delta)
                  _led_u['total_buy_shares'] += _delta
                  save_stock_allocation(stock_alloc)
                  send_telegram_message(f'🧾 *{escape_md(symbol)}* 先前逾時委託已成交 {_delta} 股（@{px:.2f}）⇒ 已依券商庫存補記帳')
                else:
                  print(f'🧾 {symbol} 先前逾時委託未成交（券商庫存 {_bq} 股）⇒ 清掉未明紀錄')
                clear_unknown_order(symbol)
                continue
            # 2026-11-02：買單一律走 `place_buy()`（下單前才釋出停泊部位，賣出不動停泊）。
            if USE_REAL_API:
              order_result = (place_buy(symbol, position_size) if (action == 'BUY')
                              else broker.place_order(symbol, action.lower(), position_size))
              if ('error' in order_result):
                if (action == 'BUY'):
                  mark_entry_attempt(symbol, today_str)   # 買入失敗也視為「今天試過」⇒ 停泊可接手（2026-11-02）
                _order_fail_notified = notify_order_failure(symbol, f'{order_result["error"]}', _order_fail_notified, today_str, send_telegram_message, action=('買入' if action == 'BUY' else '賣出'))
                if (sn == 'keep_wait'):
                  trk['buy_count'] = kw_pre_state['buy_count']
                  trk['last_buy_price'] = kw_pre_state['last_buy_price']
                  trk['total_cost'] = kw_pre_state['total_cost']
                  trk['total_shares'] = kw_pre_state['total_shares']
                  trk['sold_date'] = kw_pre_state['sold_date']
                  trk['tp_tiers_fired'] = list(kw_pre_state.get('tp_tiers_fired', []))
                # 2026-10-19：逾時回來的 error 是「結果未明」——下單執行緒可能稍後才成交
                # （當天 8046 就是這樣），若不落地追蹤，隔天「未持股每天重試補足」會買成 2 倍。
                if isinstance(order_result, dict) and order_result.get('unknown'):
                  try:
                    record_unknown_order(symbol, position_size, today_str, action=action)
                    print(f'🧾 {symbol} 下單結果未明（逾時）⇒ 已落地；今日不再買，明日買入前先向券商校正')
                    send_telegram_message(f'🧾 *{escape_md(symbol)}* 下單逾時（結果未明）⇒ 今日不再買；明日開盤前會先向券商校正庫存')
                  except Exception as _ue:
                    print(f'⚠️ 記錄「下單結果未明」失敗: {_ue}')
                continue
              # 2026-10-19：記帳價改用「實際送單價」（provider 送單前會重新取價）。
              # 當天 6505 決策價 123.0、實際成交 123.50 ⇒ 帳本成本少記 338 元、對帳每天誤報。
              _sent_px = order_fill_price(order_result, px)
              if abs(_sent_px - px) >= 0.005:
                print(f'📌 {symbol} 記帳價改用實際送單價 {px:.2f} → {_sent_px:.2f}')
                px = _sent_px
              _filled = resolve_fill(broker, symbol, action, order_result, position_size)
              if _filled is not None and _filled < position_size:
                if _filled <= 0:
                  _order_fail_notified = notify_order_failure(symbol, f'委託未成交（排隊中）{order_result}', _order_fail_notified, today_str, send_telegram_message, action='買入')
                  continue
                print(f'⚠️ {symbol} 部分成交 {_filled}/{position_size} 股')
                position_size = _filled
              else:
                # ── 券商整股規則會改動真正送出的股數（2026-09-23 實盤事故）────────────
                # 玉山 provider 對整股單四捨五入到「張」（餘數 ≥500 進位、<500 捨去），但 13:25
                # 送整股單時 check_fill() 還查不到成交（13:30 才撮合）⇒ resolve_fill() 回 None
                # ⇒ 若照計畫股數記帳，holdings/CSV 會與券商庫存不符（實測：2884 送 2000 股只記
                # 1584、5876 送 1000 股卻記 1461）。以 provider 回報的實際送單股數為準。
                _sent_qty = reconcile_order_qty(position_size, order_result)
                if (_sent_qty > 0) and (_sent_qty != position_size):
                  print(f'⚠️ {symbol} 券商整股規則調整下單股數：{position_size} → {_sent_qty} 股'
                        f'（以實際送單股數記帳）')
                  position_size = _sent_qty
            else:
              if (action == 'BUY'):
                place_buy(symbol, position_size)
              else:
                broker.place_order(symbol, action, position_size)
            rm.log_trade(symbol, signal, px, position_size, exclude_from_daily=False)
            if (action == 'BUY'):
              holdings[symbol] = (holdings.get(symbol, 0) + position_size)
            else:
              holdings[symbol] = max(0, (holdings.get(symbol, 0) - position_size))
            save_holdings(holdings)
            if (MAX_DAILY_TRADES_PER_SYMBOL > 0):
              daily_symbol_trades[symbol] = (daily_symbol_trades.get(symbol, 0) + 1)
              save_daily_trades(daily_symbol_trades, daily_symbol_trades_date)
            if (action == 'SELL'):
              ltt[symbol] = now.isoformat()
              save_last_trade_times(ltt)
              sell_proceeds = (px * position_size)
              total_sell_all += sell_proceeds
              if ((symbol in pyramid_tracker) and (sn != 'keep_wait')):
                del pyramid_tracker[symbol]
              if (symbol in stock_alloc):
                _sell_profit, _ = sell_stock_allocation(stock_alloc, symbol, position_size, sell_proceeds)
                if _sell_profit is not None:
                  save_stock_allocation(stock_alloc)
                  if ((_sell_profit > 0) and (sn == 'keep_wait')):
                    ekwr(symbol, _sell_profit)
            if (action == 'BUY'):
              if (SELFSELECT_EXEC_MODE == 'immediate' and _was_auto and (symbol not in SELFSELECT_FILLED)):
                SELFSELECT_FILLED[symbol] = today_str
                save_json(SELFSELECT_FILLED, "logs/selfselect_filled.json")
              trade_cost = (px * position_size)
              total_buy_all += trade_cost
              update_monthly_spending(symbol, trade_cost, budget_spent)
              # 2026-10-01：不可直接索引——熱新增的標的還沒在分帳本裡（見 ensure_symbol_ledgers）
              _led = ensure_symbol_ledgers(stock_alloc, [symbol])[symbol]
              _led['total_buy_cost'] += trade_cost
              _led['total_buy_shares'] += position_size
              save_stock_allocation(stock_alloc)
            action_zh = ('買進' if (action == 'BUY') else '賣出')
            # auto：把「今日型態路由到的底層策略」帶進通知（依 acd 最新 K 線即時判斷，無前瞻）
            _strat_label = sn.upper()
            if (sn == 'auto'):
              try:
                _routed = route_strategy(acd) if ('close' in acd.columns) else 'ma_cross'
                _strat_label = f'AUTO(路由→{_routed})'
              except Exception:
                _strat_label = 'AUTO'
            notice_msg = f'''
🔔 交易通知
股票: {symbol}
動作: {action_zh}
價格: {px:.2f}
股數: {position_size} 股
策略: {_strat_label}'''
            send_trade_alert(symbol, action, px, position_size, _strat_label)
            send_line_notification(notice_msg)
        except Exception as e:
          print(f'❌ {symbol} 錯誤: {e}')
          _order_fail_notified = notify_order_failure(symbol, e, _order_fail_notified, today_str, send_telegram_message, action="買入")
      # ── 閒置資金停泊（只在 13:25–13:30 的下單窗口）─────────────────────────
      # ⚠️ 2026-11-05 修（重大）：這個呼叫點原本在**兩個「必定 continue」的分支之後**
      #   （交易日 08:45–13:30 主區塊、13:31+ 收盤報告區塊），交易日結構上永遠到不了它。
      #   v1.1.22 之前之所以看起來「有效」，是因為 `close_order_window_open()` 當時沒有上限，
      #   停泊其實是在 **13:30 收盤後（多半 14:00+）**才執行 ⇒ 那幾筆 0050 是收盤後下的單，
      #   也正是 `000017: 非該盤別盤中或預約時間` 的來源。v1.1.22 補上上限後停泊就再也不會動了
      #   （實測 2026-11-05 13:25–13:30：idle 30.6 萬、所有前置條件都成立，卻一筆都沒送）。
      #   ⇒ 正確位置是「交易時段區塊內、下單窗口時」呼叫，收盤後一律不送。
      if _close_order_window and _park_sym():
        try:
          park_idle_if_due()
        except Exception as _pke:
          print(f'⚠️ 停泊流程異常（不影響交易）：{_pke}')
      time.sleep(60)
      continue
    if (is_tday and (h == 13) and (m >= 31)):
      # 13:45 收盤報告 ＋ 睡前持倉報告**同一輪**發送（2026-09-15）：
      # VM 依 GCP 執行個體排程在台北 14:00 關機，睡前報告若等到非交易時段分支
      # （約 14:00:3x）才發，會與關機競態而整份掉掉。非交易時段分支仍保留為補發路徑。
      if ((m >= 45) and report_due(now, _report_state, 'daily_report', trading_day=is_tday)):
        send_daily_report(pd, date)
        send_closing_summary(pd, APP_VERSION, TOTAL_CAPITAL, PORTFOLIO_CONFIG)
        try:
          from scripts.generate_dashboard import main as gen_dash
          gen_dash()
        except Exception as e:
          print(f'❌ 產生儀表板失敗: {e}')
        # ── 每日券商原始快照（2026-11-05）──────────────────────────────
        # 為什麼：模擬環境的查詢 API **不保留歷史**（get_transactions_by_date 對 11/03 回 0 筆，
        #   連當天確定成交的股票都沒有），事後完全無法回溯「券商到底有沒有那筆」。
        #   ⇒ 每天收盤把 inventories／transactions／order_results／balance 原始回傳落地，
        #   之後用 `scripts/reconcile_broker_books.py --from-json logs/broker_snapshot_<date>.json` 重跑。
        if not _snapshot_tried[0]:
          try:
            from scripts.snapshot_broker import already_done as _snap_done, main as _snap_main
            _snapshot_tried[0] = True
            if _snap_done('logs'):
              print('📸 今日券商快照已存在，跳過')
            else:
              # --no-dotenv：不要在本行程內 load_dotenv(override=True)，避免 13:45 之後的設定被換掉
              _rc = _snap_main(['--quiet', '--no-dotenv'])
              if _rc == 0:
                print('📸 今日券商原始快照已落地（logs/broker_snapshot_*.json）')
              else:
                print(f'⚠️ 券商快照未完成（rc={_rc}；不影響交易）')
          except Exception as _se:
            print(f'⚠️ 券商快照失敗（不影響交易）：{_se}')
        # ── 收盤對帳（2026-11-05）：券商成交回報 vs 帳本 ⇒ **只修正 holdings，不下單** ──
        # 為什麼：11/05 的 2615 送 2 張整股賣單、券商只成交 1 張，帳本卻記成全部賣出
        #   （`resolve_fill()` 在 13:27 查不到成交時走「查不到＝全成交」）。若那 1,000 股還在手上，
        #   明天同檔出現買訊就會重複建倉。方向刻意不對稱：**賣出少成交 → 預設自動補回持股**（保守方向）；
        #   **買進少成交 → 預設只告警**（`BROKER_SYNC_TRIM=1` 才真的減，避免減錯造成重複建倉）。
        if not _booksync_tried[0]:
          try:
            from core.broker_sync import run_daily as _bs_run
            _booksync_tried[0] = True
            _rep = _bs_run(broker, today_str)
            _chg = _rep.get('changed') or {}
            _alerts = [p for p in (_rep.get('plan') or []) if p.get('action') != 'unknown']
            _unknown = [p for p in (_rep.get('plan') or []) if p.get('action') == 'unknown']
            print(f"🧾 收盤對帳：{_rep.get('summary')}")
            if _chg:
              _lines = '\n'.join(f"{k}: {v[0]} → {v[1]} 股" for k, v in _chg.items())
              print(f"🧾 收盤對帳：修正帳本\n{_lines}")
              send_telegram_message(f'🧾 *收盤對帳：帳本已依券商成交修正*\n{escape_md(_lines)}\n'
                                    rf'（只改帳、未下單；稽核 logs/broker\_reconcile.jsonl）')
            elif _alerts:
              _lines = '\n'.join(f"{p['sid']} {p['side']}｜帳本 {p['book']:.0f} / 券商 {p['broker']}"
                                  f"｜{p['note']}" for p in _alerts)
              print(f"⚠️ 收盤對帳差異（未改帳）\n{_lines}")
              send_telegram_message(f'⚠️ *收盤對帳差異（未改帳）*\n{escape_md(_lines)}')
            if _unknown:
              print("⚠️ 收盤對帳：以下代號在券商成交回報裡查不到（模擬環境只回當日／可能缺漏），"
                    "不改帳：" + ', '.join(f"{p['sid']}({p['side']})" for p in _unknown))
          except Exception as _be:
            print(f'⚠️ 收盤對帳失敗（不影響交易）：{_be}')
        # ── 停泊帳對帳（2026-11-06，v1.1.35）：帳本 × 稽核檔重播 × 券商庫存 ────────────────
        # 為什麼：停泊交易寫 `logs/park_trades.jsonl`、**不在** performance.csv
        #   ⇒ 上面那段 broker_sync 完全看不到停泊帳（2026-11-06「帳面 4,122 / 券商 4,000」的 122 股幻影
        #   就是這樣潛伏的：兩份對帳工具都只讀 performance.csv，停泊帳沒有任何自動防護）。
        # 原則：**只告警、不自動改帳**——停泊不影響下單股數，只影響權益與現金估算，
        #   自動改錯的風險比留著人工確認更高。
        if (_report_state.get('park_recon') != today_str):
          try:
            from core.park_asset import (check_position as _pchk, load_state as _pls3,
                                        load_trades as _ptr, traded_on as _ptod)
            _pst = _pls3()
            _psym2 = _pst.get('symbol') or _park_sym()
            _precs = _ptr()
            try:
              _pbq = broker_holding_qty(broker, _psym2) if _psym2 else None
            except Exception:
              _pbq = None
            _prc = _pchk(int(_pst.get('shares') or 0), _precs, broker_shares=_pbq,
                         traded_today=_ptod(_precs, today_str, _psym2))
            _report_state['park_recon'] = today_str      # 每天只做一次（不論結果）
            save_json(_report_state, REPORT_STATE_PATH)
            if _prc['status'] in ('ledger_mismatch', 'broker_mismatch'):
              _btxt = f"／券商 {_prc['broker']:,} 股" if _prc.get('broker') is not None else ''
              print(f"⚠️ 停泊帳對帳：{_prc['status']}｜{_prc['note']}")
              send_telegram_message(f"⚠️ *停泊帳對帳差異*（{today_str}）\n"
                                    f"{escape_md(_psym2)}：帳面 {_prc['book']:,} 股{escape_md(_btxt)}\n"
                                    f"{escape_md(_prc['note'])}\n"
                                    f"（只告警、未改帳；請用券商快照核對後人工修帳）")
            elif _prc['status'] != 'ok':
              print(f"ℹ️ 停泊帳對帳：{_prc['status']}｜{_prc['note']}")
          except Exception as _pce:
            print(f'⚠️ 停泊帳對帳失敗（不影響交易）：{_pce}')
        # ── 每日停泊狀態（2026-11-05）：成功／失敗／**沒做**都要有一則，且每天只一則 ──
        # 為什麼：「停泊成功才有聲音、沒做與失敗全靜默」正是它壞了四天沒人發現的原因。
        if (_report_state.get('park_status') != today_str):   # 每日一次（不用 report_due：13:31+ 區塊的守門測試要求剛好 2 次）
          try:
            from core.park_asset import (cash_available as _pcash, format_position as _pfmt,
                                        load_state as _pls, skip_reason as _pskip)
            _st = _pls()
            _sym = _st.get('symbol') or _park_sym()
            _sh = int(_st.get('shares') or 0)
            _cost = float(_st.get('cost') or 0.0)
            _avg = (_cost / _sh) if (_sh > 0 and _cost > 0) else None
            try:
              _px_now = broker.get_current_price(_sym) if (_sym and _sh > 0) else None
            except Exception:
              _px_now = None
            try:
              _idle_now = max(0.0, _park_leg_capital() - _park_stock_value() - _park_hold_value(_st))
            except Exception:
              _idle_now = None
            try:
              from core.books import load_ledger as _ll, ledger_cost as _lc
              _cash_now = _pcash(TOTAL_CAPITAL, float(_lc(_ll('logs/stock_allocation.json')) or 0.0),
                                 already_parked_cost=_cost)
            except Exception:
              _cash_now = None
            from core.park_asset import format_plan_vs_actual as _fpa
            _lines = [f'🅿️ *停泊狀態*（{today_str}）',
                      f'   {escape_md(_pfmt(_sym or "—", _sh, _avg, _px_now))}']
            _plan = None
            try:
              import json as _json
              with open('logs/park_plan.json', encoding='utf-8') as _pf:
                _plan = _json.load(_pf)
            except Exception:
              _plan = None
            if _plan and str(_plan.get('date') or '') == today_str:
              # _fpa 內部已轉義動態原因並保留 `*粗體*` ⇒ 這裡原樣送
              _lines += [f'   {_ln}' for _ln in _fpa(_plan)]
            else:
              _why = _pskip(shares=_sh, cash=_cash_now, idle=_idle_now)
              _lines.append(f'   今日未停泊：{escape_md(_why or "今天沒有觸發停泊")}')
              if _idle_now is not None:
                _lines.append(f'   閒置額度 NT${_idle_now:,.0f}｜可用現金 '
                              + (f'NT${_cash_now:,.0f}' if _cash_now is not None else '未知'))
            send_telegram_message('\n'.join(_lines))
            print('🅿️ 停泊狀態已發送：' + _lines[1].strip())
            _report_state['park_status'] = today_str
            save_json(_report_state, REPORT_STATE_PATH)
          except Exception as _pe:
            print(f'⚠️ 停泊狀態通知失敗（不影響交易）：{_pe}')
        mark_report_sent(_report_state, 'daily_report', now)
        save_json(_report_state, REPORT_STATE_PATH)
      if ((m >= 45) and report_due(now, _report_state, 'sleep', trading_day=is_tday)):
        try:
          send_sleep_notification(pd, APP_VERSION, _next_market_open(now), TOTAL_CAPITAL, PORTFOLIO_CONFIG)
        except Exception as e:
          print(f'❌ 發送睡前持倉報告失敗: {e}')
        mark_report_sent(_report_state, 'sleep', now)
        save_json(_report_state, REPORT_STATE_PATH)
      # ── 盤後自選股自動選股觸發（V4.35；D1 13:36~13:55，D2 08:05~08:39 補跑）──
      # 程式自己在容器內選股、自己改 .env、自己發 TG；選股與 .env 變更全部交給已驗證的
      # `scripts/monthly_selfselect_run.py`（含步驟 0 補資料、基準日把關、絕不刪已持倉）。
      # 生效點＝隔天 08:40 熱重載；D2 的買進由既有 SELFSELECT_EXEC_MODE=immediate 負責。
      if os.getenv('SELFSELECT_AUTO', '0') == '1':
          try:
              from core.selfselect_scheduler import run_if_due as _ss_run_if_due
              _ss = _ss_run_if_due(now=now, notify=send_telegram_message)
              if _ss.get('ran'):
                  _ss_ok = '✅' if _ss.get('ok') else '⚠️'
                  print(f"{_ss_ok} 自選股自動選股（{_ss.get('day')}）：{_ss.get('summary') or _ss.get('tail')}")
                  if _ss.get('ok'):
                      # 補跑若拖過 08:40，熱重載已經跑過 ⇒ 清掉標記，讓下一次迴圈立刻重載新 .env
                      globals()['_hot_reload_date'] = None
          except Exception as _e:
              print(f'⚠️ 自選股自動選股異常（不影響其他策略）：{_e}')
      time.sleep(60)
      continue
    # ── 每日一次：bollinger/vwap/ma_cross 買入不足主動補足（方案 B，2026-09-01）──
    # 回測假設全額成交；實盤部分成交/資金不足會導致倉位不足 → 每日主動補到目標
    # （不看策略訊號）；逾 3 交易日仍未滿 → TG 通知（每日一次去重）
    # ⚠️ 停泊（park_idle_if_due）已於 2026-11-05 移到交易日主區塊內（見上方），
    #    原因是舊位置被兩個 `continue` 分支擋住、交易日永遠到不了。

    # 補買僅盤中執行（09:00-13:30）；逾時通知任何時段都檢查
    try:
      _buy_offset = float(os.getenv('BUY_AMOUNT_OFFSET', '0.02'))
      if _buy_offset > 0:
        _market_open_now = is_tday and (h > 9 or (h == 9 and m >= 0)) and (h < 13 or (h == 13 and m <= 30))
        _last_buy_map = {}
        if os.path.exists('logs/performance.csv'):
          import csv as _c
          with open('logs/performance.csv', newline='', encoding='utf-8') as _f:
            for _row in _c.reader(_f):
              if len(_row) >= 6 and _row[5].upper() == 'BUY':
                _last_buy_map[_row[1]] = _row[0]
        for (symbol, cfg) in PORTFOLIO_CONFIG.items():
          sn = cfg['strategy']
          if sn in ('bollinger', 'vwap', 'ma_cross'):
            held = holdings.get(symbol, 0)
            try:
              px = broker.get_current_price(symbol)
            except Exception:
              px = 0
            if px > 0:
              _alloc_pct = float(cfg.get('alloc', 12.5))
              _target = int((TOTAL_CAPITAL * _alloc_pct / 100.0) / px)
              # v3.27: 僅補「已有持股但不足」；空倉（held=0）等策略訊號不建倉
              from core.live_utils import calc_topup_need as _calc_need
              _need = _calc_need(held, _target, _buy_offset, _market_open_now)
              if _need > 0:
                  # 2026-11-09（v1.1.37）：額度 ≠ 現金（見 fit_cash）——補足股數同樣受可用現金限制
                  _need = fit_cash(symbol, _need, px)
              if _need > 0:
                  # 主動補足到目標（不看訊號）
                  try:
                    if USE_REAL_API:
                      _order_ret = place_buy(symbol, _need, '買入補足需要資金')
                      _filled = resolve_fill(broker, symbol, 'buy', _order_ret, _need)
                      if _filled is not None and _filled <= 0:
                        _order_fail_notified = notify_order_failure(
                            symbol, f'補足未成交（{_order_ret}）', _order_fail_notified,
                            today_str, send_telegram_message, action='買入補足')
                        _filled = 0
                      else:
                        # 2026-11-06：成交查不到時也要用 provider 回報的實際送單股數
                        # （整股規則會把 4,122 改成 4,000）——同一般買進／停泊買進的口徑。
                        _filled = (_filled if _filled is not None
                                   else reconcile_order_qty(_need, _order_ret))
                        if int(_filled or 0) != int(_need):
                          print(f'⚠️ {symbol} 補足記帳股數依實際送單：{int(_need)} → {int(_filled)} 股')
                    else:
                      _order_ret = place_buy(symbol, _need, '買入補足需要資金')
                      _filled = _need
                    if _filled > 0:
                      # 2026-11-03：記帳價改用 provider 回報的實際送單價（同孤兒清倉／策略訊號）
                      px = book_price(_order_ret, px, f'{symbol} 補足')
                      holdings[symbol] = held + _filled
                      save_holdings(holdings)
                      rm.log_trade(symbol, 1, px, _filled, exclude_from_daily=True)
                      # v3.29: 補買同步更新分帳本（否則 avg_cost 失真/資金上限失效）
                      from core.live_utils import add_stock_allocation as _add_alloc
                      _add_alloc(stock_alloc, symbol, px * _filled, _filled)
                      save_stock_allocation(stock_alloc)
                      print(f'📥 {symbol} 買入補足 {_filled} 股 @ {px:.2f}（{held}→{held+_filled}，目標 {_target}）')
                  except Exception as _e:
                    print(f'⚠️ {symbol} 買入補足失敗: {_e}')
                    _order_fail_notified = notify_order_failure(
                        symbol, _e, _order_fail_notified, today_str,
                        send_telegram_message, action='買入補足')
              # 逾 3 交易日仍未滿 → TG 通知
              from core.live_utils import check_buy_fill_shortfall
              _buy_fill_notified = check_buy_fill_shortfall(
                  symbol, holdings.get(symbol, 0), _target, _buy_offset,
                  _last_buy_map.get(symbol), now.date(),
                  send_telegram_message, _buy_fill_notified, label=sn.upper())
    except Exception as _e:
      print(f'⚠️ 買入補足檢查異常: {_e}')
    next_open = _next_market_open(now)
    sleep_seconds = min((next_open - now).total_seconds(), 3600)
    if (sleep_seconds >= 3600):
      # 收盤/睡前報告**補發路徑**（交易日、同日收盤後只發一次、狀態落地）：
      # 正常情況兩份都在 13:45 那一輪發完（見上方）；這裡負責盤後崩潰後重啟的補發
      # （2026-09-10 主迴圈卡死 8 小時那類）。
      _report_changed = False
      if report_due(now, _report_state, 'daily_report', trading_day=is_tday):
        send_daily_report(pd, date)
        send_closing_summary(pd, APP_VERSION, TOTAL_CAPITAL, PORTFOLIO_CONFIG)
        try:
          from scripts.generate_dashboard import main as gen_dash
          gen_dash()
        except Exception as e:
          print(f'❌ 產生儀表板失敗: {e}')
        mark_report_sent(_report_state, 'daily_report', now)
        _report_changed = True
      if report_due(now, _report_state, 'sleep', trading_day=is_tday):
        try:
          send_sleep_notification(pd, APP_VERSION, next_open, TOTAL_CAPITAL, PORTFOLIO_CONFIG)
        except Exception as e:
          print(f'❌ 發送睡前持倉報告失敗: {e}')
        mark_report_sent(_report_state, 'sleep', now)
        _report_changed = True
      if _report_changed:
        save_json(_report_state, REPORT_STATE_PATH)
      # 只在「下次開盤時間」改變時印一次（原本每輪都印 ⇒ docker logs --tail 被同一行洗掉）
      if should_emit_idle_notice(_idle_notice_state, next_open.strftime('%Y-%m-%d %H:%M')):
        print(f"💤 非交易時段，下次開盤 {next_open.strftime('%m/%d %H:%M')}，休眠中...")
    _sleep_total = max(sleep_seconds, 60)
    _elapsed = 0.0
    while _elapsed < _sleep_total:
      _chunk = min(30.0, _sleep_total - _elapsed)
      time.sleep(_chunk)
      _elapsed += _chunk
      _HEARTBEAT['ts'] = time.time()   # 睡眠期間也更新心跳（否則 watchdog 會誤判「卡住」）
      # 睡眠期間也檢查 `.env` 指紋（V4.38）：休市／盤後的一輪可長達 1 小時，若只在迴圈開頭檢查，
      # 「改完 .env 立即生效」會退化成「最慢一小時」——使用者要的是**當天 13:25 前改就當天生效**，
      # 而盤前（08:00–09:00）與盤後正是最常改 `.env` 的時段。偵測到變更就中斷休眠、立刻回迴圈開頭套用。
      _fp_sleep = env_fingerprint()
      if _fp_sleep and _env_fp_seen['v'] and (_fp_sleep != _env_fp_seen['v']):
        print(f"📥 偵測到 .env 內容變更（{_env_fp_seen['v'][:8]} → {_fp_sleep[:8]}）⇒ 中斷休眠立即套用")
        break
if (__name__ == '__main__'):
  from dotenv import load_dotenv
  load_dotenv()
  main()