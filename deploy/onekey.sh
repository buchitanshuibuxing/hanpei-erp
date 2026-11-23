#!/usr/bin/env bash
# =============================================================================
# Hanpei ERP 一键部署脚本
#
#   sudo bash onekey.sh                # 轻量模式（默认）：系统 Python 3.12 + SQLite
#                                     #   + 前端构建 + systemd，单端口 8008
#   sudo bash onekey.sh --docker       # 完整模式：Docker Compose
#                                     #   PostgreSQL / Redis / MinIO / 后端 / Nginx，端口 80
#   sudo bash onekey.sh --help         # 查看全部参数
#
# 设计原则：
#   1. 幂等 —— 可重复执行；.env、数据库、数据卷不会被覆盖或删除
#   2. 国内网络友好 —— 所有下载源都有国内镜像；git clone 失败自动回落 codeload tarball
#   3. 可诊断 —— 任一步失败打印行号；健康检查失败自动附带日志
#
# 可覆盖的环境变量：REPO_URL BRANCH INSTALL_DIR APP_PORT HTTP_PORT
#                   PYTHON_VERSION NODE_VERSION CN_MIRROR SKIP_FRONTEND
# =============================================================================
set -Eeuo pipefail

MODE="lite"
REPO_URL="${REPO_URL:-https://github.com/buchitanshuibuxing/hanpei-erp.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/hanpei-erp}"
APP_PORT="${APP_PORT:-8008}"
HTTP_PORT="${HTTP_PORT:-80}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
NODE_VERSION="${NODE_VERSION:-v22.11.0}"
CN_MIRROR="${CN_MIRROR:-1}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"
SERVICE="hanpei-erp"

usage() {
  # 不依赖 $0：脚本可能通过 `curl ... | sudo bash` 以 stdin 方式执行
  cat <<'USAGE'
Hanpei ERP 一键部署

  sudo bash onekey.sh                lite 模式（默认）：Python 3.12 + SQLite + 前端构建
                                     + systemd，单端口 8008
  sudo bash onekey.sh --docker       full 模式：Docker Compose
                                     PostgreSQL / Redis / MinIO / 后端 / Nginx，端口 80
  sudo bash onekey.sh --help         显示本帮助

可覆盖的环境变量：
  REPO_URL BRANCH INSTALL_DIR APP_PORT HTTP_PORT
  PYTHON_VERSION NODE_VERSION CN_MIRROR SKIP_FRONTEND

脚本幂等：重复执行不会覆盖 .env、数据库或数据卷。
USAGE
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --docker) MODE="docker" ;;
    --lite)   MODE="lite" ;;
    -h|--help) usage ;;
    *) echo "未知参数: $arg（用 --help 查看用法）" >&2; exit 2 ;;
  esac
done

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'printf "\033[1;31m[FAIL]\033[0m 第 %s 行执行失败: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

[[ $EUID -eq 0 ]] || die "请用 root 运行：sudo bash onekey.sh [--docker]"
command -v apt-get >/dev/null 2>&1 || die "本脚本面向 Ubuntu / Debian（需要 apt-get）"

export DEBIAN_FRONTEND=noninteractive
. /etc/os-release
CODENAME="${VERSION_CODENAME:-jammy}"

if [[ "$CN_MIRROR" == "1" ]]; then
  PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
  NPM_REGISTRY="https://registry.npmmirror.com"
  APT_DOCKER="https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu"
  NODE_URL="https://registry.npmmirror.com/-/binary/node/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
else
  PIP_INDEX="https://pypi.org/simple"
  NPM_REGISTRY="https://registry.npmjs.org"
  APT_DOCKER="https://download.docker.com/linux/ubuntu"
  NODE_URL="https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
fi

# -----------------------------------------------------------------------------
log "1/8 系统准备与软件源（${PRETTY_NAME:-Linux} / ${CODENAME}）"
# -----------------------------------------------------------------------------
if [[ "$CN_MIRROR" == "1" ]]; then
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
    [[ -f "$f" ]] || continue
    grep -qE 'archive\.ubuntu\.com|security\.ubuntu\.com' "$f" || continue
    cp -n "$f" "$f.hanpei-bak" 2>/dev/null || true
    sed -i -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' \
           -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' "$f"
  done
