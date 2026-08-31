"""SQLAlchemy ORM 模型：组件文档 / 会话 / 消息 / Token用量。"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Float, Integer, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import JSON

from .database import Base


class ComponentDoc(Base):
    """上传的组件库文档。"""
    __tablename__ = "component_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)          # 原始文件名
    path: Mapped[str] = mapped_column(String(512), nullable=False)          # 服务器存储路径
    ext: Mapped[str] = mapped_column(String(16), nullable=False)            # md/txt/pdf/docx/html
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 向量化消耗（embedding 计费）
    embed_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embed_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")  # ready/error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_doc_created", "created_at"),)


class Conversation(Base):
    """答疑会话。"""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    """会话消息，记录本条生成的 token 用量与成本。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conv_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)           # user/assistant
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)       # 本次检索限定文档
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)         # {prompt_tokens,completion_tokens,cost,cost_in,cost_out}
    cited_chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 引用片段 [{doc_name,content,score}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_msg_conv", "conv_id", "id"),)


class UsageLog(Base):
    """Token 用量流水：企业级成本报表数据源。"""
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)           # chat / embedding
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_input: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_output: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ref_id: Mapped[int] = mapped_column(Integer, nullable=True)             # 关联 msg_id 或 doc_id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_usage_created", "created_at"),)
