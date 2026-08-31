# 企业级 AI 后端镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再拷代码
COPY app ./app
COPY run.py .

# 运行时挂载：数据库经网络连 mysql 服务；uploads/chroma/logs 建议持久化卷
EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import requests;requests.get('http://127.0.0.1:8003/',timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