fi
apt-get update -qq
apt-get install -y -qq git curl ca-certificates xz-utils openssl \
  python3 python3-venv python3-pip build-essential >/dev/null
ok "基础依赖就绪（python3=$(python3 --version 2>&1 | awk '{print $2}')）"

# -----------------------------------------------------------------------------
log "2/8 获取代码 → $INSTALL_DIR"
# -----------------------------------------------------------------------------
SOURCE_MODE="git"
OWNER_REPO="${REPO_URL#https://github.com/}"; OWNER_REPO="${OWNER_REPO%.git}"
TARBALL="https://codeload.github.com/${OWNER_REPO}/tar.gz/refs/heads/${BRANCH}"
GIT_OPTS=(-c http.version=HTTP/1.1 -c http.lowSpeedLimit=0 -c http.lowSpeedTime=60)

# GitHub 网页/codeload 常比 git 协议稳定；clone 或 fetch 失败时一律用 tarball 覆盖源码，
# 绝不静默沿用旧代码（否则会部署到过期版本，实测中因此重复拉过旧 minio:latest）。
# cp -a 只覆盖 tarball 里的文件，不会删除 .env / data / .venv / dist 等运行期内容。
fetch_tarball() {
  warn "改用 codeload tarball 覆盖源码：$TARBALL"
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL --retry 3 --max-time 120 "$TARBALL" -o "$tmp/src.tar.gz" \
    || die "tarball 下载失败，请检查网络或设置 REPO_URL"
  mkdir -p "$INSTALL_DIR"
  tar -xzf "$tmp/src.tar.gz" -C "$tmp"
  cp -a "$tmp"/"$(basename "$OWNER_REPO")-$BRANCH"/. "$INSTALL_DIR"/
  rm -rf "$tmp"
  SOURCE_MODE="tarball"
}

if [[ -d "$INSTALL_DIR/.git" ]]; then
  updated=0
  for attempt in 1 2; do
    if git -C "$INSTALL_DIR" "${GIT_OPTS[@]}" fetch --depth 1 origin "$BRANCH" >/dev/null 2>&1 \
       && git -C "$INSTALL_DIR" checkout -q -f "$BRANCH" \
       && git -C "$INSTALL_DIR" reset -q --hard FETCH_HEAD; then
      updated=1; break
    fi
    warn "仓库更新第 $attempt 次失败（HTTP2 / TLS 常见），重试中"
  done
  [[ "$updated" -eq 1 ]] || fetch_tarball
else
  cloned=0
  for attempt in 1 2; do
    rm -rf "$INSTALL_DIR"
    if git "${GIT_OPTS[@]}" clone --depth 1 -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1; then
      cloned=1; break
    fi
    warn "git clone 第 $attempt 次失败（国内链路 TLS 常见），重试中"
  done
  [[ "$cloned" -eq 1 ]] || fetch_tarball
fi
[[ -f "$INSTALL_DIR/backend/app/main.py" ]] || die "代码目录不完整：$INSTALL_DIR"
if [[ "$SOURCE_MODE" == "tarball" ]]; then
  ok "代码就绪（来源：tarball 覆盖更新，运行期数据保留）"
else
  ok "代码就绪（来源：git）"
fi

