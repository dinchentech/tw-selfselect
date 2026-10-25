# backtest.py
import os
import argparse
import csv
import pandas as pd
from datetime import datetime
from config.symbols import ALL_SYMBOLS, get_yahoo_suffix
from core.strategy_engine import StrategyEngine
from data.yahoo_loader import load_historical_data
from core.config_loader import load_portfolio_config, get_strategy_params

# 匯入所有策略
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.breakout import breakout_strategy

# 載入用戶自訂策略
try:
    from user_strategies import USER_STRATEGY_MAP
    USER_STRATEGIES_AVAILABLE = True
    print(f"✅ 已載入 {len(USER_STRATEGY_MAP)} 個用戶自訂策略")
except ImportError:
    USER_STRATEGIES_AVAILABLE = False
    print("ℹ️  未找到 user_strategies.py，僅使用內建策略")
    USER_STRATEGY_MAP = {}

# 策略配置映射
STRATEGY_CONFIG = {
    "vwap": {
        "func": vwap_deviation_strategy,
        "params": {"sigma_mult": 1.5, "rsi_period": 5}
    },
    "ma_cross": {
        "func": ma_cross_strategy,
        "params": {"fast_period": 9, "slow_period": 21, "atr_threshold": 0.005}
    },
    "bollinger": {
        "func": bollinger_reverse_strategy,
        "params": {"window": 20, "std_dev": 2.0, "rsi_period": 5}
    },
    "breakout": {
        "func": breakout_strategy,
        "params": {"lookback": 25, "atr_period": 14, "atr_threshold": 0.02}
    },
    # 用戶自訂策略（預設參數）
    "g1_strategy_1": {
        # 2026-09-21 修正：這支是 user_strategies.price_band（價格區間低接高賣），
        # 參數是 buy_price/sell_price；舊寫 fast_period/slow_period 會被 **kwargs 吸收後
        # 靜默無效，且與 core/config_loader.STRATEGY_PARAM_KEYS 的登記不一致。
        "func": USER_STRATEGY_MAP.get("g1_strategy_1"),
        "params": {"buy_price": 250, "sell_price": 280}
    },
    "g1_strategy_2": {
        "func": USER_STRATEGY_MAP.get("g1_strategy_2"),
        "params": {"k_period": 9, "k_threshold": 30, "d_period": 3}
    },
    "g2_strategy_1": {
        "func": USER_STRATEGY_MAP.get("g2_strategy_1"),
        "params": {"lookback": 5, "threshold": 3}
    },
    "g2_strategy_2": {
        "func": USER_STRATEGY_MAP.get("g2_strategy_2"),
        "params": {"ma_period": 10, "volume_ma_period": 10, "volume_mult": 1.5}
    },
}

# 所有策略參數統一定義（用於 argparse）
# 跨策略共用參數只定義一次，避免 argparse 衝突
SHARED_PARAMS = {
    "rsi_period": {"default": 5, "type": int, "help": "RSI 計算週期"},
}

STRATEGY_PARAMS = {
    "vwap": {
        "sigma_mult": {"default": 1.5,  "type": float, "help": "VWAP 偏離倍數"},
        "rsi_period": SHARED_PARAMS["rsi_period"],
    },
    "ma_cross": {
        "fast_period": {"default": 9,   "type": int,   "help": "快線週期"},
        "slow_period": {"default": 21,  "type": int,   "help": "慢線週期"},
        "atr_threshold": {"default": 0.005, "type": float, "help": "ATR波動度門檻"},
    },
    "bollinger": {
        "window":   {"default": 20, "type": int,   "help": "布林通道計算週期"},
        "std_dev":  {"default": 2.0,"type": float, "help": "標準差倍數"},
        "rsi_period": SHARED_PARAMS["rsi_period"],
    },
    "breakout": {
        "lookback":    {"default": 25,  "type": int,   "help": "突破回溯期間"},
        "atr_period":  {"default": 14,  "type": int,   "help": "ATR 計算週期"},
        "atr_threshold": {"default": 0.02, "type": float, "help": "ATR 波動度門檻"},
    },
    # 用戶自訂策略參數
    "g1_strategy_1": {
        "buy_price":  {"default": 250, "type": int,   "help": "G1_S1(price_band): 買進觸發價（現價 ≤ 此價買）"},
        "sell_price": {"default": 280, "type": int,   "help": "G1_S1(price_band): 賣出觸發價（現價 ≥ 此價賣）"},
    },
    "g1_strategy_2": {
        "k_period":  {"default": 9, "type": int,   "help": "G1_S2: KD 週期"},
        "k_threshold": {"default": 30,"type": int,   "help": "G1_S2: K 值低檔門檻(低於此值才買)"},
        "d_period":   {"default": 3, "type": int,   "help": "G1_S2: KD 平滑期數"},
    },
    "g2_strategy_1": {
        "lookback":    {"default": 5,  "type": int,   "help": "G2_S1: 回看天數"},
        "threshold":   {"default": 3,  "type": float, "help": "G2_S1: 漲跌幅門檻（百分比）"},
    },
    "g2_strategy_2": {
        "ma_period":           {"default": 10, "type": int,   "help": "G2_S2: 價格均線週期"},
        "volume_ma_period":    {"default": 10, "type": int,   "help": "G2_S2: 成交量均線週期"},
        "volume_mult":         {"default": 1.5,"type": float, "help": "G2_S2: 成交量放大倍數"},
    },
}

