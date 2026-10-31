FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    YIFAZHILIAN_DB_PATH=/data/yifazhilian.db

WORKDIR /app

# 先装依赖，改代码时可复用这一层缓存
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/

RUN mkdir -p /data
VOLUME ["/data"]

WORKDIR /app/backend
EXPOSE 8000

# --proxy-headers：Caddy 在前面终止 TLS，用它转发的 X-Forwarded-* 还原真实协议和 IP
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
