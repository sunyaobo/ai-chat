#!/bin/bash
# ============================================================
#  四合一 AI 应用 · 一键部署脚本（阿里云轻量 2C2G 优化版）
#
#  使用方式：
#    1. ssh 到服务器
#    2. git clone ... && cd 项目目录  （或 scp 解压后 cd）
#    3. cp .env.example .env && vim .env   # 填入密钥
#    4. （可选）把 RAG 文档放到 qa_bot/backend/data/
#    5. bash deploy.sh
#
#  优化点（针对 2核2G 服务器）：
#    * Docker 镜像加速（阿里云 + daocloud）
#    * pip / npm 国内源（自动注入到 Dockerfile）
#    * Swap 扩容至 4GB（2GB 物理内存扛不住 Python 镜像构建）
#    * 分批构建 + 失败重试 + 构建前磁盘清理
#    * 单镜像 build 限制内存，避免 OOM 杀整机
# ============================================================
set -e

# ---------- 颜色输出 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }

echo "=========================================="
echo "  AI 应用集群部署（2C2G 优化版）"
echo "=========================================="

# ============================================================
# 0. 读取 .env
# ============================================================
if [ ! -f .env ]; then
  err ".env 不存在，请先执行：cp .env.example .env && vim .env"
  exit 1
fi
set -a; source .env; set +a

# 必填项校验
if [ -z "$DB_PASSWORD" ] || [ "$DB_PASSWORD" = "changeme123" ]; then
  err ".env 里 DB_PASSWORD 未设置或仍是默认值 changeme123"
  exit 1
fi
if [ -z "$DASHSCOPE_API_KEY" ]; then
  warn ".env 里 DASHSCOPE_API_KEY 未设置，依赖大模型的项目（chat/qa/review/enterprise）将无法正常工作"
fi

# ============================================================
# 1. 检查内存 + 自动扩 Swap（2GB 内存构建 Python 镜像必爆，扩到 4GB swap 兜底）
# ============================================================
MEM=$(free -m | awk '/Mem:/ {print $2}')
SWAP=$(free -m | awk '/Swap:/ {print $2}')
info "当前内存 ${MEM}MB，Swap ${SWAP}MB"

if [ "$MEM" -lt 4096 ]; then
  warn "内存 < 4GB，构建可能 OOM，已确保 Swap 充足"
fi

# 2GB 内存下，swap 至少要 4GB 才能 build torch/langchain 类镜像
if [ "${SWAP:-0}" -lt 4000 ]; then
  info "Swap 不足 4GB，扩容中 ..."
  swapoff /swapfile 2>/dev/null || true
  rm -f /swapfile 2>/dev/null || true
  # fallocate 在某些文件系统不支持，回退 dd
  if ! fallocate -l 4G /swapfile 2>/dev/null; then
    info "fallocate 失败，使用 dd（较慢，请等待）..."
    dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress
  fi
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  # 降低 swappiness，优先用物理内存，构建峰值才用 swap
  sysctl -w vm.swappiness=30 >/dev/null 2>&1 || true
  ok "Swap 扩容至 4GB 完成（当前 $(free -m | awk '/Swap:/ {print $2}')MB）"
else
  ok "Swap 已足够（${SWAP}MB），跳过扩容"
fi

# ============================================================
# 2. 检查并安装 Docker（阿里云 Alibaba Cloud Linux 3）
# ============================================================
install_docker() {
  info "Docker 未安装，使用阿里云镜像安装 ..."
  yum install -y yum-utils device-mapper-persistent-data lvm2
  yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
  yum makecache
  yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl start docker
  systemctl enable docker
  ok "Docker 安装完成"
}

if ! command -v docker &> /dev/null; then
  install_docker
fi

if ! docker compose version &> /dev/null; then
  err "Docker Compose 未安装，请手动安装 docker-compose-plugin"
  exit 1
fi

ok "Docker $(docker --version | awk '{print $3}') / Compose $(docker compose version --short)"

