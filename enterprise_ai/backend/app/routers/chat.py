"""智能顾问问答路由：RAG 检索 + 多轮流式生成 + usage 计量。"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..loggers import logger
from .. import crud
from ..services import ingest, llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(payload: dict, request: Request, db: Session = Depends(get_db)):
    """SSE 流式答疑。

    payload: {question, conversation_id?, doc_ids?, mode?("qa"|"code")}
    事件：
      meta     {conversation_id}
      cite     {citations:[{doc_name,content,score}]}   检索引用（回答前先发）
      delta    {content}
      done     {content, usage:{tokens,cost...}, message_id}
      error/stopped {message}
    """
    question = (payload.get("question") or "").strip()
    if isinstance(question, list):      # 边界防御：内容片段列表还原为字符串
        question = "\n".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in question)
    question = str(question).strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    conv_id = payload.get("conversation_id")
    doc_ids = [int(i) for i in (payload.get("doc_ids") or [])]
    mode = payload.get("mode", "qa")

    # 会话：不存在则新建（标题取首问）
    if conv_id and crud.get_conversation(db, int(conv_id)):
        conv_id = int(conv_id)
    else:
        conv_id = crud.create_conversation(db, question).id
        crud.last_title_from_question(db, conv_id, question)

    # 存用户消息
    crud.add_message(db, conv_id, "user", question, doc_ids=doc_ids)

    async def event_source():
        try:
            yield {"event": "meta", "data": json.dumps(
                {"conversation_id": conv_id}, ensure_ascii=False)}

            # ---------- RAG 检索 ----------
            citations: list[dict] = []
            context = ""
            if doc_ids:
                names = crud.doc_names_by_ids(db, doc_ids)
                hits = ingest.query_chunks(question, doc_ids, settings.RAG_TOP_K)
                for h in hits:
                    citations.append({
                        "doc_name": names.get(h.get("doc_id"), f"文档{h.get('doc_id')}"),
                        "content": h["content"],
                        "score": h["score"],
                    })
                context = "\n\n".join(
                    f"【片段{i + 1}｜来源《{c['doc_name']}》】\n{c['content']}"
                    for i, c in enumerate(citations))
                yield {"event": "cite", "data": json.dumps(citations, ensure_ascii=False)}
                logger.info(f"conv#{conv_id} 检索命中 {len(citations)} 片段")

            # ---------- 历史轮次 ----------
            msgs_rows = crud.conversation_messages(db, conv_id)
            history = [
                {"role": m.role, "content": m.content}
                for m in msgs_rows[:-1]          # 刚存的 user 已作为本轮 question，排除
            ]

            messages = llm.build_messages(history, question, context, mode)

            # ---------- 流式生成 ----------
            acc: list[str] = []
            usage_final: dict | None = None
            async for piece, usage in llm.stream_chat(messages):
                if await request.is_disconnected():
                    break
                if piece:
                    acc.append(piece)
                    yield {"event": "delta", "data": json.dumps(
                        {"content": piece}, ensure_ascii=False)}
                elif usage:
                    usage_final = usage

            answer = "".join(acc) or "(无内容)"
            msg_row = crud.add_message(db, conv_id, "assistant", answer,
                                       usage=usage_final, doc_ids=doc_ids,
                                       cited=citations or None)
            if usage_final:
                from ..services.cost import log_usage
                log_usage(db, settings.LLM_MODEL, "chat",
                          usage_final, ref_id=msg_row.id)
            yield {"event": "done", "data": json.dumps({
                "message_id": msg_row.id,
                "content": answer,
                "usage": usage_final or {},
            }, ensure_ascii=False)}

        except asyncio.CancelledError:
            yield {"event": "stopped", "data": json.dumps(
                {"message": "已中止"}, ensure_ascii=False)}
            raise
        except Exception as e:
            logger.error(f"chat stream 异常: {e}")
            yield {"event": "error", "data": json.dumps(
                {"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_source())


@router.get("/conversations")
def conversations(limit: int = 50, db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "created_at": c.created_at}
            for c in crud.list_conversations(db, limit)]


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int, db: Session = Depends(get_db)):
    rows = crud.conversation_messages(db, conv_id)
    return [
        {
            "id": m.id, "role": m.role, "content": m.content,
            "usage": m.usage, "cited_chunks": m.cited_chunks,
            "created_at": m.created_at,
        }
        for m in rows
    ]


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = crud.get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    rows = crud.conversation_messages(db, conv_id)
    for m in rows:
        db.delete(m)
    db.delete(conv)
    db.commit()
    return {"ok": True}


# ---------- 成本报表 ----------

@router.get("/usage/summary")
def usage_summary(db: Session = Depends(get_db)):
    from ..services.cost import summarize
    return summarize(db)
