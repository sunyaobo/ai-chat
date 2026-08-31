#!/bin/bash
# ============================================================
#  四合一 AI 应用 · 一键部署脚本（阿里云轻量应用服务器）
#
#  使用方式：
#    1. git clone <repo> && cd <repo>
#    2. cp .env.example .env && vim .env   # 填入密钥
#    3. bash deploy.sh
# ============================================================
set -e

echo "=========================================="
echo "  AI 应用集群部署"
echo "=========================================="

# 1. 检查 .env
if [ ! -f .env ]; then
  echo "[ERROR] .env 不存在，请先 cp .env.example .env 并填入密钥"
  exit 1
fi

# 2. 检查 Docker
if ! command -v docker &> /dev/null; then
  echo "[ERROR] Docker 未安装，请先安装："
  echo "  curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if ! docker compose version &> /dev/null; then
  echo "[ERROR] Docker Compose 未安装或版本过低"
  exit 1
fi

# 3. 检查 RAG 文档（qa_bot 需要）
if [ ! -f qa_bot/backend/data/银行个金客户经理考核办法.docx ]; then
  echo "[WARN] qa_bot RAG 文档不存在，请将 .docx 放到 qa_bot/backend/data/"
  echo "       （不影响其他项目启动，qa_bot 启动时 RAG 会报错跳过）"
fi

# 4. 构建并启动
echo ""
echo "[1/3] 构建镜像..."
docker compose build

echo ""
echo "[2/3] 启动服务..."
docker compose up -d

echo ""
echo "[3/3] 等待 MySQL 就绪..."
timeout=60
while [ $timeout -gt 0 ]; do
  if docker compose exec -T mysql mysqladmin ping -h localhost --silent &>/dev/null; then
    echo "MySQL 已就绪"
    break
  fi
  echo -n "."
  sleep 2
  timeout=$((timeout - 2))
done

# 5. 自动建库（4 个数据库）
echo ""
echo "创建数据库..."
for db in chat_app qa_bot code_review enterprise_ai; do
  docker compose exec -T mysql mysql -uroot -p"$DB_PASSWORD" -e \
    "CREATE DATABASE IF NOT EXISTS $db DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
  echo "  ✓ $db"
done

# 6. 状态汇总
echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "后端 API 地址（Nginx 80 端口）："
echo "  chat_app       → http://$(hostname -I | awk '{print $1}')/chat"
echo "  qa_bot         → http://$(hostname -I | awk '{print $1}')/qa"
echo "  code_review    → http://$(hostname -I | awk '{print $1}')/review"
echo "  enterprise_ai  → http://$(hostname -I | awk '{print $1}')/enterprise"
echo ""
echo "健康检查："
echo "  curl http://localhost/health"
echo ""
echo "前端部署到 Vercel："
echo "  在各 frontend/ 目录的 Vercel 项目中设置环境变量："
echo "    chat_app       VITE_API_BASE=http://<服务器IP>/chat"
echo "    qa_bot         VITE_API_BASE=http://<服务器IP>/qa"
echo "    code_review    VITE_API_BASE=http://<服务器IP>/review"
echo "    enterprise_ai  VITE_API_BASE=http://<服务器IP>/enterprise"
echo ""
echo "查看日志：docker compose logs -f"
echo "停止服务：docker compose down"
