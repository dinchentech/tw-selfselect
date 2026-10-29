# backtest_finmind.py — FinMind 資料源回測（function-based 策略＋自訂策略比較）
"""
模式二：同一檔股票、多策略橫向比較（FinMind 台灣在地資料庫）。

用法：
    # 逐年比較（每個年度各自從 1/1 開始，指標各自暖機）
    python backtest_finmind.py --symbol 2454 --years 2022 2025

    # 單一區間（舊行為）
    python backtest_finmind.py --symbol 2330 --start 2023-01-01

口徑（`compute_backtest`）：
    - 初始資本 500,000；**單一部位**：空手才買（買訊在持倉時忽略，與實盤「滿倉不買」一致）
    - 每次買訊投入「當下現金」的 100%；賣訊全數出清；期末仍有持股則以最後一根收盤平倉（計入賣出）
    - 手續費：買 0.1425%、賣 0.4425%（含證交稅）；價格為 FinMind 原始價（未還原權息）
"""
import argparse
import os
from datetime import datetime

import pandas as pd
from FinMind.data import DataLoader

from core.config_loader import load_portfolio_config, get_strategy_params

# 匯入 function-based 策略（與 backtest.py 同一套）
from strategies.vwap_deviation import vwap_deviation_strategy
from strategies.ma_cross import ma_cross_strategy
from strategies.bollinger import bollinger_reverse_strategy
from strategies.breakout import breakout_strategy

try:
    from user_strategies import weekly_kd_golden_cross
except ImportError:  # pragma: no cover - 沒有 user_strategies.py 時仍可比較 4 個內建策略
    weekly_kd_golden_cross = None


def _buy_and_hold(df: pd.DataFrame) -> pd.DataFrame:
    """買進持有（基準線）：第一根 K 進場、期末平倉。"""
    out = df.copy()
    signal = pd.Series(0, index=out.index)
    if len(signal) > 0:
        signal.iloc[0] = 1
    out['signal'] = signal.astype(int)
    return out


STRATEGIES = {
    "VWAP 偏離": {
        "func": vwap_deviation_strategy,
        "params": {"sigma_mult": 1.5, "rsi_period": 5},
    },
    "均線交叉": {
        "func": ma_cross_strategy,
        "params": {"fast_period": 9, "slow_period": 21, "atr_threshold": 0.005},
    },
    "布林通道": {
        "func": bollinger_reverse_strategy,
        "params": {"window": 20, "std_dev": 2.0, "rsi_period": 5},
    },
    "突破交易": {
        "func": breakout_strategy,
        "params": {"lookback": 25, "atr_period": 14, "atr_threshold": 0.02},
    },
}

# 自訂策略（g1_strategy_2 週 KD）；有 user_strategies.py 才掛上
if weekly_kd_golden_cross is not None:
    STRATEGIES["週KD（9/30/3）"] = {
        "func": weekly_kd_golden_cross,
        "params": {"k_period": 9, "k_threshold": 30, "d_period": 3},
    }
    STRATEGIES["週KD（12/25/5，調參）"] = {
        "func": weekly_kd_golden_cross,
        "params": {"k_period": 12, "k_threshold": 25, "d_period": 5},
    }

# 基準線放最後
STRATEGIES["買進持有（全額）"] = {"func": _buy_and_hold, "params": {}}

# 顯示名 → PC_ 設定裡的策略內部名（有 PC_<代號> 時可覆蓋參數）
_STRAT_NAME_MAP = {
    "VWAP 偏離": "vwap",
    "均線交叉": "ma_cross",
    "布林通道": "bollinger",
    "突破交易": "breakout",
    "週KD（9/30/3）": "g1_strategy_2",
    "週KD（12/25/5，調參）": "g1_strategy_2",
}


