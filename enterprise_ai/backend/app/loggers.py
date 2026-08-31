"""结构化日志配置：console + 滚动文件，含 trace_id 贯穿。"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import settings

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    """初始化根日志：双输出（终端 + logs/app.log 滚动 5MB x 3）。"""
    root = logging.getLogger()
    if root.handlers:                      # 防重复初始化（uvicorn reload 场景）
        return logging.getLogger("app")

    root.setLevel(settings.LOG_LEVEL)
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    fh = RotatingFileHandler(
        settings.log_path / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 收敛第三方库噪音
    for noisy in ("urllib3", "httpx", "openai", "chromadb", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("app")


logger = setup_logging()
