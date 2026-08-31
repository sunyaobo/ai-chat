"""自动代码审查路由：截图上传 + SSE 流式 Agent + 历史。"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .. import crud
from ..services import file_service, vision, agent_service

router = APIRouter(prefix="/api/review", tags=["review"])


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """上传报错截图，返回 {url, name, size}。"""
    info = await file_service.save_image(file)
    return {"url": info["url"], "name": info["name"], "size": info["size"]}


@router.post("/run")
async def run_review(payload: dict, request: Request, db: Session = Depends(get_db)):
    """流式执行自动代码审查（SSE）。

    事件：
      meta         {id}                     任务 id
      stage        {stage, message}         阶段提示（如截图识别）
      thought      {text}                   Agent 中间思考
      step_start   {tool, args}             工具开始调用
      step_result  {tool, output}           工具返回
      delta        {content}                最终报告增量
      done         {report}                 完整报告
      stopped/error {message}
    """
    input_text = (payload.get("error_text") or "").strip()
    images = payload.get("images") or []          # [{url,name,size}]
    if not input_text and not images:
        raise HTTPException(status_code=400, detail="请提供报错信息文本或报错截图")

    rec = crud.create_record(db, input_text, images)

    async def event_source():
        try:
            yield {"event": "meta", "data": json.dumps({"id": rec.id}, ensure_ascii=False)}

            # ---------- 阶段1：VL 模型提取截图中的报错 ----------
            extracted_parts: list[str] = []
            if input_text:
                extracted_parts.append(input_text)
                yield {"event": "stage", "data": json.dumps(
                    {"stage": "text", "message": "已接收文字描述"}, ensure_ascii=False)}

            for img in images:
                if await request.is_disconnected():
                    break
                rel = img["url"].replace(settings.UPLOAD_URL_PREFIX, "").lstrip("/")
                path = settings.upload_path / rel
                if not path.exists():
                    continue
                yield {"event": "stage", "data": json.dumps(
                    {"stage": "extract", "message": f"正在识别截图《{img.get('name')}》中的报错…"},
                    ensure_ascii=False)}
                # VL 调用是阻塞 IO，放线程避免卡事件循环
                text = await asyncio.to_thread(vision.extract_error_from_image, str(path))
                extracted_parts.append(f"[截图《{img.get('name')}》识别结果]\n{text}")

            if not extracted_parts:
                crud.finish_record(db, rec.id, "", [], status="error")
                yield {"event": "error", "data": json.dumps(
                    {"message": "未能获取任何报错信息"}, ensure_ascii=False)}
                return

            full_error_text = "\n\n".join(extracted_parts)

            # ---------- 阶段2：Agent 调查与生成 ----------
            report_buf: list[str] = []
            trace_acc: list[dict] = []

            async for evt in agent_service.run_review_agent(full_error_text):
                if await request.is_disconnected():
                    break
                name, data = evt["event"], evt["data"]
                if name == "delta":
                    report_buf.append(data["content"])
                elif name in ("thought", "step_start", "step_result"):
                    trace_acc.append({"type": name, **data})
                yield {"event": name, "data": json.dumps(data, ensure_ascii=False)}

            final_report = "".join(report_buf) or "(无报告)"
            crud.finish_record(
                db, rec.id, final_report, trace_acc,
                extracted_error=full_error_text, status="done",
            )
            yield {"event": "finalize", "data": json.dumps(
                {"id": rec.id, "status": "done"}, ensure_ascii=False)}

        except asyncio.CancelledError:
            crud.finish_record(db, rec.id, "(用户中断)", [], status="stopped")
            yield {"event": "stopped", "data": json.dumps(
                {"message": "任务已中止"}, ensure_ascii=False)}
            raise
        except Exception as e:
            crud.finish_record(db, rec.id, f"[错误] {e}", [], status="error")
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_source())


@router.get("/history")
def history(limit: int = 50, db: Session = Depends(get_db)):
    """历史记录列表。"""
    records = crud.list_records(db, limit=limit)
    return [
        {
            "id": r.id,
            "input_text": r.input_text,
            "images": r.images,
            "extracted_error": r.extracted_error,
            "report": r.report,
            "trace": r.trace,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in records
    ]


@router.get("/{record_id}")
def detail(record_id: int, db: Session = Depends(get_db)):
    """单条记录详情。"""
    r = crud.get_record(db, record_id)
    if not r:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {
        "id": r.id,
        "input_text": r.input_text,
        "images": r.images,
        "extracted_error": r.extracted_error,
        "report": r.report,
        "trace": r.trace,
        "status": r.status,
        "created_at": r.created_at,
    }


@router.delete("/{record_id}")
def remove(record_id: int, db: Session = Depends(get_db)):
    """删除记录。"""
    if not crud.delete_record(db, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}
