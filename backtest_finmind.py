# backtest_finmind.py — FinMind 資料源回測（function-based 策略）
import os
import numpy as np
import pandas as pd
from FinMind.data import DataLoader
from core.config_loader import load_portfolio_config, get_strategy_params

# 匯入 function-based 策略（與 backtest.py 同一套）
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.breakout import breakout_strategy

STRATEGIES = {
    "VWAP Deviation": {
        "func": vwap_deviation_strategy,
        "params": {"sigma_mult": 1.5, "rsi_period": 5},
    },
    "MA Cross": {
        "func": ma_cross_strategy,
        "params": {"fast_period": 9, "slow_period": 21, "atr_threshold": 0.005},
    },
    "Bollinger Reverse": {
        "func": bollinger_reverse_strategy,
        "params": {"window": 20, "std_dev": 2.0, "rsi_period": 5},
    },
    "Breakout": {
        "func": breakout_strategy,
        "params": {"lookback": 25, "atr_period": 14, "atr_threshold": 0.02},
    },
}


def compute_backtest(df: pd.DataFrame, buy_cost=0.001425, sell_cost=0.004425, initial_capital=500_000):
    """從 signal 計算回測績效（分批 Buy & Hold 模擬）"""
    df = df.copy().reset_index(drop=True)
    cash = float(initial_capital)
    hold = 0.0
    total_buy_cost = 0.0  # 累計買進成本（含手續費）
    total_txn = 0
    wins = 0
    losses = 0

    for i in range(len(df)):
        signal = int(df.loc[i, "signal"])
        price = float(df.loc[i, "close"])

        if signal == 1 and cash > 0:
            invest = cash * 0.5
            shares = int(invest / (price * (1 + buy_cost)))
            if shares > 0:
                cost = shares * price * (1 + buy_cost)
                cash -= cost
                total_buy_cost += cost
                hold += shares
                total_txn += 1

        elif signal == -1 and hold > 0:
            proceeds = hold * price * (1 - sell_cost)
            # 按買進成本比例計算這筆損益
            avg_cost_per_share = total_buy_cost / hold if hold > 0 else 0
            trade_cost = hold * avg_cost_per_share
            if proceeds > trade_cost:
                wins += 1
            else:
                losses += 1
            cash += proceeds
            total_buy_cost = 0
            hold = 0

    if hold > 0 and len(df) > 0:
        price = float(df.loc[len(df) - 1, "close"])
        proceeds = hold * price * (1 - sell_cost)
        avg_cost_per_share = total_buy_cost / hold if hold > 0 else 0
        trade_cost = hold * avg_cost_per_share
        if proceeds > trade_cost:
            wins += 1
        else:
            losses += 1
        cash += proceeds
        hold = 0

    total_trades = total_txn
    win_rate = wins / total_trades if total_trades > 0 else 0
    total_return = (cash - initial_capital) / initial_capital

    return cash, total_trades, win_rate, total_return


def run_finmind_backtest(symbol: str = "2330", start_date: str = "2023-01-01"):
    """使用 FinMind 資料執行回測"""
    print(f"📊 開始 FinMind 回測: {symbol}")

    # 取得資料
    data_loader = DataLoader()
    finmind_token = os.getenv("FINMIND_API_TOKEN")
    if finmind_token:
        data_loader.login_by_token(api_token=finmind_token)

    if finmind_token:
        raw = data_loader.taiwan_stock_daily(stock_id=symbol, start_date=start_date)
        if raw.empty:
            print(f"❌ {symbol} 無資料")
            return
        # 對應欄位：FinMind → 策略統一格式
        stock_price = pd.DataFrame({
            "date": pd.to_datetime(raw["date"]),
            "open": raw["open"].astype(float),
            "high": raw["max"].astype(float),
            "low": raw["min"].astype(float),
            "close": raw["close"].astype(float),
            "volume": raw["Trading_Volume"].astype(float),
        }).set_index("date").sort_index()
    else:
        print("⚠️ 未設定 FINMIND_API_TOKEN，使用模擬資料")
        dates = pd.date_range(start=start_date, periods=250, freq="D")
        np.random.seed(42)
        close = 650 + np.random.randn(250).cumsum()
        stock_price = pd.DataFrame({
            "open": close + np.random.randn(250) * 0.5,
            "high": close + np.abs(np.random.randn(250)) * 3 + 2,
            "low": close - np.abs(np.random.randn(250)) * 3 - 2,
            "close": close,
            "volume": np.random.randint(1_000_000, 5_000_000, 250),
        }, index=pd.date_range(start=start_date, periods=250, freq="D"))
        stock_price.index.name = "date"

    # 若有 PC_ 設定，覆蓋對應策略參數
    pc_config = load_portfolio_config()
    pc_params_cache = {}
    if symbol in pc_config:
        sym_cfg = pc_config[symbol]
        for pc_strat in ["vwap", "ma_cross", "bollinger", "breakout"]:
            pp = get_strategy_params(sym_cfg, pc_strat)
            if pp:
                pc_params_cache[pc_strat] = pp
        if pc_params_cache:
            print(f"📋 偵測到 {symbol} 的 PC_ 設定，將覆蓋對應策略參數: {pc_params_cache}")

    # 策略名稱映射表：顯示名 → 內部名
    STRAT_NAME_MAP = {
        "VWAP Deviation": "vwap",
        "MA Cross": "ma_cross",
        "Bollinger Reverse": "bollinger",
        "Breakout": "breakout",
    }

    # 執行各策略
    results = {}
    for name, cfg in STRATEGIES.items():
        params = dict(cfg["params"])
        internal_name = STRAT_NAME_MAP.get(name)
        if internal_name and internal_name in pc_params_cache:
            params.update(pc_params_cache[internal_name])
            print(f"  ⚙️  {name} 使用 PC_ 參數: {pc_params_cache[internal_name]}")
        try:
            df = cfg["func"](stock_price.copy(), **params)
            final_equity, total_txn, win_rate, avg_return = compute_backtest(df)
            results[name] = {
                "final_equity": round(final_equity, 2),
                "total_transactions": total_txn,
                "win_rate": round(win_rate, 4),
                "avg_return": round(avg_return, 4),
            }
            print(f"\n{name} 策略績效:")
            print(f"  最終權益: {final_equity:.2f}")
            print(f"  交易次數: {total_txn}")
            print(f"  勝率: {win_rate:.2%}")
            print(f"  平均報酬: {avg_return:.2%}")
        except Exception as e:
            print(f"❌ {name} 策略錯誤: {e}")
            results[name] = None

    return results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    run_finmind_backtest("2330", "2023-01-01")
