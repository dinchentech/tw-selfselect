# 台灣個股（上市）
STOCKS = ["2330", "2454", "2317", "2881", "2382", "2886"]

# 台灣指數型 ETF
INDEX_ETFS = ["0050", "0056", "00632R", "00646", "006208", "00878"]

# 所有監控標的
ALL_SYMBOLS = STOCKS + INDEX_ETFS

def get_yahoo_suffix(symbol: str) -> str:
    """自動判斷 Yahoo Finance 後綴"""
    if symbol == "00632R":
        return ".TWO"  # 上櫃
    return ".TW"       # 上市