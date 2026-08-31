"""全局配置：从 .env 读取。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "enterprise_ai"

    # DashScope
    DASHSCOPE_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-max"
    EMBEDDING_MODEL: str = "text-embedding-v1"

    # Token 成本单价（元 / 1000 tokens），按阿里云公开牌价估算，可随时在 .env 覆盖
    COST_QWEN_MAX_IN: float = 0.0024
    COST_QWEN_MAX_OUT: float = 0.0096
    COST_EMBEDDING_PER_1K: float = 0.0007

    # RAG
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 4
    CHROMA_PERSIST_DIR: str = "./chroma_store"

    # 会话上下文：最多带入的历史轮数（1 轮 = user+assistant）
    HISTORY_ROUNDS: int = 5

    # 服务
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8003
    UPLOAD_DIR: str = "./uploads_docs"
    LOG_DIR: str = "./logs"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5176,http://127.0.0.1:5176"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        p = Path(self.UPLOAD_DIR).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_path(self) -> Path:
        p = Path(self.LOG_DIR).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