# -----------------------------------------------------------------------------
log "3/8 生成 .env（随机密钥，已存在则沿用）"
# -----------------------------------------------------------------------------
rand() { openssl rand -hex "${1:-24}"; }
ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  cat > "$ENV_FILE" <<EOF
# 由 deploy/onekey.sh 于 $(date '+%F %T') 生成；请妥善保管，勿提交到仓库
APP_ENV=production
APP_PORT=$APP_PORT
SERVE_FRONTEND=1
DATABASE_URL=sqlite:///$INSTALL_DIR/data/erp.db
SECRET_KEY=$(rand 32)
MASTER_KEY=
BOOTSTRAP_ADMIN=admin
BOOTSTRAP_PASSWORD=$(rand 8)
BOOTSTRAP_PORTAL_USER=alnoor
BOOTSTRAP_PORTAL_PASSWORD=$(rand 8)
# 以下供 --docker 模式使用；compose 会把 DATABASE_URL 覆盖成 PostgreSQL
PG_USER=erp
PG_PASSWORD=$(rand 16)
PG_DB=erp
MINIO_USER=erp
MINIO_PASSWORD=$(rand 16)
HTTP_PORT=$HTTP_PORT
PIP_INDEX=$PIP_INDEX
EOF
  chmod 600 "$ENV_FILE"
  ok "已生成 $ENV_FILE（600）"
else
  ok "沿用现有 .env"
fi
# 幂等补齐：老版本 .env 缺 docker 相关键时追加，不覆盖已有值
for key in PG_PASSWORD MINIO_PASSWORD HTTP_PORT PIP_INDEX BOOTSTRAP_PORTAL_USER BOOTSTRAP_PORTAL_PASSWORD; do
  grep -q "^${key}=" "$ENV_FILE" || {
    case "$key" in
      PG_PASSWORD|MINIO_PASSWORD) echo "$key=$(rand 16)" >> "$ENV_FILE" ;;
      BOOTSTRAP_PORTAL_USER) echo "BOOTSTRAP_PORTAL_USER=alnoor" >> "$ENV_FILE" ;;
      BOOTSTRAP_PORTAL_PASSWORD) echo "BOOTSTRAP_PORTAL_PASSWORD=$(rand 8)" >> "$ENV_FILE" ;;
      HTTP_PORT) echo "HTTP_PORT=$HTTP_PORT" >> "$ENV_FILE" ;;
      PIP_INDEX) echo "PIP_INDEX=$PIP_INDEX" >> "$ENV_FILE" ;;
    esac
  }
done
# 老版本 .env 里写的是 sqlite:///./data/erp.db（相对路径）。systemd 的 WorkingDirectory
# 是 backend/，会解析成 backend/data/erp.db 而该目录不存在 -> "unable to open database file"。
# 这里自动迁移成绝对路径，保证重复执行也能自愈。
if grep -q '^DATABASE_URL=sqlite:///\./' "$ENV_FILE"; then
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=sqlite:///$INSTALL_DIR/data/erp.db|" "$ENV_FILE"
  warn "已把 .env 中的相对 SQLite 路径迁移为绝对路径"
fi
ADMIN_USER="$(sed -n 's/^BOOTSTRAP_ADMIN=//p' "$ENV_FILE" | head -1)"
ADMIN_PASS="$(sed -n 's/^BOOTSTRAP_PASSWORD=//p' "$ENV_FILE" | head -1)"
[[ -n "$ADMIN_PASS" ]] || die ".env 中缺少 BOOTSTRAP_PASSWORD"
PORTAL_USER="$(sed -n 's/^BOOTSTRAP_PORTAL_USER=//p' "$ENV_FILE" | head -1)"
PORTAL_PASS="$(sed -n 's/^BOOTSTRAP_PORTAL_PASSWORD=//p' "$ENV_FILE" | head -1)"

# -----------------------------------------------------------------------------
log "4/8 准备 Python $PYTHON_VERSION 运行时"
# -----------------------------------------------------------------------------
PYBASE=""
if python3 -c "import sys;sys.exit(0 if sys.version_info[:2] >= (3,12) else 1)" 2>/dev/null; then
  PYBASE="$(command -v python3)"
  ok "使用系统 Python $(python3 --version 2>&1 | awk '{print $2}')"
