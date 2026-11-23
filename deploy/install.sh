#!/usr/bin/env bash
# 一键部署：检测 Docker → 生成 .env（随机密码）→ 构建并启动 → 健康检查 → 输出地址
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

echo "==> 1/5 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker，请先安装（国内可执行 curl -fsSL https://get.docker.com | bash -s -- --mirror Aliyun）"
  exit 1
fi
docker compose version >/dev/null 2>&1 || { echo "需要 Docker Compose v2 插件"; exit 1; }

echo "==> 2/5 生成 .env"
ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  rand() { openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 32; }
  PG_PASS="$(rand)"; MINIO_PASS="$(rand)"; SECRET="$(rand)$(rand)"; ADMIN_PASS="$(rand | cut -c1-12)"
  cat > "$ENV_FILE" <<EOF
# 由 install.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 生成，请妥善保管
PG_USER=erp
PG_PASSWORD=$PG_PASS
PG_DB=erp
MINIO_USER=erp
MINIO_PASSWORD=$MINIO_PASS
SECRET_KEY=$SECRET
DATABASE_URL=postgresql+psycopg://erp:$PG_PASS@postgres:5432/erp
APP_ENV=production
APP_PORT=8008
SERVE_FRONTEND=1
HTTP_PORT=80
PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
BOOTSTRAP_ADMIN=admin
BOOTSTRAP_PASSWORD=$ADMIN_PASS
EOF
  chmod 600 "$ENV_FILE"
  echo "   已生成 $ENV_FILE（随机密码，权限 600）"
else
  echo "   已存在，沿用现有 .env"
fi

# compose 默认只从当前目录读 .env，而本项目 .env 在仓库根；
# 不建软链的话 ${PG_PASSWORD:?} / ${MINIO_PASSWORD:?} 会被判为缺失，直接拒绝启动。
if [ ! -e .env ] || [ -L .env ]; then ln -sfn ../.env .env; fi
ADMIN_PASS="$(sed -n 's/^BOOTSTRAP_PASSWORD=//p' "$ENV_FILE" | head -1)"
HTTP_PORT="$(sed -n 's/^HTTP_PORT=//p' "$ENV_FILE" | head -1)"; HTTP_PORT="${HTTP_PORT:-80}"

echo "==> 3/5 构建镜像（首次约 3-8 分钟）"
docker compose build --pull=false

echo "==> 4/5 启动服务"
docker compose up -d

echo "==> 5/5 健康检查（最多等待 120 秒）"
ok=0
for i in $(seq 1 24); do
  if curl -fsS "http://127.0.0.1:${HTTP_PORT:-80}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
if [ "$ok" -ne 1 ]; then
  echo "健康检查未通过，最近日志："
  docker compose logs --tail=60 erp
  exit 1
fi

echo ""
echo "==> 部署完成"
echo "    访问地址： http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1):${HTTP_PORT:-80}"
echo "    初始账号： admin / $ADMIN_PASS （随机生成，见 .env；请登录后立即修改密码）"
echo "    手动事项： 域名解析、路由器端口映射、防火墙放行 443/80（脚本无法代做）"
