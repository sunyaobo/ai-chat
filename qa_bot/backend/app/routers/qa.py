"""问答路由：RAG 检索 + 本地模型生成，支持流式 SSE 与非流式。"""
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..services import rag as rag_service
from ..services import llm as llm_service

router = APIRouter(prefix="/api/qa", tags=["qa"])


def _retrieve(question: str):
    """检索 Top-K 相关切片，返回 (results, context, sources)。"""
    rag = rag_service.RAGService.instance()
    results = rag.retrieve(question)
    context = rag.build_context(results)
    sources = rag.to_sources(results)
    return results, context, sources


@router.post("")
def qa_answer(payload: dict, db: Session = Depends(get_db)):
    """非流式问答：检索 → 构造 RAG Prompt → 生成 → 落库 → 返回。"""
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    # 1) 检索
    _results, context, sources = _retrieve(question)

    # 2) 构造 RAG messages
    messages = llm_service.LLMService.instance().build_rag_messages(question, context)

    # 3) 生成
    try:
        answer = llm_service.LLMService.instance().generate(messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"模型生成失败: {e}")

    # 4) 落库
    rec = crud.create_record(db, question, answer, sources)

    return {
        "id": rec.id,
        "question": rec.question,
        "answer": rec.answer,
        "sources": sources,
        "created_at": rec.created_at,
    }


@router.post("/stream")
async def qa_stream(payload: dict, request: Request, db: Session = Depends(get_db)):
    """流式 SSE 问答。

    事件流：
      - meta:   问答记录 id（便于前端关联）
      - delta:  增量文本 {content}
      - done:   完整内容 + sources {content, sources, id}
      - error:  错误信息 {message}
    前端可用 AbortController 终止请求，会触发 GeneratorExit。
    """
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    # 1) 检索（同步，开销小）
    _results, context, sources = _retrieve(question)

    # 2) 构造 RAG messages
    messages = llm_service.LLMService.instance().build_rag_messages(question, context)

    # 3) 预建问答记录（answer 先空，流式完成后回写）
    rec = crud.create_record(db, question, "", sources)

    async def event_source():
        full = []
        try:
            # 先发 meta
            yield {
                "event": "meta",
                "data": json.dumps({"id": rec.id}, ensure_ascii=False),
            }

            async for piece in llm_service.LLMService.instance().generate_stream(messages):
                if await request.is_disconnected():
                    break
                full.append(piece)
                yield {
                    "event": "delta",
                    "data": json.dumps({"content": piece}, ensure_ascii=False),
                }

            final = "".join(full)
            crud.update_answer(db, rec.id, final or "(无内容)")
            yield {
                "event": "done",
                "data": json.dumps(
                    {"id": rec.id, "content": final, "sources": sources},
                    ensure_ascii=False,
                ),
            }

        except asyncio.CancelledError:
            # 客户端断开：把已生成内容存库
            final = "".join(full)
            crud.update_answer(db, rec.id, final or "(已终止)")
            yield {
                "event": "stopped",
                "data": json.dumps({"content": final}, ensure_ascii=False),
            }
            raise

        except Exception as e:
            crud.update_answer(db, rec.id, f"[错误] {e}")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_source())


# ---------- 历史记录 ----------

@router.get("/history")
def list_history(limit: int = 100, db: Session = Depends(get_db)):
    """列出问答历史（最新优先）。"""
    records = crud.list_records(db, limit=limit)
    return [
        {
            "id": r.id,
            "question": r.question,
            "answer": r.answer,
            "sources": r.sources,
            "created_at": r.created_at,
        }
        for r in records
    ]


@router.delete("/history/{record_id}")
def delete_history(record_id: int, db: Session = Depends(get_db)):
    """删除单条问答记录。"""
    if not crud.delete_record(db, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


@router.delete("/history")
def clear_history(db: Session = Depends(get_db)):
    """清空全部问答历史。"""
    count = crud.clear_records(db)
    return {"ok": True, "deleted": count}


# ---------- 向量库管理 ----------

@router.post("/rebuild")
def rebuild_index():
    """重建向量库（重新加载文档 + 切分 + 向量化）。"""
    rag = rag_service.RAGService.instance()
    count = rag.rebuild()
    return {"ok": True, "doc_count": count}


@router.get("/status")
def rag_status():
    """查看 RAG 状态。"""
    rag = rag_service.RAGService.instance()
    return {"doc_count": rag.doc_count}