else
  # Ubuntu 22.04 自带 3.10，而项目 CI 基线为 3.12/3.13；用 uv 装独立 3.12，不污染系统
  UV_BIN="/usr/local/bin/uv"
  if [[ ! -x "$UV_BIN" ]]; then
    if curl -fsSL --max-time 60 https://astral.sh/uv/install.sh \
         | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null 2>&1; then
      :
    else
      # uv 官方脚本不通时，直接取 GitHub 上的独立二进制
      curl -fsSL --max-time 120 \
        "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-x86_64-unknown-linux-gnu.tar.gz" \
        -o /tmp/uv.tar.gz 2>/dev/null && \
        tar -xzf /tmp/uv.tar.gz -C /usr/local/bin --strip-components=1 2>/dev/null || true
    fi
  fi
  if [[ -x "$UV_BIN" ]] && "$UV_BIN" python install "$PYTHON_VERSION" >/dev/null 2>&1; then
    PYBASE="$("$UV_BIN" python find "$PYTHON_VERSION")"
    ok "uv 已安装托管 Python $($PYBASE --version 2>&1)"
  else
    warn "uv 不可用，回退系统 Python（若依赖报版本不兼容，请检查网络后重跑）"
    PYBASE="$(command -v python3)"
  fi
fi
"$PYBASE" -m venv "$INSTALL_DIR/.venv"
VPY="$INSTALL_DIR/.venv/bin/python"
"$VPY" -m pip install -q --upgrade pip -i "$PIP_INDEX"
ok "虚拟环境：$VPY"

# -----------------------------------------------------------------------------
log "5/8 安装后端依赖（$PIP_INDEX）"
# -----------------------------------------------------------------------------
"$VPY" -m pip install -q -i "$PIP_INDEX" \
  -r "$INSTALL_DIR/backend/requirements.txt" \
  -c "$INSTALL_DIR/backend/constraints.txt"
"$VPY" -c "import fastapi, sqlalchemy, pydantic, alembic, uvicorn" \
  || die "后端依赖导入失败"
ok "后端依赖就绪"

# -----------------------------------------------------------------------------
log "6/8 构建前端（Node $NODE_VERSION）"
# -----------------------------------------------------------------------------
if [[ "$SKIP_FRONTEND" == "1" && -f "$INSTALL_DIR/frontend/dist/index.html" ]]; then
  warn "SKIP_FRONTEND=1，沿用已有 dist"
else
  NEED_NODE=1
  if command -v node >/dev/null 2>&1; then
    major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
    [[ "$major" -ge 18 ]] && NEED_NODE=0
  fi
  if [[ "$NEED_NODE" -eq 1 ]]; then
    curl -fsSL --retry 3 --max-time 180 "$NODE_URL" -o /tmp/node.tar.xz \
      || die "Node 下载失败：$NODE_URL"
    mkdir -p /opt/node
    tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1
    ln -sf /opt/node/bin/node /usr/local/bin/node
    ln -sf /opt/node/bin/npm  /usr/local/bin/npm
    ln -sf /opt/node/bin/npx  /usr/local/bin/npx
    export PATH="/opt/node/bin:$PATH"
  fi
  ok "Node $(node --version) / npm $(npm --version)"
  ( cd "$INSTALL_DIR/frontend" && \
    npm ci --registry "$NPM_REGISTRY" --no-audit --no-fund >/dev/null && \
    npm run build >/dev/null )
  [[ -f "$INSTALL_DIR/frontend/dist/index.html" ]] || die "前端构建未产出 dist/index.html"
  ok "前端产物：$INSTALL_DIR/frontend/dist"
fi

# -----------------------------------------------------------------------------
log "7/8 启动服务（模式：$MODE）"
# -----------------------------------------------------------------------------
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/data/uploads" "$INSTALL_DIR/backend/data"

if [[ "$MODE" == "lite" ]]; then
  cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=Hanpei ERP (lite / SQLite single-port)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR/backend
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1 SERVE_FRONTEND=1
ExecStart=$VPY -m uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT --workers 1
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1
  systemctl restart "$SERVICE"
  HEALTH_URL="http://127.0.0.1:${APP_PORT}/api/health"
  FAIL_LOG="journalctl -u $SERVICE -n 80 --no-pager"
else
  if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL --max-time 60 "${APT_DOCKER}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] ${APT_DOCKER} ${CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
      docker-buildx-plugin docker-compose-plugin >/dev/null
  fi
  docker compose version >/dev/null 2>&1 || die "缺少 Docker Compose v2 插件"
  systemctl enable --now docker >/dev/null 2>&1 || true

  if [[ "$CN_MIRROR" == "1" ]]; then
    mkdir -p /etc/docker
    python3 - <<'PY'
