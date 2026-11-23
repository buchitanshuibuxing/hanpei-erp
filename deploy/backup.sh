#!/usr/bin/env bash
# 每日备份：PostgreSQL 走 pg_dump，文件目录打 tar；保留 30 天
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./data/backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
if docker compose -f deploy/docker-compose.yml ps postgres 2>/dev/null | grep -q Up; then
  docker compose -f deploy/docker-compose.yml exec -T postgres \
    pg_dump -U "${PG_USER:-erp}" -d "${PG_DB:-erp}" -Fc > "$BACKUP_DIR/db_${STAMP}.dump"
else
  [ -f data/erp.db ] && cp data/erp.db "$BACKUP_DIR/erp_${STAMP}.db"
fi
tar -czf "$BACKUP_DIR/files_${STAMP}.tar.gz" data/uploads 2>/dev/null || true
find "$BACKUP_DIR" -type f -mtime +30 -delete
echo "备份完成：$BACKUP_DIR/*_${STAMP}.*"
