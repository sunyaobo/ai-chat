"""数据库 CRUD 操作。"""
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from .models import ChatSession, ChatMessage


def create_session(db: Session, title: str | None = None) -> ChatSession:
    session = ChatSession(title=title or "新对话")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: int) -> ChatSession | None:
    return db.get(ChatSession, session_id)


def update_session_title(db: Session, session_id: int, title: str) -> None:
    sess = db.get(ChatSession, session_id)
    if sess:
        sess.title = title[:255]
        db.commit()


def list_sessions(db: Session, limit: int = 100) -> list[dict]:
    """列出会话，带最近一条消息预览与消息数。"""
    stmt = (
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            ChatSession.updated_at,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(desc(ChatSession.updated_at))
        .limit(limit)
    )
    rows = db.execute(stmt).all()

    # 取每个会话最后一条消息内容
    result = []
    for r in rows:
        last_msg = (
            db.query(ChatMessage.content)
            .filter(ChatMessage.session_id == r.id)
            .order_by(desc(ChatMessage.id))
            .first()
        )
        preview = (last_msg[0] if last_msg else "")[:60]
        result.append({
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "message_count": r.message_count,
            "last_message": preview,
        })
    return result


def delete_session(db: Session, session_id: int) -> bool:
    sess = db.get(ChatSession, session_id)
    if not sess:
        return False
    db.delete(sess)  # 级联删除消息
    db.commit()
    return True


def add_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    attachments: list[dict] | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        attachments=attachments,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(db: Session, session_id: int) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )


def delete_message(db: Session, message_id: int) -> bool:
    msg = db.get(ChatMessage, message_id)
    if not msg:
        return False
    db.delete(msg)
    db.commit()
    return True


def update_message_content(db: Session, message_id: int, content: str) -> None:
    msg = db.get(ChatMessage, message_id)
    if msg:
        msg.content = content
        db.commit()
