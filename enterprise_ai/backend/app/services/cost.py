"""Token 成本预估：单价表 + 用量落库 + 汇总报表。"""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..config import settings
from ..loggers import logger
from ..models import UsageLog


def _round4(x: float) -> float:
    return round(x, 6)


def chat_cost(model: str, prompt_tokens: int, completion_tokens: int) -> dict:
    """按模型单价估算一次 LLM 调用成本（元）。"""
    # 当前仅 qwen-max 建价目表；其余模型走保守兜底（同 max 单价 x 2，宁可高估）
    if "max" in model:
        in_price, out_price = settings.COST_QWEN_MAX_IN, settings.COST_QWEN_MAX_OUT
    else:
        in_price = settings.COST_QWEN_MAX_IN * 2
        out_price = settings.COST_QWEN_MAX_OUT * 2

    cost_in = _round4(prompt_tokens / 1000 * in_price)
    cost_out = _round4(completion_tokens / 1000 * out_price)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_input": cost_in,
        "cost_output": cost_out,
        "cost_total": _round4(cost_in + cost_out),
    }


def embedding_cost(total_tokens: int) -> tuple[int, float]:
    """embedding 成本，返回 (tokens, 元)。"""
    return total_tokens, _round4(total_tokens / 1000 * settings.COST_EMBEDDING_PER_1K)


def log_usage(
    db: Session,
    model: str,
    kind: str,
    usage: dict,
    ref_id: int | None = None,
) -> None:
    """写一条用量流水；失败不影响主流程。"""
    try:
        rec = UsageLog(
            model=model,
            kind=kind,
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            cost_input=usage.get("cost_input", 0.0) or 0.0,
            cost_output=usage.get("cost_output", 0.0) or 0.0,
            cost_total=usage.get("cost_total", 0.0) or 0.0,
            ref_id=ref_id,
        )
        db.add(rec)
        db.commit()
        logger.info(f"usage | {kind} {model} p={usage.get('prompt_tokens')} c={usage.get('completion_tokens')} cost=¥{usage.get('cost_total')}")
    except Exception as e:
        db.rollback()
        logger.warning(f"usage 落库失败: {e}")


def estimate_text_tokens(text: str) -> int:
    """无 usage 兜底：中英混合粗估（中文≈1字/token，英文≈4字符/token）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + other // 4)


def summarize(db: Session) -> dict:
    """累计与今日的成本汇总（供前端仪表展示）。"""
    def _agg(cond=None):
        stmt = select(
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost_input), 0.0),
            func.coalesce(func.sum(UsageLog.cost_output), 0.0),
            func.count(UsageLog.id),
        )
        if cond is not None:
            stmt = stmt.where(cond)
        row = db.execute(stmt).one()
        p, c, ci, co, n = row
        return {
            "calls": int(n),
            "prompt_tokens": int(p),
            "completion_tokens": int(c),
            "cost_input": round(float(ci), 4),
            "cost_output": round(float(co), 4),
            "cost_total": round(float(ci) + float(co), 4),
        }

    today_start = datetime.combine(date.today(), datetime.min.time())
    return {
        "total": _agg(),
        "today": _agg(UsageLog.created_at >= today_start),
    }
