FROM python:3.11-slim
ENV TZ=Asia/Taipei
WORKDIR /app
# 安裝基本編譯工具 + 時區資料
RUN apt-get update && apt-get install -y build-essential tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --default-timeout=120 --no-cache-dir -r requirements.txt
# 複製程式碼（含 esun_sdk/：SDK 不在 PyPI，需自行向玉山證券取得 whl；
# 沒有 esun_sdk/ 或沒有 whl 也能建置，只是無法下單——回測與選股不受影響)
COPY . .
RUN if ls esun_sdk/*.whl >/dev/null 2>&1; then \
        pip install --default-timeout=600 --no-cache-dir esun_sdk/*.whl; \
    else \
        echo "⚠️ 未提供 esun_sdk/*.whl → 略過玉山 SDK（BROKER=esun 將無法下單）"; \
    fi
CMD ["python", "selfselect_trader.py"]
