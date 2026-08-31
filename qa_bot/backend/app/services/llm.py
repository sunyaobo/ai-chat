"""LLM 服务：DashScope qwen-max 流式生成（OpenAI 兼容协议）。

- 无需本地 GPU，通过 DashScope API 调用 qwen-max
- 流式：后台线程消费 openai stream，asyncio.Queue 桥接到异步事件循环
- 接口保持与原本地模型版本一致：build_rag_messages / generate / generate_stream
"""
from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator

from openai import OpenAI

from ..config import settings


class LLMService:
    """单例：通过 DashScope API 提供 LLM 生成能力。"""

    _instance: "LLMService | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._client: OpenAI | None = None

    @classmethod
    def instance(cls) -> "LLMService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self._client

    def load(self) -> None:
        """兼容旧接口：API 模式无需预加载，空实现。"""
        pass

    @staticmethod
    def build_rag_messages(question: str, context: str) -> list[dict]:
        """构造 RAG Prompt 为 chat messages（system + user）。"""
        system_prompt = (
            "你是一名银行考核领域的助手。请根据下面提供的参考资料回答用户问题。"
            '如果资料中没有相关信息，请直接回答「资料中未提及」。'
            "回答要简洁、准确，并尽量引用资料中的原文。"
        )
        user_prompt = f"参考资料:\n{context}\n\n用户问题: {question}"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def generate(self, messages: list[dict]) -> str:
        """非流式：返回完整文本。"""
        client = self._get_client()
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        return resp.choices[0].message.content or ""

    async def generate_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式：yield 增量文本（异步生成器）。

        后台线程消费 openai 同步流式迭代器，通过 asyncio.Queue 推到事件循环。
        """
        client = self._get_client()
        stream = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            stream=True,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce():
            try:
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            chunk.choices[0].delta.content,
                        )
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _produce)

        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            pass
