"""历史记录与会话管理路由。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud

router = APIRouter(prefix="/api/sessions", tags=["history"])


@router.get("")
def list_sessions_route(limit: int = 100, db: Session = Depends(get_db)):
    """列出所有会话（带最近消息预览与消息数）。"""
    return crud.list_sessions(db, limit=limit)


@router.post("")
def create_session_route(title: str | None = None, db: Session = Depends(get_db)):
    """新建会话。"""
    sess = crud.create_session(db, title)
    return {"id": sess.id, "title": sess.title, "created_at": sess.created_at}


@router.get("/{session_id}/messages")
def get_messages_route(session_id: int, db: Session = Depends(get_db)):
    """获取某个会话的全部消息。"""
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = crud.list_messages(db, session_id)
    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "attachments": m.attachments,
            "created_at": m.created_at,
        }
        for m in msgs
    ]


@router.delete("/{session_id}")
def delete_session_route(session_id: int, db: Session = Depends(get_db)):
    """删除整个会话（级联删除消息）。"""
    if not crud.delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.delete("/messages/{message_id}")
def delete_message_route(message_id: int, db: Session = Depends(get_db)):
    """删除单条消息（用户在前端点删除按钮时调用）。"""
    if not crud.delete_message(db, message_id):
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"ok": True}
