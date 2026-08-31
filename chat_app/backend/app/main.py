"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import history, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保表存在（生产建议用 alembic 迁移）
    Base.metadata.create_all(bind=engine)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Chat App API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件：上传的图片/文件对外可访问
app.mount(settings.UPLOAD_URL_PREFIX, StaticFiles(directory=str(settings.upload_path)), name="uploads")

app.include_router(history.router)
app.include_router(chat.router)


@app.get("/")
def root():
    return {"name": "Chat App API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True,
    )
