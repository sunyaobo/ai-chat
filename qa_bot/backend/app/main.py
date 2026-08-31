"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import qa
from .services import rag as rag_service
from .services import llm as llm_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) 建表（生产建议用 alembic 迁移）
    Base.metadata.create_all(bind=engine)
    # 2) 初始化 RAG：加载文档 + 切分 + 向量化入库（已存在则复用）
    rag_service.RAGService.instance().initialize()
    # 3) LLM 改用 DashScope API，无需预加载模型
    yield


app = FastAPI(title="QA Bot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(qa.router)


@app.get("/")
def root():
    return {"name": "QA Bot API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=False,  # 本地大模型加载耗时，开发期关闭 reload 避免重复加载
    )
