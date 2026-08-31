"""聊天路由：上传文件、非流式聊天、SSE 流式聊天。"""
import json
import os
import asyncio

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..database import get_db
from .. import crud
from ..config import settings
from ..services import llm, file_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    """上传图片或文件，返回附件信息（含 URL）。"""
    info = await file_service.save_upload(file)
    # 拼成后端可访问的完整 URL（前端用相对路径或 host 都可）
    return {
        "type": info["type"],
        "url": info["url"],
        "name": info["name"],
        "size": info["size"],
    }


def _build_history(db: Session, session_id: int) -> list[dict]:
    """把 DB 中的历史消息转成 OpenAI messages 格式。"""
    msgs = crud.list_messages(db, session_id)
    history = []
    for m in msgs:
        if m.role == "user" and m.attachments:
            # 带 image 的历史 user 消息也用 content list
            parts: list[dict] = []
            if m.content:
                parts.append({"type": "text", "text": m.content})
            for att in m.attachments:
                if att.get("type") == "image":
                    parts.append({"type": "image_url", "image_url": {"url": att["url"]}})
                else:
                    parts.append({"type": "text", "text": f"[附件: {att.get('name')}] 已提取"})
            history.append({"role": "user", "content": parts or m.content})
        else:
            history.append({"role": m.role, "content": m.content})
    return history


def _extract_file_text(attachments: list[dict]) -> str:
    """对文件类型附件抽取纯文本。"""
    pieces = []
    for att in attachments:
        if att.get("type") == "file":
            url = att["url"]               # /uploads/files/xxx.pdf
            rel = url.replace(settings.UPLOAD_URL_PREFIX, "").lstrip("/")
            path = settings.upload_path / rel
            ext = os.path.splitext(path)[1]
            try:
                txt = file_service.extract_text(str(path), ext)
                if txt:
                    pieces.append(f"--- {att.get('name','文件')} ---\n{txt}")
            except Exception as e:
                pieces.append(f"[文件 {att.get('name')} 提取失败: {e}]")
    return "\n\n".join(pieces)


@router.post("/chat")
def chat(payload: dict, db: Session = Depends(get_db)):
    """非流式聊天接口。"""
    session_id = payload.get("session_id")
    user_text = payload.get("message", "") or ""
    attachments = payload.get("attachments") or []

    if not session_id:
        title = (user_text or "新对话")[:30]
        sess = crud.create_session(db, title)
        session_id = sess.id
    else:
        if not crud.get_session(db, session_id):
            raise HTTPException(status_code=404, detail="会话不存在")

    # 1) 落库 user 消息
    crud.add_message(db, session_id, "user", user_text, attachments or None)

    # 2) 构造给 LLM 的 messages
    history = _build_history(db, session_id)
    # _build_history 已经包含刚刚写入的 user 消息，故 user_text 传空
    file_text = _extract_file_text(attachments)
    messages = llm.build_messages(history[:-1], user_text, file_text, attachments)

    # 3) 调用 LLM
    try:
        answer = llm.chat_complete(messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"模型调用失败: {e}")

    # 4) 落库 assistant 消息
    amsg = crud.add_message(db, session_id, "assistant", answer, None)

    # 首条消息后更新会话标题
    if user_text:
        crud.update_session_title(db, session_id, user_text[:30])

    return {
        "session_id": session_id,
        "message": {
            "id": amsg.id,
            "session_id": session_id,
            "role": "assistant",
            "content": answer,
            "attachments": None,
            "created_at": amsg.created_at,
        },
    }


@router.post("/chat/stream")
async def chat_stream_route(payload: dict, request: Request, db: Session = Depends(get_db)):
    """流式 SSE 聊天接口。
    返回事件流，事件类型：
      - meta:      会话与消息 id
      - delta:     增量文本
      - done:      完整内容（含 session_id）
      - error:     错误信息
    前端可用 AbortController 终止请求，会触发 GeneratorExit。
    """
    session_id = payload.get("session_id")
    user_text = payload.get("message", "") or ""
    attachments = payload.get("attachments") or []

    if not session_id:
        title = (user_text or "新对话")[:30]
        sess = crud.create_session(db, title)
        session_id = sess.id
    else:
        if not crud.get_session(db, session_id):
            raise HTTPException(status_code=404, detail="会话不存在")

    # 1) 落库 user 消息
    crud.add_message(db, session_id, "user", user_text, attachments or None)

    # 2) 构造给 LLM 的 messages
    history = _build_history(db, session_id)
    file_text = _extract_file_text(attachments)
    messages = llm.build_messages(history[:-1], user_text, file_text, attachments)

    if user_text:
        crud.update_session_title(db, session_id, user_text[:30])

    # 预先创建 assistant 行，最终保存累加文本
    amsg = crud.add_message(db, session_id, "assistant", "", None)

    async def event_source():
        full = []
        try:
            # 先发 meta 让前端知道关联 id
            yield {"event": "meta", "data": json.dumps({
                "session_id": session_id, "message_id": amsg.id,
            }, ensure_ascii=False)}

            async for piece in llm.chat_stream_async(messages):
                if await request.is_disconnected():
                    break
                full.append(piece)
                yield {"event": "delta", "data": json.dumps({"content": piece}, ensure_ascii=False)}

            final = "".join(full)
            crud.update_message_content(db, amsg.id, final or "(无内容)")
            yield {"event": "done", "data": json.dumps({
                "session_id": session_id, "message_id": amsg.id, "content": final,
            }, ensure_ascii=False)}

        except asyncio.CancelledError:
            # 客户端断开：把已生成内容存库
            final = "".join(full)
            crud.update_message_content(db, amsg.id, final or "(已终止)")
            yield {"event": "stopped", "data": json.dumps({"content": final}, ensure_ascii=False)}
            raise

        except Exception as e:
            crud.update_message_content(db, amsg.id, f"[错误] {e}")
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_source())
