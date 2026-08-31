"""全局配置：从 .env 读取。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "chat_app"

    # DashScope
    DASHSCOPE_API_KEY: str = ""
    LLM_TEXT_MODEL: str = "qwen-max"
    LLM_VL_MODEL: str = "qwen-vl-max-latest"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 服务
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000
    UPLOAD_DIR: str = "./uploads"
    UPLOAD_URL_PREFIX: str = "/uploads"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

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


settings = Settings()
