"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, Field


class ReviewResponse(BaseModel):
    id: int
    input_text: str
    images: list[dict] | None = None
    extracted_error: str | None = None
    report: str
    trace: list[dict] | None = None
    status: str
    created_at: datetime


class UploadOut(BaseModel):
    url: str
    name: str
    size: int
