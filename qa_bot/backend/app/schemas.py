"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """问答请求。"""
    question: str
    stream: bool = True


class SourceItem(BaseModel):
    content: str
    score: float


class QAResponse(BaseModel):
    """非流式问答响应。"""
    id: int
    question: str
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    created_at: datetime


class QAHistoryItem(BaseModel):
    id: int
    question: str
    answer: str
    sources: list[dict] | None = None
    created_at: datetime
