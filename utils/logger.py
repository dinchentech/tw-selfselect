import os
import pandas as pd
from datetime import datetime

LOG_FILE = "logs/performance.csv"

def init_log():
    if not os.path.exists("logs"):
        os.makedirs("logs")
    if not os.path.exists(LOG_FILE):
        pd.DataFrame(columns=["timestamp", "symbol", "signal", "price", "action"]).to_csv(LOG_FILE, index=False)

def log_trade(symbol: str, signal: int, price: float):
    init_log()
    action = "BUY" if signal == 1 else "SELL"
    new_row = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "signal": signal,
        "price": price,
        "action": action
    }
    df = pd.DataFrame([new_row])
    df.to_csv(LOG_FILE, mode='a', header=False, index=False)
    print(f"📝 已記錄交易: {action} {symbol} @ {price}")