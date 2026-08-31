"""SQLAlchemy ORM 模型。"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import JSON

from .database import Base


class ReviewRecord(Base):
    """自动代码审查任务记录。"""
    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 用户输入的报错信息原文
    input_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 上传的截图（相对 URL 列表）
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # VL 模型从截图提取的报错文本
    extracted_error: Mapped[str] = mapped_column(Text, nullable=True)
    # Agent 最终报告（Markdown：原因分析 + 修复代码 + 测试结论）
    report: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Agent 执行轨迹：[{type: thought/step_start/step_result, ...}]
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # running / done / error / stopped
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_created", "created_at"),)
