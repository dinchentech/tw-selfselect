# TW SelfSelect Trader — 台股「自選股（每月換股）」自動交易主程式
# 由 tw-autotrader 拆出：只保留自選股腿（全輪替／法人動能兩條腿已移除）
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
from utils.telegram import send_trade_alert, send_telegram_message
from core.risk_manager import RiskManager
from core.live_state import load_json, save_json, load_monthly_budget, save_monthly_budget, check_monthly_budget, update_monthly_spending, load_stock_allocation, save_stock_allocation, ensure_symbol_ledgers, check_stock_cap, update_stock_allocation, load_holdings, save_holdings, update_holdings, load_last_trade_times, save_last_trade_times, load_daily_trades, save_daily_trades, load_processed_capital, save_processed_capital
from core.live_notifications import send_line_notification, notify_all, send_daily_report, send_closing_summary, send_sleep_notification, send_startup_holdings
from core.live_utils import get_next_market_open as _next_market_open, resolve_fill, reconcile_order_qty, order_fill_price, load_unknown_orders, record_unknown_order, clear_unknown_order, unknown_order_blocks_buy, broker_holding_qty, sell_with_fill_check, notify_order_failure, sell_stock_allocation, report_due, mark_report_sent, REPORT_STATE_PATH, is_trading_day, close_order_window_open, should_emit_idle_notice, full_position_topup, intraday_trade_window
import sys

# ── 網路呼叫預設 timeout（避免主迴圈卡死）──────────────────────────────
# 根因：E.Sun / FinMind 兩支 SDK 內部的 requests 呼叫「沒有 timeout」→ 一旦連線半開
# 會永久阻塞整個主迴圈（2026-09-10 曾卡死 8 小時、整段交易時段無輸出）。
# 這裡統一 monkey-patch requests，未指定 timeout 的一律補上 NET_TIMEOUT_SEC 秒上限。
_NET_TIMEOUT_SEC = float(os.getenv('NET_TIMEOUT_SEC', '30'))
if _NET_TIMEOUT_SEC > 0:
  _orig_session_request = requests.sessions.Session.request
  def _session_request_with_timeout(self, method, url, **kwargs):
    if kwargs.get('timeout') is None:
      kwargs['timeout'] = _NET_TIMEOUT_SEC
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
📈 監控中: ''' + ', '.join((f"{s}[{c['strategy']}]" for (s, c) in PORTFOLIO_CONFIG.items())))
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
  lccd = None
  pcap = load_processed_capital()
  (daily_symbol_trades, daily_symbol_trades_date) = load_daily_trades()
  if (daily_symbol_trades_date is None):
    daily_symbol_trades = {}
  _order_fail_notified = {}   # {symbol: 'YYYY-MM-DD'} 下單失敗 TG 警示去重
  _risk_notified = {}         # {symbol: 'YYYY-MM-DD'} 風險控管攔截 TG 警示去重（每日一次）
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
日期: {date_str}
{source}: NT${amount:,.0f}
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
          try:
            broker.place_order(symbol, 'buy', buy_shares)
            rm.log_trade(symbol, 1, px, buy_shares, exclude_from_daily=True)
            holdings[symbol] = (holdings.get(symbol, 0) + buy_shares)
            save_holdings(holdings)
            print(f'📥 {symbol} keep_wait 加碼 {buy_shares} 股 @ {px:.0f}')
            send_telegram_message(f'📥 *{symbol}* keep_wait 加碼 {buy_shares} 股 @ {px:.0f}')
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
            f"🚨 *帳務不一致*\n{_ab['summary']}\n"
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
          _filled, _order_fail_notified = sell_with_fill_check(broker, old_sym, old_shares, _order_fail_notified, today_str, send_telegram_message, '清倉')
          if _filled <= 0:
            continue
          old_shares = _filled
          rm.log_trade(old_sym, -1, old_px, old_shares, exclude_from_daily=True)
          send_trade_alert(old_sym, 'SELL', old_px, old_shares, 'CLEANUP')
          print(f'🧹 清倉 {old_sym} {old_shares} 股 @ {old_px:.0f}（不再在 PORTFOLIO_CONFIG 中）')
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
                # ── 多層停利 (tp_tiers) ──
                fired_tiers = trk.setdefault('tp_tiers_fired', [])
                tier_triggered = None
                for tier_idx, tier in enumerate(kw_tp_tiers):
                  if tier_idx in fired_tiers:
                    continue
                  tier_pct = float(tier.get('pct', 15))
                  if profit_pct >= tier_pct:
                    tier_triggered = (tier_idx, tier)
                    break
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
                    print(f'📈 {symbol} 停利 T{tier_idx+1}: +{profit_pct:.1f}% >= +{tier["pct"]}% 賣出 {sell_qty}/{owned} 股 ({tier["ratio"]}%)')
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
                    msg = f'''📈 *{symbol}* 漲幅 +{profit_pct:.1f}% 已達目標 {kw_tp_pct:.0f}%
