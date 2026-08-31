"""数据库 CRUD 操作。"""
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from .models import QARecord


def create_record(
    db: Session,
    question: str,
    answer: str = "",
    sources: list[dict] | None = None,
) -> QARecord:
    rec = QARecord(question=question, answer=answer, sources=sources)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def update_answer(db: Session, record_id: int, answer: str) -> None:
    rec = db.get(QARecord, record_id)
    if rec:
        rec.answer = answer
        db.commit()


def list_records(db: Session, limit: int = 100) -> list[QARecord]:
    stmt = select(QARecord).order_by(desc(QARecord.id)).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_record(db: Session, record_id: int) -> QARecord | None:
    return db.get(QARecord, record_id)


def delete_record(db: Session, record_id: int) -> bool:
    rec = db.get(QARecord, record_id)
    if not rec:
        return False
    db.delete(rec)
    db.commit()
    return True


def clear_records(db: Session) -> int:
    """清空全部问答历史，返回删除条数。"""
    count = db.query(QARecord).count()
    db.query(QARecord).delete()
    db.commit()
    return count
