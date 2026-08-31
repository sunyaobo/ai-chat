"""LLM 服务：基于 DashScope 兼容 OpenAI 协议。
- 文本消息用 LLM_TEXT_MODEL
- 含图片输入时自动切换 LLM_VL_MODEL
- 提供同步与流式两种调用方式
"""
from __future__ import annotations

from typing import AsyncIterator, Iterator
import asyncio
import json

from openai import OpenAI

from ..config import settings


def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )


def _has_image(messages: list[dict]) -> bool:
    """messages 中是否含 image_url 内容。"""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def _pick_model(messages: list[dict]) -> str:
    return settings.LLM_VL_MODEL if _has_image(messages) else settings.LLM_TEXT_MODEL


def build_messages(history: list[dict], user_text: str, file_text: str, attachments: list[dict]) -> list[dict]:
    """把历史、文本、附件拼成 OpenAI 兼容的 messages 列表。"""
    # 1) 拼接 user content：文本 + 文件抽取的纯文本 + 图片
    content_parts: list[dict] = []
    text_block = user_text
    if file_text:
        text_block = f"{user_text}\n\n[附件内容]\n{file_text}" if user_text else file_text

    if text_block:
        content_parts.append({"type": "text", "text": text_block})

    for att in attachments:
        if att.get("type") == "image":
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": att["url"]},
            })

    # 没有附件时退化为普通字符串内容（兼容非 VL 模型）
    if len(content_parts) == 1 and content_parts[0]["type"] == "text":
        user_msg: dict = {"role": "user", "content": text_block}
    elif not content_parts:
        user_msg = {"role": "user", "content": ""}
    else:
        user_msg = {"role": "user", "content": content_parts}

    # 2) 系统 prompt
    sys_prompt = {
        "role": "system",
        "content": "你是一个有帮助的中文助手。当用户上传文件时，文件内容已被提取并以纯文本形式附在消息中。",
    }
    return [sys_prompt] + list(history) + [user_msg]


def chat_complete(messages: list[dict]) -> str:
    """非流式：返回完整文本。"""
    client = _client()
    resp = client.chat.completions.create(
        model=_pick_model(messages),
        messages=messages,
        stream=False,
    )
    return resp.choices[0].message.content or ""


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """流式：yield 增量文本（同步生成器）。"""
    client = _client()
    stream = client.chat.completions.create(
        model=_pick_model(messages),
        messages=messages,
        stream=True,
        stream_options={"include_usage": False},
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece


async def chat_stream_async(messages: list[dict]) -> AsyncIterator[str]:
    """把同步流式包装成异步迭代器，配合 SSE 使用。

    使用独立线程 + asyncio.Queue 安全地桥接同步生成器与异步世界，
    避免 StopIteration 泄漏到 Future 中导致 RuntimeError。
    客户端断开时通过 cancelled 标志通知线程尽快退出。
    """
    import threading

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    _cancelled = {"flag": False}

    def _producer():
        try:
            for piece in chat_stream(messages):
                if _cancelled["flag"]:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    thread = threading.Thread(target=_producer, daemon=True)
    thread.start()

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    except BaseException:
        _cancelled["flag"] = True
        try:
            while True:
                queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        thread.join(timeout=2)
        raise
    else:
        thread.join(timeout=2)
