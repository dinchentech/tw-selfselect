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
        from data.esun_provider import EsunProvider
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