import json, os
p = "/etc/docker/daemon.json"
d = json.load(open(p)) if os.path.exists(p) and os.path.getsize(p) else {}
m = d.setdefault("registry-mirrors", [])
mirror = "https://docker.m.daocloud.io"
if mirror not in m:
    m.insert(0, mirror)
d.setdefault("log-driver", "json-file")
d.setdefault("log-opts", {"max-size": "20m", "max-file": "3"})
json.dump(d, open(p, "w"), indent=2)
PY
    systemctl restart docker
    ok "已配置 Docker 镜像加速：docker.m.daocloud.io"
  fi

  mkdir -p "$INSTALL_DIR/deploy/certs"
  # compose 默认只从当前目录读 .env，而本项目 .env 在仓库根；软链 + 显式 --env-file 双保险，
  # 否则 ${PG_PASSWORD:?} / ${MINIO_PASSWORD:?} 会被判定为缺失而直接拒绝启动。
  ln -sfn ../.env "$INSTALL_DIR/deploy/.env"
  ( cd "$INSTALL_DIR/deploy" && docker compose --env-file "$ENV_FILE" up -d --build )
  HEALTH_URL="http://127.0.0.1:${HTTP_PORT}/api/health"
  FAIL_LOG="cd $INSTALL_DIR/deploy && docker compose --env-file $ENV_FILE logs --tail=80 erp nginx"
fi

# -----------------------------------------------------------------------------
log "8/8 健康检查"
# -----------------------------------------------------------------------------
healthy=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 3
done
if [[ "$healthy" -ne 1 ]]; then
  echo "--- 最近日志 ---" >&2
  bash -c "$FAIL_LOG" >&2 || true
  die "健康检查未通过：$HEALTH_URL"
fi
ok "health 200：$HEALTH_URL"

BASE_URL="${HEALTH_URL%/api/health}"
SPA_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/" || true)"
LOGIN_CODE="$(curl -sS -o /tmp/hp_login.json -w '%{http_code}' \
  -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" || true)"
if python3 -c "import json,sys;d=json.load(open('/tmp/hp_login.json'));sys.exit(0 if d.get('token') else 1)" 2>/dev/null; then
  LOGIN_OK="token OK"
else
  LOGIN_OK="需检查（可能 .env 为旧密码，种子账号只在首次初始化生效）"
fi

echo
echo "==================== Hanpei ERP 部署完成 ===================="
printf '  模式        : %s\n' "$MODE"
printf '  代码目录    : %s（来源 %s）\n' "$INSTALL_DIR" "$SOURCE_MODE"
printf '  访问地址    : %s\n' "$BASE_URL"
printf '  健康检查    : 200\n'
printf '  SPA 首页    : %s\n' "$SPA_CODE"
printf '  管理员登录  : %s / %s（%s）\n' "$ADMIN_USER" "$ADMIN_PASS" "$LOGIN_OK"
printf '  管理员账号  : %s\n' "$ADMIN_USER"
printf '  管理员密码  : %s\n' "$ADMIN_PASS"
printf '  门户账号    : %s / %s\n' "${PORTAL_USER:-alnoor}" "${PORTAL_PASS:-（沿用旧值）}"
if [[ "$MODE" == "lite" ]]; then
  printf '  服务管理    : systemctl {status|restart|stop} %s\n' "$SERVICE"
  printf '  查看日志    : journalctl -u %s -f\n' "$SERVICE"
else
  printf '  服务管理    : cd %s/deploy && docker compose {ps|logs|down}\n' "$INSTALL_DIR"
fi
printf '  备份数据    : %s/.env 与 %s/data（docker 模式另有数据卷）\n' "$INSTALL_DIR" "$INSTALL_DIR"
echo "============================================================"
echo "提示：这是内网测试部署；上公网前请改默认密码、配 HTTPS、限制来源 IP（见 SECURITY.md）。"
