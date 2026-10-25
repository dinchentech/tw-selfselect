# utils/plotter.py
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime

def plot_vwap_chart(df: pd.DataFrame, symbol: str, signal: int, save_dir: str = "plots") -> str:
    """
    繪製 VWAP + RSI + 成交量 三子圖，並標註 VWAP 偏離百分比
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    # 取最近 60 分鐘資料
    df_plot = df.tail(60).copy()
    
    # 建立三子圖
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), 
                                        height_ratios=[3, 1, 1], 
                                        sharex=True)
    
    # ===== 上圖：價格與 VWAP =====
    ax1.plot(df_plot.index, df_plot['close'], label='Price', color='black', linewidth=1.5)
    
    if 'VWAP' in df_plot.columns:
        ax1.plot(df_plot.index, df_plot['VWAP'], label='VWAP', color='orange', linewidth=2)
        
        # 繪製上下軌
        if 'Std' in df_plot.columns:
            upper_band = df_plot['VWAP'] + 1.5 * df_plot['Std']
            lower_band = df_plot['VWAP'] - 1.5 * df_plot['Std']
            ax1.plot(df_plot.index, upper_band, label='Upper Band (+1.5σ)', color='red', linestyle='--')
            ax1.plot(df_plot.index, lower_band, label='Lower Band (-1.5σ)', color='green', linestyle='--')
    
    # 標記交易點並計算偏離百分比
    last_idx = df_plot.index[-1]
    last_price = df_plot['close'].iloc[-1]
    
    # 計算 VWAP 偏離百分比
    deviation_pct = None
    if 'VWAP' in df_plot.columns:
        last_vwap = df_plot['VWAP'].iloc[-1]
        if last_vwap != 0:
            deviation_pct = (last_price - last_vwap) / last_vwap * 100
    
    # 繪製交易點
    ax1.scatter(last_idx, last_price, 
                color='green' if signal == 1 else 'red', 
                s=100, 
                zorder=5,
                label=f'{"Buy" if signal == 1 else "Sell"} Signal')
    
    # 標註偏離百分比
    if deviation_pct is not None:
        # 決定文字位置（避免遮擋）
        y_offset = last_price * 0.005  # 0.5% 的價格偏移
        text_y = last_price + (y_offset if signal == 1 else -y_offset)
        color = 'green' if signal == 1 else 'red'
        ax1.annotate(f'{deviation_pct:+.1f}%', 
                    xy=(last_idx, last_price), 
                    xytext=(last_idx, text_y),
                    color=color, 
                    fontweight='bold',
                    ha='center',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))
    
    ax1.set_ylabel('Price')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f'{symbol} - VWAP Strategy ({datetime.now().strftime("%Y-%m-%d %H:%M")})')
    
    # ===== 中圖：RSI =====
    if 'RSI' in df_plot.columns:
        ax2.plot(df_plot.index, df_plot['RSI'], label='RSI(5)', color='purple', linewidth=1.5)
        ax2.axhline(70, color='red', linestyle='--', alpha=0.7, label='Overbought (70)')
        ax2.axhline(30, color='green', linestyle='--', alpha=0.7, label='Oversold (30)')
        ax2.axhline(50, color='gray', linestyle=':', alpha=0.5)
        
        # 標記交易點的 RSI 值
        last_rsi = df_plot['RSI'].iloc[-1]
        ax2.scatter(last_idx, last_rsi, 
                    color='green' if signal == 1 else 'red', 
                    s=80, 
                    zorder=5)
        
        ax2.set_ylabel('RSI')
        ax2.set_ylim(0, 100)
        ax2.legend(loc='upper left')
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'RSI data not available', 
                horizontalalignment='center', 
                verticalalignment='center',
                transform=ax2.transAxes)
        ax2.set_ylabel('RSI')
    
    # ===== 下圖：成交量 =====
    if 'volume' in df_plot.columns:
        # 設定成交量顏色（上漲綠、下跌紅）
        colors = ['green' if df_plot['close'].iloc[i] >= (df_plot['open'].iloc[i] if 'open' in df_plot.columns else df_plot['close'].iloc[i-1] if i>0 else df_plot['close'].iloc[i])
                  else 'red' for i in range(len(df_plot))]
        if 'open' not in df_plot.columns:
            colors = ['steelblue'] * len(df_plot)
            
        ax3.bar(df_plot.index, df_plot['volume'], color=colors, alpha=0.7, width=0.005)
        ax3.set_ylabel('Volume')
        ax3.grid(True, alpha=0.3)
        
        # 標記交易點的成交量
        last_volume = df_plot['volume'].iloc[-1]
        ax3.scatter(last_idx, last_volume, 
                    color='green' if signal == 1 else 'red', 
                    s=80, 
                    zorder=5)
    else:
        ax3.text(0.5, 0.5, 'Volume data not available', 
                horizontalalignment='center', 
                verticalalignment='center',
                transform=ax3.transAxes)
        ax3.set_ylabel('Volume')
    
    # 格式化 X 軸
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # 儲存檔案
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol}_{timestamp}_{'buy' if signal == 1 else 'sell'}.png"
    filepath = os.path.join(save_dir, filename)
    plt.savefig(filepath)
    plt.close()
    
    print(f"📊 已儲存圖表: {filepath}")
    return filepath