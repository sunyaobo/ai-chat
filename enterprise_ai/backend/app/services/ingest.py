"""组件文档接入服务：抽取文本 → 递归切分 → DashScope Embedding → Chroma 入库。

- 支持 md/txt/pdf/docx/html
- Chroma 以 doc_id 作 metadata，检索可按文档过滤；重传同 id 时先删后插
- embedding 走 dashscope SDK（每批 ≤25 条文本），记录消耗 token 用于成本预估
"""
from __future__ import annotations

import re
from pathlib import Path

import chromadb
import dashscope

from ..config import settings
from ..loggers import logger

_client = None


def _chroma() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _client


def _collection():
    return _chroma().get_or_create_collection(
        "component_docs",
        metadata={"hnsw:space": "cosine"},
    )


# ---------- 文本抽取 ----------

def extract_text(path: str, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in ("md", "txt"):
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext in ("docx", "doc"):
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    if ext == "html":
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        raw = re.sub(r"<(script|style)[\s\S]*?</\1>", "", raw, flags=re.I)
        # 块级标签换行
        raw = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw, flags=re.I)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
        text = re.sub(r"<[^>]+>", "", raw)
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join([ln for ln in lines if ln])
    raise ValueError(f"不支持的文档类型: {ext}")


# ---------- 切分 ----------

def split_chunks(text: str) -> list[str]:
    """递归切分：优先语义边界降级。"""
    seps = ["\n## ", "\n### ", "\n\n", "\n", "。", ";", "，", ""]
    size, overlap = settings.CHUNK_SIZE, settings.CHUNK_OVERLAP

    def _split(s: str, sep_idx: int) -> list[str]:
        if len(s) <= size:
            return [s] if s.strip() else []
        if sep_idx >= len(seps):
            # 硬切兜底
            out = []
            for i in range(0, len(s), size - overlap):
                out.append(s[i:i + size])
            return [x for x in out if x.strip()]
        sep = seps[sep_idx]
        parts = s.split(sep) if sep else [s]
        chunks: list[str] = []
        buf = ""
        for p in parts:
            cand = (buf + sep + p) if buf else p
            if len(cand) <= size:
                buf = cand
                continue
            if buf:
                chunks.append(buf)
                # 带重叠回滚
                buf = buf[-overlap:] + (sep or "") + p if overlap < len(buf) else p
            else:
                # 单段超长 → 更细粒度递归
                chunks.extend(_split(p, sep_idx + 1))
            buf = ""
        if buf:
            chunks.append(buf)
        return [c for c in (x.strip() for x in chunks) if c]

    return _split(text, 0)


# ---------- 向量化 ----------

def embed_texts(texts: list[str]) -> tuple[list[list[float]], int]:
    """DashScope 批量向量化（≤10条/批、每批总长限制），返回 (向量列表, 总token)。"""
    all_vecs: list[list[float]] = []
    total_tokens = 0
    BATCH = 10
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        resp = dashscope.TextEmbedding.call(
            model=settings.EMBEDDING_MODEL,
            input=batch,
            api_key=settings.DASHSCOPE_API_KEY,
            dimension=1024,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding 失败: {resp.code} {resp.message}")
        # 兼容不同 SDK 版本：text_index / index
        items = sorted(resp.output["embeddings"],
                       key=lambda e: e.get("text_index") or e.get("index") or 0)
        for item in items:
            all_vecs.append(item["embedding"])
        total_tokens += resp.usage.get("total_tokens", 0) or 0
    return all_vecs, total_tokens


def delete_doc_vectors(doc_id: int) -> None:
    """删除指定文档的全部向量（重建/删除场景防重复）。"""
    try:
        _collection().delete(where={"doc_id": doc_id})
    except Exception as e:
        logger.warning(f"删除旧向量失败(doc_id={doc_id}): {e}")


def add_doc_chunks(doc_id: int, chunks: list[str], metas_extra: dict | None = None) -> tuple[int, int]:
    """切块入库，返回 (成功块数, 消耗token)。"""
    if not chunks:
        return 0, 0
    vecs, tokens = embed_texts(chunks)
    coll = _collection()
    base_meta = {"doc_id": doc_id}
    if metas_extra:
        base_meta.update(metas_extra)

    B = 64
    for i in range(0, len(chunks), B):
        ids = [f"d{doc_id}_c{i + j}" for j in range(len(chunks[i:i + B]))]
        docs = chunks[i:i + B]
        metas = [{**base_meta} for _ in docs]
        coll.add(ids=ids, documents=docs, embeddings=vecs[i:i + B], metadatas=metas)
    return len(chunks), tokens


def query_chunks(question: str, doc_ids: list[int] | None, k: int) -> list[dict]:
    """检索 Top-K；doc_ids 为空则不限文档。"""
    vecs, _ = embed_texts([question])
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
    res = _collection().query(query_embeddings=vecs, n_results=k, where=where)
    out = []
    for i in range(len(res["documents"][0])):
        meta = (res.get("metadatas") or [[]])[0][i] or {}
        out.append({
            "content": res["documents"][0][i],
            "score": round(float(res["distances"][0][i]), 4),
            "doc_id": meta.get("doc_id"),
        })
    return out
