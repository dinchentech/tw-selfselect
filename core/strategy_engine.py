# core/strategy_engine.py
import pandas as pd

class StrategyEngine:
    def __init__(self, strategy_func, **strategy_params):
        """
        策略執行引擎
        :param strategy_func: 策略函數（如 vwap_deviation_strategy）
        :param strategy_params: 策略參數（如 sigma_mult=1.5）
        """
        self.strategy_func = strategy_func
        self.params = strategy_params

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        執行策略並回傳帶有訊號的 DataFrame
        """
        result = self.strategy_func(df, **self.params)

        # 如果結果只有 'signal' 欄位，則合併原始 DataFrame
        if 'signal' in result.columns and set(result.columns) == {'signal'}:
            # 將訊號合併到原始 DataFrame
            df_copy = df.copy()
            df_copy['signal'] = result['signal']
            return df_copy

        # 否則直接返回結果
        return result