def compute_backtest(df: pd.DataFrame, buy_cost=0.001425, sell_cost=0.004425,
                     initial_capital=500_000, invest_ratio=1.0) -> dict:
    """從 signal 計算回測績效（買訊投入現金 50%、賣訊全出、期末平倉）。"""
    df = df.copy().reset_index(drop=True)
    cash = float(initial_capital)
    hold = 0.0
    total_buy_cost = 0.0  # 累計買進成本（含手續費）
    buys = sells = wins = 0

    # 單一部位：空手才買（滿倉不重複買，與實盤一致）、持倉遇賣訊全出
    for i in range(len(df)):
        signal = int(df.loc[i, "signal"])
        price = float(df.loc[i, "close"])

        if signal == 1 and hold == 0 and cash > 0:
            shares = int(cash * invest_ratio / (price * (1 + buy_cost)))
            if shares > 0:
                cost = shares * price * (1 + buy_cost)
                cash -= cost
                total_buy_cost += cost
                hold += shares
                buys += 1

        elif signal == -1 and hold > 0:
            proceeds = hold * price * (1 - sell_cost)
            if proceeds > total_buy_cost:
                wins += 1
            cash += proceeds
            total_buy_cost = 0.0
            hold = 0.0
            sells += 1

    if hold > 0 and len(df) > 0:
        price = float(df.loc[len(df) - 1, "close"])
        proceeds = hold * price * (1 - sell_cost)
        if proceeds > total_buy_cost:
            wins += 1
        cash += proceeds
        hold = 0.0
        sells += 1

    return {
        "final_equity": cash,
        "buys": buys,
        "sells": sells,
        "win_rate": (wins / sells) if sells > 0 else 0.0,
        "total_return": (cash - initial_capital) / initial_capital,
    }


def load_finmind_prices(symbol: str, start_date: str, end_date: str = None) -> pd.DataFrame:
    """FinMind 日線 → 統一口徑 OHLCV（DatetimeIndex）。抓不到回空 DataFrame。"""
    token = os.getenv("FINMIND_API_TOKEN")
    if not token:
        print("❌ 未設定 FINMIND_API_TOKEN（見 .env／.env.example.txt），無法取得 FinMind 資料")
        return pd.DataFrame()

    loader = DataLoader()
    loader.login_by_token(api_token=token)
    raw = loader.taiwan_stock_daily(stock_id=str(symbol), start_date=start_date)
    if raw is None or raw.empty:
        print(f"❌ {symbol}: FinMind 無資料（{start_date} 起）")
        return pd.DataFrame()

    df = pd.DataFrame({
        "date": pd.to_datetime(raw["date"]),
        "open": raw["open"].astype(float),
        "high": raw["max"].astype(float),
        "low": raw["min"].astype(float),
        "close": raw["close"].astype(float),
        "volume": raw["Trading_Volume"].astype(float),
    }).set_index("date").sort_index()
    if end_date:
        df = df.loc[:end_date]
    return df


def _pc_param_overrides(symbol: str) -> dict:
    """回傳 {內部策略名: 參數}（該檔在 PC_ 有設定時才覆蓋）。"""
    pc_config = load_portfolio_config()
    overrides = {}
    sym_cfg = pc_config.get(symbol)
    if not sym_cfg:
        return overrides
    for internal in ("vwap", "ma_cross", "bollinger", "breakout", "g1_strategy_2"):
        params = get_strategy_params(sym_cfg, internal)
        if params:
            overrides[internal] = params
    if overrides:
        print(f"📋 偵測到 {symbol} 的 PC_ 設定，將覆蓋對應策略參數: {overrides}")
    return overrides


def _run_strategies(df: pd.DataFrame, label: str, overrides: dict) -> dict:
    """對一個價格區間跑全部策略，回傳 {策略顯示名: metrics}。"""
    out = {}
    for name, cfg in STRATEGIES.items():
        params = dict(cfg["params"])
        internal = _STRAT_NAME_MAP.get(name)
        if internal and internal in overrides:
            params.update(overrides[internal])
        try:
            signal_df = cfg["func"](df.copy(), **params)
            out[name] = compute_backtest(signal_df)
        except Exception as e:  # 單一策略壞掉不擋其他策略
            print(f"❌ {label} {name} 策略錯誤: {e}")
            out[name] = None
    return out


