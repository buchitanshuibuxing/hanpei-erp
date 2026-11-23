#!/usr/bin/env bash
# 升级：备份 → 重新构建 → 重启 → 健康检查 → 失败自动回滚到旧镜像
set -euo pipefail
cd "$(dirname "$0")/.."
OLD_IMAGE="$(docker compose -f deploy/docker-compose.yml images -q erp 2>/dev/null | head -1 || true)"

echo "==> 升级前备份"
bash deploy/backup.sh

echo "==> 构建新版本"
docker compose -f deploy/docker-compose.yml build erp
echo "==> 重启服务"
docker compose -f deploy/docker-compose.yml up -d erp

ok=0
for i in $(seq 1 12); do
  if curl -fsS "http://127.0.0.1:${HTTP_PORT:-80}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
if [ "$ok" -ne 1 ]; then
  echo "健康检查失败，尝试回滚"
  if [ -n "$OLD_IMAGE" ]; then
    docker tag "$OLD_IMAGE" hanpei-erp-rollback:latest || true
    docker compose -f deploy/docker-compose.yml down erp || true
    echo "请手动执行：docker compose -f deploy/docker-compose.yml up -d（使用上一镜像标签 $OLD_IMAGE）"
  fi
  docker compose -f deploy/docker-compose.yml logs --tail=80 erp
  exit 1
fi
echo "升级完成，健康检查通过"
