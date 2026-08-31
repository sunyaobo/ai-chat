#!/bin/bash
# ============================================================
#  四合一 AI 应用 · 一键部署脚本（阿里云轻量应用服务器）
#
#  使用方式：
#    1. ssh 到服务器
#    2. git clone https://github.com/sunyaobo/ai-chat.git && cd ai-chat
#    3. cp .env.example .env && vim .env   # 填入密钥
#    4. （可选）把 RAG 文档放到 qa_bot/backend/data/
#    5. bash deploy.sh
# ============================================================
set -e

echo "=========================================="
echo "  AI 应用集群部署"
echo "=========================================="

# 1. 读取 .env（脚本自己需要用 DB_PASSWORD 建库）
if [ ! -f .env ]; then
  echo "[ERROR] .env 不存在，请先 cp .env.example .env 并填入密钥"
  exit 1
fi
set -a
source .env
set +a

# 2. 检查内存 + 自动加 swap（轻量应用服务器通常只有 2核4G，不够 build 4 个镜像）
MEM=$(free -m | awk '/Mem:/ {print $2}')
SWAP=$(free -m | awk '/Swap:/ {print $2}')
echo "当前内存 ${MEM}MB，Swap ${SWAP}MB"

if [ "$MEM" -lt 4096 ]; then
  echo "[WARN] 内存不足 4GB，构建可能 OOM"
fi

if [ "$SWAP" -lt 2048 ]; then
  echo "[INFO] 自动扩容 Swap 至 2GB ..."
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  # 持久化
  if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  fi
  echo "Swap 扩容完成"
fi

# 3. 检查 Docker
if ! command -v docker &> /dev/null; then
  echo "[ERROR] Docker 未安装，请先执行："
  echo "  curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker \$USER"
  echo "  然后重新登录 ssh 会话"
  exit 1
fi

if ! docker compose version &> /dev/null; then
  echo "[ERROR] Docker Compose 未安装"
  exit 1
fi

# 4. 检查 RAG 文档（可选）
if [ ! -f qa_bot/backend/data/银行个金客户经理考核办法.docx ]; then
  echo "[INFO] qa_bot RAG 文档不存在，qa_bot 启动时会跳过 RAG 初始化（其他项目不受影响）"
fi

# 5. 分批构建（避免 OOM）
echo ""
echo "[1/3] 构建镜像（分批构建以避免内存不足）..."
for dir in chat_app/backend qa_bot/backend code_review_bot/backend enterprise_ai/backend; do
  name=$(basename $(dirname $(dirname $dir)))
  echo "  构建 $name ..."
  docker compose build "$name" || { echo "[ERROR] $name 构建失败"; exit 1; }
done
echo "  构建 nginx（直接用官方镜像，跳过）"

# 6. 启动服务
echo ""
echo "[2/3] 启动服务..."
docker compose up -d

# 7. 等待 MySQL 就绪
echo ""
echo "[3/3] 等待 MySQL 就绪..."
timeout=60
while [ $timeout -gt 0 ]; do
  if docker compose exec -T mysql mysqladmin ping -h localhost -p"$DB_PASSWORD" --silent &>/dev/null; then
    echo "MySQL 已就绪"
    break
  fi
  echo -n "."
  sleep 2
  timeout=$((timeout - 2))
done

# 8. 自动建库
echo ""
echo "创建数据库..."
for db in chat_app qa_bot code_review enterprise_ai; do
  docker compose exec -T mysql mysql -uroot -p"$DB_PASSWORD" -e \
    "CREATE DATABASE IF NOT EXISTS $db DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
  echo "  ✓ $db"
done

# 9. 状态汇总
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "后端 API 地址（Nginx 80 端口）："
echo "  chat_app       → http://$IP/chat"
echo "  qa_bot         → http://$IP/qa"
echo "  code_review    → http://$IP/review"
echo "  enterprise_ai  → http://$IP/enterprise"
echo ""
echo "健康检查：curl http://localhost/health"
echo "查看服务状态：docker compose ps"
echo "查看日志：docker compose logs -f [服务名]"
echo "停止服务：docker compose down"
echo ""
echo "===== 前端 Vercel 部署 ====="
echo "在各 frontend/ 目录的 Vercel 项目中设置环境变量："
echo "  chat_app       VITE_API_BASE=http://$IP/chat"
echo "  qa_bot         VITE_API_BASE=http://$IP/qa"
echo "  code_review    VITE_API_BASE=http://$IP/review"
echo "  enterprise_ai  VITE_API_BASE=http://$IP/enterprise"
