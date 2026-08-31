"""LangChain Agent 服务：Function Calling 循环 + SSE 事件产出。

工具集：
1. search_stackoverflow —— StackExchange 官方 API 检索相似问题
2. get_stackoverflow_answer —— 拉取某问题的最佳回答正文
3. run_python_code —— subprocess 沙箱执行修复/复现代码

Agent 主循环为手写 Function Calling 流式循环：
每轮流式调用绑定 tools 的 ChatOpenAI，增量累积文本与 tool_call_chunks；
有 tool_calls 则依次执行并把 ToolMessage 追加回消息列表进入下一轮，
无 tool_calls 则该轮文本即最终报告，逐段以 delta 事件流出。
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from typing import AsyncIterator

import requests
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ..config import settings
from . import sandbox


# ============================================================
# 工具实现（同步函数，Agent 循环中用 asyncio.to_thread 调度）
# ============================================================

def _strip_html(text: str) -> str:
    """简易 HTML 转纯文本（避免引入 bs4 重依赖）。"""
    text = re.sub(r"<blockquote>.*?</blockquote>", lambda m: "\n" + _strip_html(re.sub(r"</?blockquote>", "", m.group(0))), text, flags=re.S)
    text = re.sub(r"<code>", "`", text)
    text = re.sub(r"</code>", "`", text)
    text = re.sub(r"<br>|<br/>|</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def search_stackoverflow(query: str) -> str:
    """StackExchange API 检索 StackOverflow 相关问题（excerpts 接口）。"""
    try:
        resp = requests.get(
            "https://api.stackexchange.com/2.3/search/excerpts",
            params={
                "order": "desc",
                "sort": "relevance",
                "q": query,
                "site": settings.STACKEXCHANGE_SITE,
                "pagesize": settings.SEARCH_MAX_RESULTS,
                "filter": "default",
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        return f"[搜索失败] {e}"

    items = data.get("items", [])
    if not items:
        return f"未检索到与 '{query}' 相关的 StackOverflow 问题。建议换更核心的关键词（如异常类型名）再试。"

    lines = [f"共检索到 {len(items)} 条相关问题:"]
    for i, it in enumerate(items, 1):
        title = _strip_html(it.get("title", ""))
        excerpt = _strip_html(it.get("excerpt", ""))[:300]
        link = f"https://stackoverflow.com/questions/{it.get('question_id')}"
        answered = "已采纳答案" if it.get("is_accepted") else ("有回答" if it.get("is_answered") else "无回答")
        lines.append(
            f"\n[{i}] {title}\n"
            f"    状态: {answered} | 分数: {it.get('score', 0)}\n"
            f"    链接: {link} | question_id: {it.get('question_id')}\n"
            f"    摘要: {excerpt}"
        )
    lines.append("\n如需查看某问题的详细回答，请用 get_stackoverflow_answer 并传入 question_id。")
    return "\n".join(lines)


def get_stackoverflow_answer(question_id: int) -> str:
    """拉取指定问题的回答正文（按票数取前 2 条）。"""
    headers_default = {"site": settings.STACKEXCHANGE_SITE}
    try:
        # 1) 先拿问题标题，便于上下文对应
        q_resp = requests.get(
            f"https://api.stackexchange.com/2.3/questions/{question_id}",
            params={"site": headers_default["site"], "filter": "default"},
            timeout=15,
        )
        q_items = q_resp.json().get("items", [])
        title = _strip_html(q_items[0]["title"]) if q_items else "(未知标题)"

        # 2) 取回答正文
        a_resp = requests.get(
            f"https://api.stackexchange.com/2.3/questions/{question_id}/answers",
            params={
                "site": headers_default["site"],
                "order": "desc",
                "sort": "votes",
                "pagesize": 2,
                "filter": "withbody",
            },
            timeout=15,
        )
        answers = a_resp.json().get("items", [])
    except Exception as e:
        return f"[获取失败] {e}"

    if not answers:
        return f"问题 {question_id}（《{title}》）暂无回答。"

    parts = [f"问题《{title}》的高票回答:"]
    for i, a in enumerate(answers, 1):
        accepted = "[已采纳] " if a.get("is_accepted") else ""
        body = _strip_html(a.get("body", ""))
        if len(body) > 1500:
            body = body[:1500] + "...(截断)"
        parts.append(f"\n--- 回答{i} {accepted}(票数 {a.get('score', 0)}) ---\n{body}")
    return "\n".join(parts)


def run_code_tool(code: str) -> str:
    """沙箱执行 Python 代码并返回格式化结果。"""
    result = sandbox.run_python_code(code)
    return sandbox.format_run_result(result)


# 工具元数据（Function Calling 的 tools 描述）
TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_stackoverflow",
            "description": (
                "在 StackOverflow 上搜索与报错相关的问答。输入应为精炼的英文关键词"
                "（推荐组合：异常类型名 + 关键报错短语，例如 'TypeError list indices must be integers'）。"
                "返回相关问题的标题、摘要、链接和 question_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "英文搜索关键词"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stackoverflow_answer",
            "description": "获取某个 StackOverflow 问题的高票回答详细内容。需传入 search_stackoverflow 结果中的 question_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "integer", "description": "问题 ID"}
                },
                "required": ["question_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_code",
            "description": (
                "在隔离的 Python 子进程中执行代码（最长 15 秒），返回 stdout/stderr/退出码。"
                "用途：(1) 运行最小复现脚本确认报错原因；(2) 运行修复后的代码验证方案有效。"
                "仅支持标准库与已安装的第三方库；不要读写无关系统文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "完整的 Python 源码"}
                },
                "required": ["code"],
            },
        },
    },
]

_TOOL_FUNCS = {
    "search_stackoverflow": search_stackoverflow,
    "get_stackoverflow_answer": get_stackoverflow_answer,
    "run_python_code": run_code_tool,
}


# ============================================================
# Agent 主循环
# ============================================================

SYSTEM_PROMPT = """你是一名资深的代码调试专家 Agent，帮助开发者分析和修复代码报错。

