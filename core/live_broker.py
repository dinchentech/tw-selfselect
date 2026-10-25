"""Broker factory — 依 BROKER / USE_REAL_API env var 建立對應 broker 實例"""

import os


def create_broker():
    """
    讀取環境變數，回傳 broker 實例：
      BROKER=esun  → EsunProvider（強制 USE_REAL_API=true）
      BROKER=kgi + USE_REAL_API=true  → KGIRealAPI
      BROKER=kgi + USE_REAL_API=false → KGIMockAPI（預設）
    """
    broker_type = os.getenv("BROKER", "kgi").lower()
    use_real = os.getenv("USE_REAL_API", "false").lower() == "true"

    if broker_type == "esun":
        try:
            from data.esun_provider import EsunProvider
        except ModuleNotFoundError as e:      # 玉山 SDK 不在 PyPI，需自行放置 whl 安裝
            raise RuntimeError(
                "BROKER=esun 需要玉山證券 SDK（esun_marketdata / esun_trade），目前找不到：\n"
                f"  {e}\n"
                "  請向玉山證券取得 whl，放進 esun_sdk/ 後執行：\n"
                "    pip install esun_sdk/*.whl\n"
                "  只想先跑回測／選股：把 .env 的 BROKER 改成 kgi 或改用 scripts/ 下的工具。"
            ) from e
        return EsunProvider()
    elif broker_type == "kgi":
        if use_real:
            from data.kgi_real import KGIRealAPI
            return KGIRealAPI()
        else:
            from data.kgi_mock import KGIMockAPI
            return KGIMockAPI()
    else:
        raise ValueError(f"未知的 BROKER: {broker_type}（支援: kgi, esun）")
