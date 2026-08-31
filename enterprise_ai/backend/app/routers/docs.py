"""组件文档管理路由：上传（含向量化）/ 列表 / 删除。"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..loggers import logger
from .. import crud
from ..services import ingest
from ..services.cost import embedding_cost, log_usage

router = APIRouter(prefix="/api/docs", tags=["docs"])

ALLOWED_EXT = {".md", ".txt", ".pdf", ".docx", ".html"}
MAX_SIZE = 30 * 1024 * 1024


@router.post("/upload")
async def upload_doc(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传组件文档：保存 → 抽取文本 → 切分 → 向量化入库 → 返回统计与 embedding 成本。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"仅支持 {sorted(ALLOWED_EXT)} 类型")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, "文件过大（>30MB）")
    if not content.strip():
        raise HTTPException(400, "文件为空")

    # 保存（hash 命名防冲突）
    name = file.filename or "unnamed"
    doc_row = crud.create_doc(db, name=name, path="", ext=ext.lstrip("."), size=len(content))
    save_path = settings.upload_path / "docs" / f"{doc_row.id}_{uuid.uuid4().hex[:8]}{ext}"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    doc_row.path = str(save_path)
    db.commit()

    try:
        text = ingest.extract_text(str(save_path), ext.lstrip("."))
        chunks = ingest.split_chunks(text)
        logger.info(f"doc#{doc_row.id} 《{name}》抽取 {len(text)} 字 → {len(chunks)} 切片")

        # 重传同文档 id 时防重复向量
        ingest.delete_doc_vectors(doc_row.id)
        chunk_count, tokens = ingest.add_doc_chunks(doc_row.id, chunks, {"name": name})
        e_tokens, e_cost = embedding_cost(tokens)
        crud.finish_doc(db, doc_row.id, chunk_count, e_tokens, e_cost)

        log_usage(db, settings.EMBEDDING_MODEL, "embedding",
                  {"prompt_tokens": e_tokens, "completion_tokens": 0,
                   "cost_input": e_cost, "cost_output": 0.0,
                   "cost_total": round(e_cost, 6)},
                  ref_id=doc_row.id)

        return {
            "id": doc_row.id, "name": name, "size": len(content),
            "chunks": chunk_count, "embed_tokens": e_tokens,
            "embed_cost": e_cost, "status": "ready",
        }
    except Exception as e:
        crud.finish_doc(db, doc_row.id, 0, 0, 0.0, status="error")
        logger.error(f"doc#{doc_row.id} 处理失败: {e}")
        raise HTTPException(500, f"文档处理失败: {e}")


@router.get("")
def list_docs(db: Session = Depends(get_db)):
    return [
        {
            "id": d.id, "name": d.name, "ext": d.ext, "size": d.size,
            "chunk_count": d.chunk_count, "embed_tokens": d.embed_tokens,
            "embed_cost": d.embed_cost, "status": d.status,
            "created_at": d.created_at,
        }
        for d in crud.list_docs(db)
    ]


@router.delete("/{doc_id}")
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    """删除文档记录并清理向量库。"""
    if not crud.delete_doc(db, doc_id):
        raise HTTPException(404, "文档不存在")
    ingest.delete_doc_vectors(doc_id)
    return {"ok": True}
