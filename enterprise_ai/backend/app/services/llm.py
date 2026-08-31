"""LLM 服务：qwen-max 流式生成 + usage 计量 + RAG Prompt 构造。"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from openai import OpenAI

from ..config import settings
from ..loggers import logger
from .cost import chat_cost, estimate_text_tokens


def _client() -> OpenAI:
    return OpenAI(api_key=settings.DASHSCOPE_API_KEY, base_url=settings.LLM_BASE_URL)


SYSTEM_BASE = (
    "你是一名资深前端组件库技术顾问，精通 Element Plus、Ant Design Vue 等主流组件库的 API 与最佳实践。"
    "回答要求：\n"
    "1. 优先依据提供的检索资料作答；资料不足以覆盖时可以补充通用知识，但要注明「以下为资料之外的补充」。\n"
    "2. 涉及代码时给完整可运行的示例（含 import 语句与模板结构），用 Markdown 代码块标明语言。\n"
    "3. 使用中文回答，条理清晰、简练专业。"
)

SYSTEM_CODE = SYSTEM_BASE + (
    "\n\n当前任务模式：用户需要【示例代码】。请给出：\n"
    "① 该组件/API 关键 props / events / slots 要点表格；\n"
    "② 一个完整的 .vue 单文件示例（<template> + <script setup>）；\n"
    "③ 常见坑位提醒。"
)


def build_messages(history: list[dict], question: str, context: str, mode: str) -> list[dict]:
    """组装多轮对话消息。history 为早期轮次 [{role, content}]。"""
    system = SYSTEM_CODE if mode == "code" else SYSTEM_BASE
    msgs: list[dict] = [{"role": "system", "content": system}]
    if context:
        msgs.append({
            "role": "system",
            "content": f"以下是检索到的相关文档片段，回答时请优先参考：\n\n{context}",
        })
    for h in history[-settings.HISTORY_ROUNDS * 2:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": question})
    return msgs


async def stream_chat(messages: list[dict]) -> AsyncIterator[tuple[str, dict | None]]:
    """流式生成。

    yield (piece, None) 若干次；最后 yield ("", usage_with_cost) 收尾。
    - usage 来自 API 返回（stream_options.include_usage），缺失时用文本长度估算兜底。
    """
    client = _client()
    # 兼容模式必须显式开启 include_usage 才返回用量
    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
    )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def _produce():
        try:
            for chunk in stream:
                loop.call_soon_threadsafe(q.put_nowait, chunk)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, SENTINEL)

    produce_task = loop.run_in_executor(None, _produce)

    usage_api: dict | None = None
    acc_answer: list[str] = []

    try:
        while True:
            item = await q.get()
            if item is SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            u = getattr(item, "usage", None)
            if u is not None:
                # 用量 chunk（choices 为空）
                usage_api = {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                }
                continue
            choices = getattr(item, "choices", None)
            if not choices:
                continue
            piece = choices[0].delta.content or ""
            if piece:
                acc_answer.append(piece)
                yield piece, None
    finally:
        # 确保生产者线程退出（SENTINEL 已入队则自然结束）
        try:
            await asyncio.wait_for(asyncio.shield(produce_task), timeout=5)
        except Exception:
            pass

    prompt_text = "".join(m.get("content", "") for m in messages)
    prompt_tokens = (usage_api or {}).get("prompt_tokens") or estimate_text_tokens(prompt_text)
    completion_tokens = (usage_api or {}).get("completion_tokens") or estimate_text_tokens(
        "".join(acc_answer))
    cost = chat_cost(settings.LLM_MODEL, prompt_tokens, completion_tokens)
    yield "", {**cost, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
