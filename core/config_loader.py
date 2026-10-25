"""
core/config_loader.py — 共用設定載入器（V1.11）

從 PC_<代號> 環境變數載入個股策略設定 (JSON 格式)，
供 live_trader_multi.py 及所有回測檔案共用。
"""
import os
import json
from pathlib import Path

# 各策略函式可接受的參數名稱（用於從 per-stock config 過濾）
STRATEGY_PARAM_KEYS = {
    "bollinger": ["window", "std_dev", "rsi_period", "rsi_low", "rsi_high"],
    "vwap": ["sigma_mult", "rsi_period", "rsi_low", "rsi_high"],
    "ma_cross": ["fast_period", "slow_period", "atr_period", "atr_threshold"],
    "breakout": ["lookback", "atr_period", "atr_threshold"],
    "keep_wait": [],
    "auto": [],  # 自動感知策略：路由到 4 策略之一，無固定參數
    # 用戶自訂策略
    "g1_strategy_1": ["buy_price", "sell_price"],
    "g1_strategy_2": ["k_period", "k_threshold", "d_period"],
    "g2_strategy_1": ["lookback", "threshold"],
    "g2_strategy_2": ["ma_period", "volume_ma_period", "volume_mult"],
}

# 2026-09-21 移除死碼：KEEP_WAIT_PARAM_KEYS 與 get_keep_wait_params()
#   （全 repo 無呼叫者；simulate_portfolio.py 用自己的 KEEP_WAIT_PARAMS 常數，
#     live_trader_multi.py 直接讀 cfg.get('initial_shares')）


def load_portfolio_config() -> dict:
    """
    掃描環境變數中所有 PC_ 開頭的變數，解析 JSON 設定。
    回傳 { 股票代號: config_dict }

    同一標的被重複設定：dotenv 對重複 key
    採後者覆蓋，env 只保留最後一個條目。讀 .env 檔計算每個 symbol 的
    出現次數，把 alloc 乘以次數（如 12.5×2=25），讓買入端補足到合併
    目標權重——與回測「兩排程獨立帳戶各自滿倉」一致。

    ⚠️ 2026-10-17 修 bug（`.env` 是唯一真相）：compose 的 `env_file` 只在**建立容器時**
    注入 `os.environ`，之後從 `.env` 刪掉的 `PC_*` 仍留在 `os.environ`。原本只掃
    `os.environ` ⇒ 換股後舊代號變成「幽靈檔」（實例：換掉 6213 後仍監控 9 檔），
    而同名 key 重複出現時只會讀到最後一筆 ⇒ **可能買到早已淘汰的股票**。
    現在 `.env` 存在就以檔為準：檔內沒列出的代號一律排除（檔內一個 PC_ 都沒有 ⇒ 空組合）。
    `.env` 不存在時維持舊行為（純 `docker run -e PC_...` 部署）。
    """
    env_path = Path(os.getenv("DOTENV_PATH", ".env"))
    file_syms = None
    if env_path.exists():
        try:
            file_syms = set()
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("PC_") and "=" in stripped:
                    file_syms.add(stripped[3:].split("=", 1)[0].strip())
        except Exception:
            file_syms = None
    config = {}
    for key, val in os.environ.items():
        if key.startswith("PC_"):
            symbol = key[3:]  # 去掉 PC_ 前綴
            if (file_syms is not None) and (symbol not in file_syms):
                continue  # 容器殘留的舊 key（`.env` 已無）⇒ 不認
            try:
                parsed = json.loads(val)
                if "strategy" not in parsed:
                    print(f"⚠️  {symbol} 設定缺少 strategy 欄位，跳過")
                    continue
                config[symbol] = parsed
            except json.JSONDecodeError:
                print(f"⚠️  {symbol} 設定不是有效的 JSON，跳過: {val[:60]}...")
                continue
    try:
        counts = {}
        if file_syms is not None:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("PC_") and "=" in stripped:
                    sym = stripped[3:].split("=", 1)[0].strip()
                    counts[sym] = counts.get(sym, 0) + 1
        for sym, cnt in counts.items():
            if cnt > 1 and sym in config:
                config[sym] = dict(config[sym])
                config[sym]["alloc"] = float(config[sym].get("alloc", 0)) * cnt
    except Exception:
        pass
    return config


def get_strategy_params(cfg: dict, strategy: str) -> dict:
    """從 per-stock config 提取該策略認識的參數"""
    keys = STRATEGY_PARAM_KEYS.get(strategy, [])
    return {k: cfg[k] for k in keys if k in cfg}


def build_portfolio_from_env(fallback: bool = True) -> dict:
    """
    從 PC_ 環境變數建立投資組合設定，回傳格式：
    { symbol: { "strategy": ..., "params": {...}, "alloc": ..., ... } }
    
    若無 PC_ 設定且 fallback=True，回退到舊 PORTFOLIO 格式。
    """
    config = load_portfolio_config()
    if config:
        return config

    if fallback:
        raw = os.getenv("PORTFOLIO")
        if raw:
            fallback_config = {}
            for pair in raw.split(","):
                pair = pair.strip()
                if ":" not in pair:
                    continue
                symbol, strategy = pair.split(":", 1)
                fallback_config[symbol.strip()] = {"strategy": strategy.strip().lower()}
            return fallback_config

    return {}