# ============================================================
# 3. 配置 Docker 镜像加速（阿里云轻量访问 Docker Hub 极慢/被墙）
# ============================================================
configure_docker_mirror() {
  mkdir -p /etc/docker
  # 多镜像源兜底，按顺序尝试
  if [ ! -f /etc/docker/daemon.json ] || ! grep -q registry-mirrors /etc/docker/daemon.json; then
    info "配置 Docker 镜像加速 ..."
    cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://docker.nju.edu.cn",
    "https://docker.1ms.run"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
EOF
    systemctl daemon-reload
    systemctl restart docker
    ok "Docker 镜像加速已配置"
  else
    ok "Docker 镜像加速已存在，跳过"
  fi
}
configure_docker_mirror

# ============================================================
# 4. 磁盘清理（40GB ESSD，构建 4 个镜像需预留 10GB+）
# ============================================================
DISK_FREE=$(df -m / | awk 'NR==2 {print $4}')
info "根分区剩余空间 ${DISK_FREE}MB"
if [ "$DISK_FREE" -lt 10240 ]; then
  warn "剩余空间 < 10GB，清理 Docker 缓存 ..."
  docker system prune -af --volumes 2>/dev/null || true
  yum clean all 2>/dev/null || true
  DISK_FREE2=$(df -m / | awk 'NR==2 {print $4}')
  info "清理后剩余 ${DISK_FREE2}MB"
fi

# ============================================================
# 5. 给 4 个 Dockerfile 注入 pip 国内源（加速构建，避免 PyPI 超时）
#    在 `RUN pip install` 前插入 ENV PIP_INDEX_URL
# ============================================================
inject_pip_mirror() {
  local df="$1"
  [ ! -f "$df" ] && return
  if grep -q "PIP_INDEX_URL" "$df"; then
    return  # 已注入过
  fi
  info "为 $(basename $(dirname $df)) 注入 pip 阿里云源 ..."
  # 在第一个 RUN 之前插入全局 pip 镜像 + 超时配置
  sed -i '0,/^RUN/s|^\(FROM .*\)|\1\n\n# 阿里云 pip 镜像（deploy.sh 自动注入）\nENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/\nENV PIP_TRUSTED_HOST=mirrors.aliyun.com\nENV PIP_DEFAULT_TIMEOUT=120|' "$df"
}
for df in chat_app/backend/Dockerfile qa_bot/backend/Dockerfile \
           code_review_bot/backend/Dockerfile enterprise_ai/backend/Dockerfile; do
  inject_pip_mirror "$df"
done

# ============================================================
# 6. 检查 RAG 文档（可选，缺了 qa_bot 仍能启动）
# ============================================================
if [ ! -f qa_bot/backend/data/银行个金客户经理考核办法.docx ]; then
  warn "qa_bot RAG 文档缺失，qa_bot 启动时会跳过 RAG 初始化（其他项目不受影响）"
  warn "如需 RAG，请上传：scp 银行个金客户经理考核办法.docx root@<IP>:/root/项目目录/qa_bot/backend/data/"
fi

# ============================================================
# 7. 先拉取基础镜像（预热，避免 build 时网络抖动中断）
# ============================================================
info "预热基础镜像（python:3.11-slim / mysql:8.0 / nginx:alpine） ..."
for img in python:3.11-slim mysql:8.0 nginx:alpine; do
  docker pull "$img" || warn "拉取 $img 失败，构建时会重试"
done

# ============================================================
# 8. 分批构建（2GB 内存不能并发 build，逐个 + 失败重试）
# ============================================================
echo ""
info "分批构建镜像（每个镜像失败自动重试 1 次）..."