def get_strategy_from_env_or_args():
    """從環境變數或命令列取得策略名稱與參數"""
    parser = argparse.ArgumentParser(
        description='TW AutoTrader - Backtest Mode',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "各策略可用參數：\n"
             "  vwap:          --sigma_mult, --rsi_period\n"
              "  ma_cross:      --fast_period, --slow_period, --atr_threshold\n"
             "  bollinger:     --window, --std_dev, --rsi_period\n"
             "  breakout:      --lookback, --atr_period\n"
             "  g1_strategy_1: --buy_price, --sell_price (價格區間低接高賣)\n"
             "  g1_strategy_2: --k_period, --k_threshold, --d_period (週KD黃金交叉)\n"
             "  g2_strategy_1: --lookback, --threshold (用戶自訂)\n"
             "  g2_strategy_2: --ma_period, --volume_ma_period, --volume_mult (用戶自訂)\n"
             "\n"
             "範例：\n"
             "  python backtest.py --strategy ma_cross --fast_period 5 --slow_period 30\n"
             "  python backtest.py --strategy g1_strategy_1 --buy_price 240 --sell_price 290\n"
             "  python backtest.py --strategy g1_strategy_2 --k_threshold 30 --d_period 3"
        )
    )
    parser.add_argument('--symbol', type=str, default=None,
                        help='股票代號（如有 PC_ 設定，自動採用其策略與參數）')
    parser.add_argument('--strategy', type=str, default=None,
                        help='選擇策略: vwap, ma_cross, bollinger, breakout')
    parser.add_argument('--start', type=str, default="2023-01-01",
                        help='回測開始日期 (YYYY-MM-DD)')

    # 動態加入所有策略參數（去重避免同名衝突）
    added_params = set()
    for sname, sparam in STRATEGY_PARAMS.items():
        for pname, popts in sparam.items():
            if pname not in added_params:
                parser.add_argument(
                    f'--{pname}',
                    type=popts["type"],
                    default=None,
                    help=f'{sname}: {popts["help"]} (預設 {popts["default"]})'
                )
                added_params.add(pname)

    args = parser.parse_args()

    # 從 PC_ 設定覆蓋預設策略與參數（當指定 --symbol 時）
    pc_config = load_portfolio_config()

    strategy_name = args.strategy or os.getenv("STRATEGY", "vwap")
    strategy_name = strategy_name.lower()

    if args.symbol and args.symbol in pc_config:
        sym_cfg = pc_config[args.symbol]
        pc_strategy = sym_cfg.get("strategy", strategy_name)
        if not args.strategy:
            strategy_name = pc_strategy
        # 以 PC_ 參數為基底，CLI 可覆蓋
        params = get_strategy_params(sym_cfg, strategy_name)
        if not params:
            params = STRATEGY_CONFIG.get(strategy_name, {}).get("params", {}).copy()
        print(f"📋 {args.symbol} 使用 PC_ 設定：策略={strategy_name}, 參數={params}")
    else:
        if strategy_name not in STRATEGY_CONFIG:
            # 檢查是否為用戶自訂策略
            if strategy_name in USER_STRATEGY_MAP:
                func = USER_STRATEGY_MAP[strategy_name]
                STRATEGY_CONFIG[strategy_name] = {
                    "func": func,
                    "params": {}
                }
                print(f"✅ 動態註冊用戶策略: {strategy_name}")
            else:
                print(f"❌ 無效策略: {strategy_name}，使用預設 'vwap'")
                strategy_name = "vwap"
        params = STRATEGY_CONFIG[strategy_name]["params"].copy()

    # CLI 參數覆蓋（所有策略通用）
    if strategy_name in STRATEGY_PARAMS:
        for pname in STRATEGY_PARAMS[strategy_name]:
            cli_val = getattr(args, pname, None)
            if cli_val is not None:
                params[pname] = cli_val

    return strategy_name, args.start, params, args.symbol

