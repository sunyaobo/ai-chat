"""数据库 CRUD。"""
from datetime import datetime

from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session

from .models import ComponentDoc, Conversation, ChatMessage


# ---------- 文档 ----------

def create_doc(db: Session, name: str, path: str, ext: str, size: int) -> ComponentDoc:
    doc = ComponentDoc(name=name, path=path, ext=ext, size=size)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def finish_doc(db: Session, doc_id: int, chunk_count: int, embed_tokens: int, embed_cost: float,
               status: str = "ready") -> None:
    d = db.get(ComponentDoc, doc_id)
    if d:
        d.chunk_count = chunk_count
        d.embed_tokens = embed_tokens
        d.embed_cost = embed_cost
        d.status = status
        db.commit()


def list_docs(db: Session) -> list[ComponentDoc]:
    return list(db.execute(select(ComponentDoc).order_by(desc(ComponentDoc.id))).scalars().all())


def delete_doc(db: Session, doc_id: int) -> bool:
    d = db.get(ComponentDoc, doc_id)
    if not d:
        return False
    db.delete(d)
    db.commit()
    return True


def doc_names_by_ids(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.execute(select(ComponentDoc.id, ComponentDoc.name).where(ComponentDoc.id.in_(ids))).all()
    return {r[0]: r[1] for r in rows}


# ---------- 会话与消息 ----------

def create_conversation(db: Session, title: str = "新会话") -> Conversation:
    conv = Conversation(title=title[:120])
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation(db: Session, conv_id: int) -> Conversation | None:
    return db.get(Conversation, conv_id)


def list_conversations(db: Session, limit: int = 50) -> list[Conversation]:
    return list(db.execute(select(Conversation).order_by(desc(Conversation.id)).limit(limit)).scalars().all())


def add_message(db: Session, conv_id: int, role: str, content: str,
                usage: dict | None = None, doc_ids: list[int] | None = None,
                cited: list[dict] | None = None) -> ChatMessage:
    m = ChatMessage(conv_id=conv_id, role=role, content=content,
                    usage=usage, doc_ids=doc_ids, cited_chunks=cited)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def conversation_messages(db: Session, conv_id: int, exclude_last_assistant: bool = False):
    stmt = select(ChatMessage).where(ChatMessage.conv_id == conv_id).order_by(ChatMessage.id)
    msgs = list(db.execute(stmt).scalars().all())
    # 多轮上下文：去掉最后一条 assistant 的 usage 无关紧要，直接全部返回由调用方裁剪
    return msgs


def last_title_from_question(db: Session, conv_id: int, question: str) -> None:
    """用首条问题更新会话标题。"""
    conv = db.get(Conversation, conv_id)
    if conv and conv.title in ("新会话", ""):
        conv.title = (question or "新会话")[:60]
        db.commit()
