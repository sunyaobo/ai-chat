"""启动脚本：从 backend 目录运行，确保相对路径与 .env 正确加载。

用法（在 backend 目录下）：
    d:/localModel/venv/Scripts/python.exe run.py
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=False,  # 本地大模型加载耗时，关闭 reload 避免重复加载
    )
