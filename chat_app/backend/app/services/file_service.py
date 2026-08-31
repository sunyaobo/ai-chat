"""文件上传与文本抽取服务。"""
import os
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException

from ..config import settings

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ALLOWED_FILE_EXT = {".txt", ".md", ".csv", ".pdf", ".docx", ".doc"}
MAX_SIZE = 20 * 1024 * 1024  # 20 MB


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


async def save_upload(file: UploadFile) -> dict:
    """保存上传文件，返回 {type, url, name, size, path}。"""
    ext = _ext(file.filename or "")
    if ext not in (ALLOWED_IMAGE_EXT | ALLOWED_FILE_EXT):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="文件过大（>20MB）")

    # 按日期分目录，避免单目录文件过多
    rel_dir = "images" if ext in ALLOWED_IMAGE_EXT else "files"
    save_dir = settings.upload_path / rel_dir
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    abs_path = save_dir / filename
    abs_path.write_bytes(content)

    url = f"{settings.UPLOAD_URL_PREFIX}/{rel_dir}/{filename}"
    return {
        "type": "image" if ext in ALLOWED_IMAGE_EXT else "file",
        "url": url,
        "name": file.filename or filename,
        "size": len(content),
        "path": str(abs_path),
        "ext": ext,
    }


def extract_text(file_path: str, ext: str) -> str:
    """从文件中抽取纯文本，供拼入 LLM prompt。"""
    ext = ext.lower()
    if ext in (".txt", ".md", ".csv"):
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if ext in (".docx", ".doc"):
        import docx
        doc = docx.Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)
    return ""
