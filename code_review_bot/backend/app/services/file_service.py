"""文件上传服务：保存截图，返回可访问 URL。"""
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException

from ..config import settings

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_SIZE = 20 * 1024 * 1024  # 20 MB


async def save_image(file: UploadFile) -> dict:
    """保存上传的报错截图。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"仅支持图片类型: {sorted(ALLOWED_IMAGE_EXT)}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="图片过大（>20MB）")

    save_dir = settings.upload_path / "images"
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    abs_path = save_dir / filename
    abs_path.write_bytes(content)

    return {
        "url": f"{settings.UPLOAD_URL_PREFIX}/images/{filename}",
        "name": file.filename or filename,
        "size": len(content),
        "path": str(abs_path),
    }
