FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=80 \
    YIFAZHILIAN_DB_PATH=/tmp/yifazhilian.db

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/

WORKDIR /app/backend

# 云托管按平台配置的端口探测健康检查，默认 80
EXPOSE 80

# 注意：容器没有持久磁盘，/tmp 里的 SQLite 会随重启丢失。
# 生产使用请改接云托管 MySQL 或对象存储（见 docs/cloudrun.md）。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