def _print_table(symbol: str, windows: list, per_window: dict, initial_capital=500_000) -> None:
    """印出 markdown 比較表：每個區間一組「損益／買賣次數」，最後一欄為合計損益。"""
    headers = ["策略"]
    for label, _, _ in windows:
        headers += [f"{label} 損益", f"{label} 買/賣"]
    headers.append("合計損益")
    print("\n| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")

    for name in STRATEGIES:
        row = [name]
        total = 0.0
        for label, _, _ in windows:
            m = per_window.get(label, {}).get(name)
            if m is None:
                row += ["—", "—"]
                continue
            profit = m["final_equity"] - initial_capital
            total += profit
            row.append(f"{profit:+,.0f}（{m['total_return']:+.1%}）")
            row.append(f"{m['buys']}/{m['sells']}")
        row.append(f"{total:+,.0f}")
        print("| " + " | ".join(row) + " |")
    print()


def run_comparison(symbol: str, windows: list, save_csv: bool = True) -> dict:
    """多策略比較。windows = [(標籤, 起日, 迄日), ...]（同一次抓資料後各自切片）。"""
    start = min(w[1] for w in windows)
    end = max(w[2] for w in windows) if windows[0][2] else None
    print(f"📊 FinMind 多策略回測：{symbol}（資料 {start} ~ {end or '最新'}）")
    print("   口徑：資本 500,000、單一部位（空手才買、滿倉不重複買）、賣訊全出、期末平倉；"
          "買 0.1425%／賣 0.4425%（含證交稅）")

    prices = load_finmind_prices(symbol, start, end)
    if prices.empty:
        return {}

    overrides = _pc_param_overrides(symbol)
    per_window = {}
    for label, win_start, win_end in windows:
        df = prices.loc[win_start:win_end]
        if df.empty:
            print(f"⚠️  {label}: 區間內無資料，跳過")
            per_window[label] = {}
            continue
        per_window[label] = _run_strategies(df, label, overrides)

    _print_table(symbol, windows, per_window)

    if save_csv:
        rows = []
        for label, _, _ in windows:
            for name, m in (per_window.get(label) or {}).items():
                if m is None:
                    continue
                rows.append({
                    "symbol": symbol, "window": label, "strategy": name,
                    "profit": round(m["final_equity"] - 500_000, 2),
                    "return_pct": round(m["total_return"] * 100, 2),
                    "buys": m["buys"], "sells": m["sells"],
                    "win_rate": round(m["win_rate"], 4),
                })
        if rows:
            os.makedirs("results", exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"results/finmind_compare_{symbol}_{stamp}.csv"
            pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
            print(f"✅ 比較結果已匯出: {path}")

    return per_window


def run_finmind_backtest(symbol: str = "2330", start_date: str = "2023-01-01", end_date: str = None) -> dict:
    """單一區間比較（舊介面；等於 run_comparison 只有一個視窗）。"""
    label = f"{start_date}~{end_date or '最新'}"
    return run_comparison(symbol, [(label, start_date, end_date)])


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="FinMind 多策略回測（4 個內建策略＋週KD＋買進持有）")
    ap.add_argument("--symbol", default="2330", help="股票代號（預設 2330）")
    ap.add_argument("--start", default=None, help="單一區間起日（YYYY-MM-DD）")
    ap.add_argument("--end", default=None, help="單一區間迄日（YYYY-MM-DD，預設最新）")
    ap.add_argument("--years", type=int, nargs="+", default=None,
                    help="逐年比較，例如 --years 2022 2025")
    ap.add_argument("--no-csv", dest="csv", action="store_false", default=True,
                    help="不輸出 results/ 的 CSV")
    return ap.parse_args(argv)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    args = _parse_args()

    if args.years:
        windows = [(str(y), f"{y}-01-01", f"{y}-12-31") for y in args.years]
    else:
        start = args.start or "2023-01-01"
        windows = [(f"{start}~{args.end or '最新'}", start, args.end)]

    run_comparison(args.symbol, windows, save_csv=args.csv)
