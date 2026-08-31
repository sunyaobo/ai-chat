"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, Field


class AttachmentOut(BaseModel):
    type: str           # image / file
    url: str
    name: str
    size: int | None = None


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    attachments: list[AttachmentOut] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_message: str | None = None      # 最近一条消息预览
    message_count: int = 0

    class Config:
        from_attributes = True


class SessionCreate(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    """聊天请求体：可携带历史、文本、附件 URL。"""
    session_id: int | None = None
    message: str = ""
    # 已上传好的附件（先调 /api/upload 拿到 url 再传到这里）
    attachments: list[dict] = Field(default_factory=list)
    # 是否流式
    stream: bool = True


class ChatResponse(BaseModel):
    session_id: int
    message: MessageOut
