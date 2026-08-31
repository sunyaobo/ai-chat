"""Gradio 快速 Demo：组件库智能顾问（Gradio 6.x）。

与自研前端并行存在，消费同一套 FastAPI 服务（多端复用同一 API）：
- 文档上传/选择 → POST /api/docs/upload、GET /api/docs
- 流式答疑     → POST /api/chat/stream（SSE）
- 成本面板     → GET /api/chat/usage/summary

运行：
    d:/localModel/venv/Scripts/python.exe app.py
启动后访问 http://127.0.0.1:7861
"""
from __future__ import annotations

import json

import gradio as gr
import requests

API = "http://127.0.0.1:8003"
TITLE = "🧩 组件库智能顾问（Gradio Demo）"
DESC = "上传 Element Plus / Ant Design 等组件库文档，AI 解答使用疑问并生成示例代码"

CSS = """
.gradio-container {max-width: 1200px !important; margin: 0 auto;}
footer {visibility: hidden}
"""


# ---------------- API 封装 ----------------

def api_upload(file_obj) -> str:
    if not file_obj:
        return "⚠️ 请先选择文件"
    path = str(file_obj).replace("\\", "/")
    name = path.split("/")[-1]
    with open(path, "rb") as f:
        resp = requests.post(f"{API}/api/docs/upload",
                             files={"file": (name, f)}, timeout=300)
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        return f"❌ 上传失败：{detail}"
    d = resp.json()
    return (f"✅ 已入库《{d['name']}》｜切片 {d['chunks']} 块｜"
            f"消耗 {d['embed_tokens']} tokens ≈ ¥{d['embed_cost']}")


def api_docs() -> tuple[list[str], dict]:
    """返回 checkbox 选项列表与 label->doc_id 映射。"""
    try:
        docs = requests.get(f"{API}/api/docs", timeout=30).json()
    except Exception:
        docs = []
    labels = [f"#{d['id']} {d['name']} ({d['chunk_count']}块)" for d in docs]
    mapping = {label: d["id"] for label, d in zip(labels, docs)}
    return labels, mapping


def api_summary_md() -> str:
    try:
        s = requests.get(f"{API}/api/chat/usage/summary", timeout=30).json()
    except Exception as e:
        return f"(成本面板暂不可用: {e})"
    t, td = s["total"], s["today"]
    tp = td["prompt_tokens"] + td["completion_tokens"]
    tc = t["prompt_tokens"] + t["completion_tokens"]
    return (f"**💰 今日** {td['calls']} 次 · {tp} tokens · ¥{td['cost_total']:.4f}"
            f"&nbsp;&nbsp;|&nbsp;&nbsp;**累计** {t['calls']} 次 · {tc} tokens · ¥{t['cost_total']:.4f}")


def _sse_stream(payload: dict):
    """逐行消费后端 SSE，yield (event_name, data_dict)。"""
    with requests.post(f"{API}/api/chat/stream", json=payload,
                       stream=True, timeout=600) as r:
        if r.status_code != 200:
            yield "error", {"message": f"HTTP {r.status_code}"}
            return
        ev = None
        for raw in r.iter_lines(chunk_size=1, decode_unicode=True):
            if not raw or raw.startswith(":"):
                continue
            if raw.startswith("event:"):
                ev = raw[6:].strip()
                continue
            if raw.startswith("data:") and ev:
                body = raw[5:].strip()
                try:
                    data = json.loads(body)
                except Exception:
                    continue
                yield ev, data
                if ev in ("done", "error", "stopped"):
                    break


def _render_answer(answer: str, citations: list[dict], usage: dict | None) -> str:
    parts = []
    if citations:
        cites = "\n".join(f"- 《{c['doc_name']}》（相似度 {c['score']}）"
                          for c in citations[:3])
        parts.append(f"> 📎 引用片段\n{cites}\n")
    parts.append(answer)
    if usage:
        p, c = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        parts.append(f"\n---\n`用量: {p}+{c}={p + c} tokens · 预估 ¥{usage.get('cost_total', 0):.4f}`")
    return "\n".join(parts)


