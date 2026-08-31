"""SQLAlchemy ORM 模型。"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import JSON

from .database import Base


class QARecord(Base):
    """问答历史记录：一次提问 + 一条回答 + 命中的参考资料。"""
    __tablename__ = "qa_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 命中的检索片段：[{content, score}, ...]
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_created", "created_at"),)
