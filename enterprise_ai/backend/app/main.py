"""FastAPI 应用入口：日志 + trace_id 中间件 + 静态托管前端 dist。"""
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .loggers import logger, setup_logging
from .routers import chat, docs

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"启动完成 | 端口 {settings.BACKEND_PORT} | 模型 {settings.LLM_MODEL}")
    yield


app = FastAPI(title="组件库智能顾问 API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """企业级请求日志：trace_id 贯穿，耗时统计。"""
    trace_id = request.headers.get("X-Trace-Id", uuid.uuid4().hex[:12])
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as e:
        dur = (time.perf_counter() - start) * 1000
        logger.error(f"[{trace_id}] {request.method} {request.url.path} 500 {dur:.1f}ms | {e}")
        raise
    dur = (time.perf_counter() - start) * 1000
    response.headers["X-Trace-Id"] = trace_id
    # SSE 流式响应的耗时是"首字节前时间"，仍具参考价值
    logger.info(f"[{trace_id}] {request.method} {request.url.path} -> {response.status_code} {dur:.1f}ms")
    return response


app.include_router(docs.router)
app.include_router(chat.router)


@app.get("/")
def root():
    return {"name": "组件库智能顾问 API", "docs": "/docs"}


# ---- 生产模式：托管前端构建产物（enterprise_ai/frontend/dist 存在时）----
from pathlib import Path

_frontend_dist = Path(__file__).resolve().parents[1].parent / "frontend" / "dist"


if (_frontend_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = _frontend_dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.BACKEND_HOST,
                port=settings.BACKEND_PORT, reload=False)
