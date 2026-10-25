"""
Keep & Wait Strategy — function-based version

此策略不做技術分析，signal 永遠為 0。
實際的 DCA 低接 / 停利邏輯完全由 simulate_portfolio.py 的 keep_wait 模組管理。

參數說明（透過 PC_<代號> 環境變數設定）：
  - initial_buy_pct: 首次買入佔分配資金的比例 (0-1)，預設 0.7 (70%)
    - 當資金到位時（首次分配、獲利滾入、使用者加碼），立即用此比例買入
    - 剩餘 30% 作為後續加碼的預備金
  - add_drop_pct: 加碼門檻 - 從平均成本下跌此百分比時加碼 (預設 5%)
  - add_shares: 每次加碼股數 (預設 6)
  - max_additions: 最多加碼次數 (預設 2)
  - tp_pct: 停利門檻 - 獲利達此百分比時停利 (預設 15%)
  - tp_sell_ratio: 停利時賣出比例 (預設 50%)
  - cooldown_days: 停利後冷卻天數 (預設 30)
"""

import pandas as pd


def keep_wait_strategy(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    Keep & Wait — signal 固定為 0。

    買賣時機由主程式根據 pyramid_tracker 狀態決定，
    此函式僅保留供未來擴充（如追蹤市場情緒）。
    """
    df = df.copy()
    df['signal'] = 0
    return df
