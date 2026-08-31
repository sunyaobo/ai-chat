"""全局配置：从 .env 读取。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "qa_bot"

    # DashScope（Embedding + LLM）
    DASHSCOPE_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-max"
    EMBEDDING_MODEL: str = "text-embedding-v1"

    # LLM 生成参数
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.7

    # RAG 文档与向量库
    DOC_PATH: str = r"d:\localModel\银行个金客户经理考核办法.docx"
    CHROMA_PERSIST_DIR: str = "./chroma_db_qa"
    CHROMA_COLLECTION: str = "qa_collection"
    RAG_TOP_K: int = 2
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # 服务
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8001
    CORS_ORIGINS: str = "http://localhost:5174,http://127.0.0.1:5174"

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


settings = Settings()
