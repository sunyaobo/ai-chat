"""数据库 CRUD 操作。"""
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from .models import ReviewRecord


def create_record(
    db: Session,
    input_text: str = "",
    images: list[dict] | None = None,
) -> ReviewRecord:
    rec = ReviewRecord(input_text=input_text, images=images, status="running")
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def finish_record(
    db: Session,
    record_id: int,
    report: str,
    trace: list[dict],
    extracted_error: str | None = None,
    status: str = "done",
) -> None:
    rec = db.get(ReviewRecord, record_id)
    if rec:
        rec.report = report
        rec.trace = trace
        rec.status = status
        if extracted_error:
            rec.extracted_error = extracted_error
        db.commit()


def list_records(db: Session, limit: int = 50) -> list[ReviewRecord]:
    stmt = select(ReviewRecord).order_by(desc(ReviewRecord.id)).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_record(db: Session, record_id: int) -> ReviewRecord | None:
    return db.get(ReviewRecord, record_id)


def delete_record(db: Session, record_id: int) -> bool:
    rec = db.get(ReviewRecord, record_id)
    if not rec:
        return False
    db.delete(rec)
    db.commit()
    return True
