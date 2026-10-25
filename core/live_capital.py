"""資金管理 — 資本注入、獲利滾入 keep_wait 執行"""

import os
import json
from pathlib import Path
from datetime import date


def read_capital_file(filepath: str = "capital.txt") -> list:
    """
    讀取 capital.txt，回傳 [(date_str, amount), ...]
    格式: 金額, YYYY/MM/DD  # comment
    """
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "," in line:
                    parts = line.split(",", 1)
                    amount_str = parts[0].strip()
                    date_part = parts[1].strip()
                    if "#" in date_part:
                        date_part = date_part.split("#")[0].strip()
                    try:
                        amount = float(amount_str)
                        date_str = date_part.replace("/", "-")
                        entries.append((date_str, amount))
                    except (ValueError, IndexError):
                        continue
    except FileNotFoundError:
        pass
    return entries


def check_capital_injections(
    total_capital, lccd, pcap, broker, rm, holdings,
    portfolio_config, save_holdings, send_telegram_message
):
    """
    檢查 capital.txt 是否有新的資金注入／提領，處理並回傳更新後的狀態。
    
    回傳: (total_capital, lccd, pcap, holdings)
    """
    today = date.today().isoformat()
    if lccd == today:
        return total_capital, lccd, pcap, holdings
    lccd = today

    entries = read_capital_file()
    new_entries = [(d, a) for (d, a) in entries if f"{d}" not in pcap]
    if not new_entries:
        return total_capital, lccd, pcap, holdings

    for date_str, amount in new_entries:
        if amount == 0:
            continue
        old_capital = total_capital
        total_capital += amount
        pcap.append(date_str)
        source = "外部加碼" if amount > 0 else "資金提領"
        msg = (
            f"💰 *資金變動*\n"
            f"日期: {date_str}\n"
            f"{source}: NT${amount:,.0f}\n"
            f"資本: NT${old_capital:,.0f} → NT${total_capital:,.0f}"
        )
        send_telegram_message(msg)

        if amount > 0:
            for symbol, cfg in portfolio_config.items():
                if cfg.get("strategy") != "keep_wait":
                    continue
                alloc_pct = float(cfg.get("alloc", 20))
                share_amount = (total_capital * alloc_pct) / 100.0
                initial_buy_pct = float(cfg.get("initial_buy_pct", 0.7))
                buy_amount = share_amount * initial_buy_pct
                try:
                    px = broker.get_current_price(symbol)
                except Exception:
                    continue
                if px <= 0:
                    continue
                buy_shares = int(buy_amount / px)
                if buy_shares <= 0:
                    continue
                try:
                    broker.place_order(symbol, "buy", buy_shares)
                    rm.log_trade(symbol, 1, px, buy_shares)
                    holdings[symbol] = holdings.get(symbol, 0) + buy_shares
                    save_holdings(holdings)
                    send_telegram_message(f"📥 *{symbol}* keep_wait 加碼 {buy_shares} 股 @ {px:.0f}")
                except Exception as e:
                    print(f"❌ {symbol} keep_wait 加碼失敗: {e}")

    # 寫回已處理的資本注入紀錄
    _save_processed_capital(pcap)

    return total_capital, lccd, pcap, holdings


def _save_processed_capital(pcap):
    """儲存已處理的資本注入日期列表"""
    Path("logs/processed_capital.json").write_text(json.dumps(pcap, ensure_ascii=False), encoding="utf-8")


def execute_keep_wait_on_profit_roll(
    symbol, profit_amount, broker, rm, holdings,
    portfolio_config, save_holdings, send_telegram_message
):
    """
    獲利滾入時執行 keep_wait 加碼。
    將 profit_amount 依該標的 alloc 比例買入。
    """
    cfg = portfolio_config.get(symbol, {})
    if cfg.get("strategy") != "keep_wait":
        return

    alloc_pct = float(cfg.get("alloc", 20))
    share_amount = profit_amount * (alloc_pct / 100.0)
    initial_buy_pct = float(cfg.get("initial_buy_pct", 0.7))
    buy_amount = share_amount * initial_buy_pct

    try:
        px = broker.get_current_price(symbol)
    except Exception:
        return
    if px <= 0:
        return

    buy_shares = int(buy_amount / px)
    if buy_shares <= 0:
        return

    try:
        broker.place_order(symbol, "buy", buy_shares)
        rm.log_trade(symbol, 1, px, buy_shares)
        holdings[symbol] = holdings.get(symbol, 0) + buy_shares
        save_holdings(holdings)
        msg = f"📥 *{symbol}* keep_wait 獲利滾入加碼 {buy_shares} 股 @ {px:.0f}（獲利 NT${profit_amount:,.0f}）"
        send_telegram_message(msg)
        print(f"📥 {symbol} keep_wait 獲利滾入加碼 {buy_shares} 股 @ {px:.0f}")
    except Exception as e:
        print(f"❌ {symbol} keep_wait 獲利滾入加碼失敗: {e}")