def calculate_performance(df: pd.DataFrame) -> dict:
    """計算策略績效"""
    if df.empty or (df['signal'] == 0).all():
        return {"total_trades": 0, "win_rate": 0.0, "total_return": 0.0}
    
    df = df.copy()
    df['next_close'] = df['close'].shift(-1)
    df['trade_return'] = 0.0
    
    # 買進訊號：下一根K的漲跌幅
    buy_mask = df['signal'] == 1
    if buy_mask.any():
        df.loc[buy_mask, 'trade_return'] = (df.loc[buy_mask, 'next_close'] - df.loc[buy_mask, 'close']) / df.loc[buy_mask, 'close']
    
    # 賣出訊號：出場（台股實務不做空，報酬為0）
    sell_mask = df['signal'] == -1
    if sell_mask.any():
        df.loc[sell_mask, 'trade_return'] = 0.0
    
    trades = df[df['signal'] != 0]
    if trades.empty:
        return {"total_trades": 0, "win_rate": 0.0, "total_return": 0.0}
    
    total_trades = len(trades)
    win_trades = (trades['trade_return'] > 0).sum()
    win_rate = win_trades / total_trades
    total_return = trades['trade_return'].sum()
    
    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "total_return": total_return
    }

def export_results_to_csv(results: list, strategy_name: str):
    """將回測結果匯出為 CSV"""
    if not results:
        print("⚠️ 無結果可匯出")
        return
    
    os.makedirs("results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results/backtest_results_{strategy_name}_{timestamp}.csv"
    
    fieldnames = [
        "symbol", 
        "total_trades", 
        "win_rate", 
        "total_return",
        "avg_return_per_trade"
    ]
    
    for r in results:
        r["avg_return_per_trade"] = r["return"] / r["trades"] if r["trades"] > 0 else 0.0
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {
                "symbol": r["symbol"],
                "total_trades": r["trades"],
                "win_rate": f"{r['win_rate']:.4f}",
                "total_return": f"{r['return']:.4f}",
                "avg_return_per_trade": f"{r['avg_return_per_trade']:.4f}"
            }
            writer.writerow(row)
    
    print(f"\n✅ 績效結果已匯出: {filename}")

def main():
    strategy_name, start_date, params, symbol_override = get_strategy_from_env_or_args()
    config = {"func": STRATEGY_CONFIG[strategy_name]["func"], "params": params}
    
    print(f"📊 開始回測 TW AutoTrader")
    print(f"🎯 使用策略: {strategy_name}")
    print(f"⚙️  策略參數: {config['params']}")
    print(f"📅 回測期間: {start_date} ~ 今日\n")
    
    engine = StrategyEngine(config["func"], **config["params"])
    
    # 若指定 --symbol 則只回測該檔，否則回測全部
    symbols_to_test = [symbol_override] if symbol_override else ALL_SYMBOLS
    
    all_results = []
    for symbol in symbols_to_test:
        yf_symbol = symbol + get_yahoo_suffix(symbol)
        print(f"  → 回測 {symbol} ({yf_symbol})...")
        
        df = load_historical_data(yf_symbol, start=start_date)
        if df.empty:
            print(f"    ⚠️  資料為空，跳過")
            continue
        
        # 確保 breakout 策略有 high/low 欄位
        if strategy_name == "breakout":
            required_cols = ['high', 'low']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                print(f"    ⚠️  缺少欄位 {missing_cols}，跳過")
                continue
        
        df = engine.run(df)
        perf = calculate_performance(df)
        
        if perf["total_trades"] > 0:
            result = {
                "symbol": symbol,
                "trades": perf["total_trades"],
                "win_rate": perf["win_rate"],
                "return": perf["total_return"]
            }
            all_results.append(result)
            print(f"    ✅ 交易次數: {perf['total_trades']}, 勝率: {perf['win_rate']:.1%}, 總報酬: {perf['total_return']:.2%}")
        else:
            print(f"    ❌ 無有效交易訊號")
    
    # 輸出總結與匯出
    if all_results:
        print("\n" + "="*60)
        print("📈 回測總結")
        print("="*60)
        for r in all_results:
            print(f"{r['symbol']:6} | 交易: {r['trades']:2d} 次 | 勝率: {r['win_rate']:5.1%} | 報酬: {r['return']:6.2%}")
        
        avg_win_rate = sum(r['win_rate'] for r in all_results) / len(all_results)
        avg_return = sum(r['return'] for r in all_results) / len(all_results)
        total_trades = sum(r['trades'] for r in all_results)
        print("-"*60)
        print(f"平均   | 交易: {total_trades:2d} 次 | 勝率: {avg_win_rate:5.1%} | 報酬: {avg_return:6.2%}")
        
        export_results_to_csv(all_results, strategy_name)
    else:
        print("\n❌ 所有標的均無有效交易訊號")

if __name__ == "__main__":
    main()