build_one() {
  local name="$1"
  local attempt=0
  local max=2
  while [ $attempt -lt $max ]; do
    attempt=$((attempt + 1))
    echo -e "${CYAN}  构建 $name (第 $attempt 次) ...${NC}"
    # --build-arg 传递 pip 镜像（Dockerfile 未声明 ARG 会被忽略，不影响）
    if docker compose build \
        --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
        --build-arg PIP_TRUSTED_HOST=mirrors.aliyun.com \
        "$name"; then
      ok "$name 构建成功"
      return 0
    fi
    warn "$name 第 $attempt 次构建失败"
    [ $attempt -lt $max ] && {
      info "清理构建缓存后重试 ..."
      docker builder prune -f 2>/dev/null || true
    }
  done
  err "$name 构建失败（已重试 $max 次）"
  return 1
}

for name in chat-app qa-bot code-review-bot enterprise-ai; do
  build_one "$name" || { err "无法继续，请检查 $name 的 Dockerfile / requirements.txt"; exit 1; }
  # 每个构建后清理中间层缓存，省磁盘
  docker builder prune -f 2>/dev/null || true
done

# ============================================================
# 9. 启动服务
# ============================================================
echo ""
info "启动服务集群 ..."
docker compose up -d

# ============================================================
# 10. 等待 MySQL 就绪（建库依赖）
# ============================================================
echo ""
info "等待 MySQL 就绪（最多 90s）..."
timeout=90
while [ $timeout -gt 0 ]; do
  if docker compose exec -T mysql mysqladmin ping -h localhost -p"$DB_PASSWORD" --silent 2>/dev/null; then
    ok "MySQL 已就绪"
    break
  fi
  echo -n "."
  sleep 2
  timeout=$((timeout - 2))
done
echo ""
if [ $timeout -le 0 ]; then
  err "MySQL 启动超时，请检查：docker compose logs mysql"
  exit 1
fi

# ============================================================
# 11. 自动建库
# ============================================================
info "创建 4 个数据库 ..."
for db in chat_app qa_bot code_review enterprise_ai; do
  docker compose exec -T mysql mysql -uroot -p"$DB_PASSWORD" -e \
    "CREATE DATABASE IF NOT EXISTS $db DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
  echo -e "  ${GREEN}✓${NC} $db"
done

# ============================================================
# 12. 状态汇总 + 健康检查
# ============================================================
IP=$(hostname -I | awk '{print $1}')
# 轻量服务器可能返回内网 IP，提示公网 IP
PUB_IP=$(curl -s --max-time 3 http://100.100.100.200/latest/meta-data/public-ipv4 2>/dev/null || echo "$IP")

echo ""
echo "=========================================="
echo -e "  ${GREEN}部署完成！${NC}"
echo "=========================================="
echo ""
echo "容器状态："
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || docker compose ps
echo ""
echo "后端 API 地址（Nginx 80 端口）："
echo "  chat_app       → http://$PUB_IP/chat/"
echo "  qa_bot         → http://$PUB_IP/qa/"
echo "  code_review    → http://$PUB_IP/review/"
echo "  enterprise_ai  → http://$PUB_IP/enterprise/"
echo ""
echo "健康检查："
echo "  curl http://localhost/health"
echo "  curl http://$PUB_IP/chat/"
echo ""
echo "常用运维："
echo "  查看状态：docker compose ps"
echo "  实时日志：docker compose logs -f [服务名]"
echo "  重启某项：docker compose restart chat-app"
echo "  更新代码：git pull && docker compose up -d --build chat-app"
echo "  停止全部：docker compose down"
echo "  MySQL备份：docker compose exec -T mysql mysqldump -uroot -p\$DB_PASSWORD --databases chat_app qa_bot code_review enterprise_ai > backup.sql"
echo ""
echo "===== 前端 Vercel 部署 ====="
echo "在各 frontend/ 目录的 Vercel 项目环境变量中设置："
echo "  chat_app       VITE_API_BASE=http://$PUB_IP/chat"
echo "  qa_bot         VITE_API_BASE=http://$PUB_IP/qa"
echo "  code_review    VITE_API_BASE=http://$PUB_IP/review"
echo "  enterprise_ai  VITE_API_BASE=http://$PUB_IP/enterprise"
echo ""
warn "阿里云安全组需开放 80 端口（入方向 TCP 0.0.0.0/0）"