def _as_text(content) -> str:
    """归一化消息内容。

    Gradio 6 在 postprocess→preprocess 往返后会把 content 规范化为
    内容片段列表（如 [{"type": "text", "text": "..."}]），这里统一还原成字符串。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
            else:
                parts.append(str(p))
        return "\n".join(x for x in parts if x)
    if content is None:
        return ""
    return str(content)


def submit_message(message, history):
    """把用户消息追加为 messages 格式。"""
    if not message or not message.strip():
        return history
    return [*history, {"role": "user", "content": message.strip()}]


def respond(history, doc_labels, mode, state):
    """主对话生成函数：流式更新最后一条 assistant 消息。"""
    if not history or history[-1]["role"] != "user":
        yield history, gr.update()
        return

    message = _as_text(history[-1]["content"]).strip()
    if not message:
        yield history, gr.update()
        return
    doc_map = state.get("_doc_map", {})
    payload = {
        "question": message,
        "conversation_id": state.get("conv_id"),
        "doc_ids": [doc_map[l] for l in (doc_labels or []) if l in doc_map],
        "mode": mode,
    }

    def _set_assistant(text: str):
        h = list(history)
        if h and h[-1]["role"] == "assistant":
            h[-1] = {**h[-1], "content": text}
        else:
            h.append({"role": "assistant", "content": text})
        return h

    answer_parts: list[str] = []
    citations: list[dict] = []

    try:
        for ev, data in _sse_stream(payload):
            if ev == "meta":
                state["conv_id"] = data.get("conversation_id")
            elif ev == "cite":
                citations = data
            elif ev == "delta":
                answer_parts.append(data.get("content", ""))
                yield _set_assistant("".join(answer_parts)), gr.update()
            elif ev == "done":
                final_md = _render_answer("".join(answer_parts),
                                          citations, data.get("usage"))
                yield _set_assistant(final_md), api_summary_md()
                return
            elif ev in ("error", "stopped"):
                yield _set_assistant(f"❌ {data.get('message', '已中止')}"), api_summary_md()
                return
    finally:
        pass

    if not any(h["role"] == "assistant" for h in history):
        yield _set_assistant("".join(answer_parts) or "(无输出)"), gr.update()


def refresh_docs(state):
    labels, mapping = api_docs()
    return labels, {**state, "_doc_map": mapping}, api_summary_md()


def on_uploaded(file_obj, state):
    msg = api_upload(file_obj)
    labels, mapping = api_docs()
    return msg, labels, {**state, "_doc_map": mapping}, api_summary_md()


# ---------------- UI ----------------

with gr.Blocks(title=TITLE) as demo:
    conv_state = gr.State({"conv_id": None, "_doc_map": {}})

    gr.Markdown(f"# {TITLE}\n{DESC}")

    with gr.Row():
        # ---- 左栏：知识库 ----
        with gr.Column(scale=1, variant="panel"):
            gr.Markdown("## 📁 知识库")
            up_file = gr.File(label="上传组件文档",
                              file_types=[".md", ".txt", ".pdf", ".docx", ".html"])
            up_out = gr.Markdown("上传后自动切分并向量化入库")
            refresh_btn = gr.Button("🔄 刷新文档列表")
            docs_cb = gr.CheckboxGroup(label="检索范围（不选 = 仅通用回答）",
                                       choices=[])
            mode_radio = gr.Radio(["qa", "code"], value="qa",
                                  label="模式",
                                  info="qa=解答使用疑问 | code=侧重示例代码")
            summary_md = gr.Markdown(api_summary_md())

            up_file.upload(
                on_uploaded,
                inputs=[up_file, conv_state],
                outputs=[up_out, docs_cb, conv_state, summary_md],
            )
            refresh_btn.click(
                refresh_docs,
                inputs=[conv_state],
                outputs=[docs_cb, conv_state, summary_md],
            )

        # ---- 右栏：对话 ----
        with gr.Column(scale=2, variant="panel"):
            chatbot = gr.Chatbot(height=540, label="智能顾问",
                                 placeholder="发送问题开始对话…")
            with gr.Row():
                msg_box = gr.Textbox(show_label=False, scale=5,
                                     placeholder="例如：el-table 怎么自定义列内容？",
                                     autofocus=True,
                                     container=False)
                send_btn = gr.Button("发送", variant="primary", scale=1)
            clear_btn = gr.Button("🗑 新会话")

            msg_box.submit(
                submit_message,
                [msg_box, chatbot], chatbot,
            ).then(
                respond,
                [chatbot, docs_cb, mode_radio, conv_state],
                [chatbot, summary_md],
            ).then(
                lambda: "", None, msg_box,
            )

            send_btn.click(
                submit_message,
                [msg_box, chatbot], chatbot,
            ).then(
                respond,
                [chatbot, docs_cb, mode_radio, conv_state],
                [chatbot, summary_md],
            ).then(
                lambda: "", None, msg_box,
            )

            clear_btn.click(lambda: [], None, chatbot)


if __name__ == "__main__":
    demo.queue(max_size=16).launch(server_name="127.0.0.1", server_port=7861,
                                   show_error=True, inbrowser=False, css=CSS)
