#!/usr/bin/env bash
# 备份 SQLite 到容器内的 /data/backups，保留最近 14 天。
# 用法（在仓库根目录）：
#   bash deploy/backup.sh
# 建议加进 crontab：
#   0 3 * * * cd /srv/yifazhilian && bash deploy/backup.sh >> /var/log/yfz-backup.log 2>&1

set -euo pipefail

COMPOSE="docker compose -f deploy/docker-compose.yml"

$COMPOSE exec -T api python - <<'PY'
import datetime
import os
import sqlite3

src = os.environ.get("YIFAZHILIAN_DB_PATH", "/data/yifazhilian.db")
backup_dir = "/data/backups"
os.makedirs(backup_dir, exist_ok=True)

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
target = os.path.join(backup_dir, f"yfz-{stamp}.db")

# sqlite3 的 backup API 在 WAL 模式下也是安全的一致性快照
source = sqlite3.connect(src)
dest = sqlite3.connect(target)
with dest:
    source.backup(dest)
source.close()
dest.close()

cutoff = datetime.datetime.now() - datetime.timedelta(days=14)
removed = 0
for name in os.listdir(backup_dir):
    path = os.path.join(backup_dir, name)
    if not name.endswith(".db"):
        continue
    if datetime.datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
        os.remove(path)
        removed += 1

print(f"backup: {target} ({os.path.getsize(target)} bytes), pruned: {removed}")
PY