你的工作流程：
1. 仔细分析用户提供的报错信息（可能来自截图提取），判断错误的根本原因。
2. 调用 search_stackoverflow 工具搜索相似问题；对高价值问题调用 get_stackoverflow_answer 深入了解社区解决方案。
3. 当你对修复方案有把握时，调用 run_python_code：
   - 先运行一段「最小复现代码」验证你对错误的理解；
   - 再运行「修复后的代码」证明修复有效、输出符合预期。
   - 若代码执行仍报错，请根据 stderr 修正后重试（最多重试 2 次）。
4. 所有调查完成后，输出最终的中文 Markdown 报告，结构如下：

## 一、错误原因分析
（结合堆栈与搜索到的资料解释为什么会出这个错）

## 二、修复方案
```python
（完整修复后的代码，含必要注释）
```

## 三、验证结果
（说明你实际运行的测试代码及输出，证明修复有效）

注意：
- 报告必须基于真实执行的工具结果，不要臆造验证过程。
- 若搜索与执行均无法定位问题，如实说明已知信息与推测。
- 最终回复只包含报告本身，不要再调用工具。"""


def _build_llm() -> tuple:
    """创建 DashScope 兼容模式下的 ChatOpenAI，并绑定工具定义。"""
    llm = ChatOpenAI(
        model=settings.LLM_TEXT_MODEL,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=0.2,
        streaming=True,
    )
    # bind_tools 走 OpenAI 兼容的 Function Calling 协议
    llm_with_tools = llm.bind_tools(TOOL_SPECS)
    return llm_with_tools


async def run_review_agent(error_text: str) -> AsyncIterator[dict]:
    """运行审查 Agent，逐步 yield SSE 事件。

    事件类型：
      thought     {text}              中间思考轮的文本
      step_start  {tool, args}       开始调用工具
      step_result {tool, output}     工具返回
      delta       {content}          最终报告增量
      done        {report, trace}    完成（含全程轨迹）
      error       {message}
    """
    llm_with_tools = _build_llm()

    messages: list = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"请帮我分析并修复以下代码报错：\n\n{error_text}"),
    ]

    trace: list[dict] = []

    def _record(evt: dict):
        trace.append(evt)

    try:
        for iteration in range(settings.AGENT_MAX_ITERATIONS):
            # ---------- 一轮流式 LLM 调用 ----------
            text_pieces: list[str] = []
            raw_tc: dict[int, dict] = {}

            async for chunk in llm_with_tools.astream(messages):
                content = chunk.content
                if isinstance(content, str) and content:
                    text_pieces.append(content)
                for tc in getattr(chunk, "tool_call_chunks", None) or []:
                    idx = tc.get("index")
                    idx = idx if idx is not None else len(raw_tc)
                    entry = raw_tc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    entry["id"] += tc.get("id") or ""
                    entry["name"] += tc.get("name") or ""
                    entry["args"] += tc.get("args") or ""

            round_text = "".join(text_pieces)
            tool_calls = []
            for _, e in sorted(raw_tc.items()):
                try:
                    args = json.loads(e["args"] or "{}")
                except json.JSONDecodeError:
                    args = {"_parse_error": True}
                tool_calls.append({"id": e["id"], "name": e["name"], "args": args})

            # ---------- 无工具调用 => 最终报告，逐段流式 ----------
            if not tool_calls:
                # 分段 delta（按 ~60 字符切块模拟自然流式节奏）
                step = 60
                for i in range(0, len(round_text), step):
                    yield {"event": "delta", "data": {"content": round_text[i:i + step]}}
                    await asyncio.sleep(0)

                report_md = round_text
                yield {"event": "done", "data": {"report": report_md, "trace": trace}}
                return

            # ---------- 有中间思考文本 => thought 事件 ----------
            if round_text.strip():
                evt = {"event": "thought", "data": {"text": round_text}}
                _record({**evt, "iteration": iteration + 1})
                yield evt

            # ---------- 执行每个工具调用 ----------
            messages.append(AIMessage(content=round_text, tool_calls=[
                {"name": t["name"], "args": t["args"], "id": t["id"]} for t in tool_calls
            ]))

            for t in tool_calls:
                name, args = t["name"], t["args"]

                start_evt = {
                    "event": "step_start",
                    "data": {"tool": name, "args": args},
                }
                _record({**start_evt, "iteration": iteration + 1})
                yield start_evt

                func = _TOOL_FUNCS.get(name)
                if func is None:
                    output = f"[错误] 未知的工具: {name}"
                elif args.get("_parse_error"):
                    output = "[错误] 工具参数不是合法 JSON，请检查格式后重新调用"
                else:
                    try:
                        if name == "run_python_code":
                            output = await asyncio.to_thread(func, args.get("code", ""))
                        elif name == "get_stackoverflow_answer":
                            output = await asyncio.to_thread(func, int(args.get("question_id", 0)))
                        else:
                            output = await asyncio.to_thread(func, args.get("query", ""))
                    except Exception as e:
                        output = f"[工具执行异常] {e}"

                result_evt = {
                    "event": "step_result",
                    "data": {"tool": name, "output": output},
                }
                _record(result_evt)
                yield result_evt

                messages.append(ToolMessage(
                    content=output[:6000],
                    tool_call_id=t["id"],
                    name=name,
                ))

        # 超过最大轮数仍未收敛
        msg = f"已达最大迭代次数（{settings.AGENT_MAX_ITERATIONS} 轮）强制停止"
        yield {"event": "error", "data": {"message": msg}}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        yield {"event": "error", "data": {"message": f"{type(e).__name__}: {e}"}}