目前持有 {owned} 股，成本均價 {avg_cost:.0f}
是否手動獲利了結？'''
                    send_telegram_message(msg)
                    print(f'📢 {symbol} 漲 {profit_pct:.1f}% 達標，已通知使用者')
                else:
                  signal = 0
              if (not take_profit) and (signal == 0):
                # ── DCA 加碼檢查 ──
                if ((drop_pct >= kw_drop_pct) and (trk['buy_count'] < kw_max_add)):
                  if (kw_max_entry_price > 0) and (px > kw_max_entry_price):
                    print(f'⏸️  {symbol} DCA 跳過: 價格 {px:.2f} > 上限 {kw_max_entry_price:.2f}')
                    signal = 0
                  else:
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
            (allowed, reject_reason) = rm.check_trade_allowed(symbol, signal, px, total_buy=total_buy_all, total_sell=total_sell_all)
            if (not allowed):
              if (_risk_notified.get(symbol) != today_str):
                _risk_notified[symbol] = today_str
                send_telegram_message(f'🛑 *{symbol}* 風險控管攔截（{reject_reason}）')
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
                    send_telegram_message(f'⏸️ *{symbol}* 今日曾下單逾時（結果未明），今日不再買入')
                  continue
                _bq = broker_holding_qty(broker, symbol)
                _had = holdings.get(symbol, 0)
                if _bq is None:
                  print(f'⚠️ {symbol} 有「結果未明」紀錄但查不到券商庫存 ⇒ 本次不買（保守）')
                  if (_unknown_notified.get(symbol) != today_str):
                    _unknown_notified[symbol] = today_str
                    send_telegram_message(f'⚠️ *{symbol}* 先前委託結果未明且查不到券商庫存，請人工對帳'
                                          f'（docker exec tw_selfselect_bot python scripts/reconcile_broker_books.py）')
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
                  send_telegram_message(f'🧾 *{symbol}* 先前逾時委託已成交 {_delta} 股（@{px:.2f}）⇒ 已依券商庫存補記帳')
                else:
                  print(f'🧾 {symbol} 先前逾時委託未成交（券商庫存 {_bq} 股）⇒ 清掉未明紀錄')
                clear_unknown_order(symbol)
                continue
            if USE_REAL_API:
              order_result = broker.place_order(symbol, action.lower(), position_size)
              if ('error' in order_result):
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
                    send_telegram_message(f'🧾 *{symbol}* 下單逾時（結果未明）⇒ 今日不再買；明日開盤前會先向券商校正庫存')
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
                  # 主動補足到目標（不看訊號）
                  try:
                    if USE_REAL_API:
                      _order_ret = broker.place_order(symbol, 'buy', _need)
                      _filled = resolve_fill(broker, symbol, 'buy', _order_ret, _need)
                      if _filled is not None and _filled <= 0:
                        _order_fail_notified = notify_order_failure(
                            symbol, f'補足未成交（{_order_ret}）', _order_fail_notified,
                            today_str, send_telegram_message, action='買入補足')
                        _filled = 0
                      else:
                        _filled = _filled if _filled is not None else _need
                    else:
                      broker.place_order(symbol, 'buy', _need)
                      _filled = _need
                    if _filled > 0:
                      holdings[symbol] = held + _filled
                      save_holdings(holdings)
                      rm.log_trade(symbol, 1, px, _filled, exclude_from_daily=True)
                      # v3.29: 補買同步更新分帳本（否則 avg_cost 失真/資金上限失效）
                      from core.live_utils import add_stock_allocation as _add_alloc
                      _add_alloc(stock_alloc, symbol, px * _filled, _filled)
                      save_stock_allocation(stock_alloc)
                      print(f'📥 {symbol} 買入補足 {_filled} 股 @ {px:.0f}（{held}→{held+_filled}，目標 {_target}）')
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