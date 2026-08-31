"""RAG 服务：文档加载 + 智能递归切分 + 向量化 + 相似度检索。

- 文档：D:/银行个金客户经理考核办法.docx
- 切分：RecursiveCharacterTextSplitter（中文 separators）
- 向量化：DashScopeEmbeddings（文档与查询共用同一 Embedding 模型）
- 向量库：Chroma（ip 内积相似度，持久化）
- 检索：similarity_search_with_score，返回 Top-K
"""
from __future__ import annotations

import os
import threading

from langchain_community.document_loaders import Docx2txtLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings


# HuggingFace 镜像（在导入 huggingface_hub 之前设置，DashScope 不受影响，但保持习惯）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class RAGService:
    """单例：加载文档、构建向量库、提供检索。"""

    _instance: "RAGService | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._embeddings: DashScopeEmbeddings | None = None
        self._vectorstore: Chroma | None = None
        self._doc_count: int = 0

    @classmethod
    def instance(cls) -> "RAGService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------- 初始化 ----------

    def initialize(self) -> None:
        """启动时调用：加载文档、切分、构建向量库（已存在则复用）。"""
        if self._vectorstore is not None:
            return

        # 1) Embedding 模型（文档与查询共用）
        self._embeddings = DashScopeEmbeddings(
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )

        # 2) 向量库（ip 内积相似度）
        self._vectorstore = Chroma(
            collection_name=settings.CHROMA_COLLECTION,
            embedding_function=self._embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
            collection_metadata={"hnsw:space": "ip"},
        )

        # 3) 若库中已有文档则直接复用，避免重复 add 累积重复切片
        existing = self._safe_count()
        if existing > 0:
            self._doc_count = existing
            print(f"[RAG] 向量库已存在 {existing} 个切片，直接复用")
            return

        # 4) 加载文档 + 智能递归切分
        print(f"[RAG] 加载文档: {settings.DOC_PATH}")
        loader = Docx2txtLoader(settings.DOC_PATH)
        pages = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],
        )
        # pages 是 List[Document]，用 split_documents
        documents = splitter.split_documents(pages)
        print(f"[RAG] 切分完成，共 {len(documents)} 个文档块")

        # 5) 向量化入库
        print("[RAG] 开始向量化文档...")
        self._vectorstore.add_documents(documents)
        self._doc_count = len(documents)
        print(f"[RAG] 已添加 {self._doc_count} 个文档块到向量库")

    def rebuild(self) -> int:
        """清空并重建向量库，返回新切片数。"""
        if self._vectorstore is None:
            self.initialize()
            return self._doc_count

        # 清空已有 collection，再重新加载
        try:
            self._vectorstore.delete_collection()
        except Exception as e:
            print(f"[RAG] 删除旧 collection 警告: {e}")
        # 重新创建空 collection
        self._vectorstore = Chroma(
            collection_name=settings.CHROMA_COLLECTION,
            embedding_function=self._embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
            collection_metadata={"hnsw:space": "ip"},
        )

        loader = Docx2txtLoader(settings.DOC_PATH)
        pages = loader.load()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],
        )
        documents = splitter.split_documents(pages)
        self._vectorstore.add_documents(documents)
        self._doc_count = len(documents)
        print(f"[RAG] 重建完成，共 {self._doc_count} 个文档块")
        return self._doc_count

    # ---------- 检索 ----------

    def retrieve(self, query: str, k: int | None = None) -> list[tuple[str, float]]:
        """检索相似度最高的 K 条，返回 [(content, score), ...]。"""
        if self._vectorstore is None:
            raise RuntimeError("RAG 服务未初始化")
        top_k = k or settings.RAG_TOP_K
        results = self._vectorstore.similarity_search_with_score(query, k=top_k)
        return [(doc.page_content, float(score)) for doc, score in results]

    @staticmethod
    def build_context(results: list[tuple[str, float]]) -> str:
        """拼接检索到的上下文文本。"""
        return "\n\n".join([content for content, _ in results])

    def to_sources(self, results: list[tuple[str, float]]) -> list[dict]:
        """转成前端可展示的来源列表。"""
        return [{"content": c, "score": round(s, 4)} for c, s in results]

    @property
    def doc_count(self) -> int:
        return self._doc_count

    # ---------- 内部 ----------

    def _safe_count(self) -> int:
        """安全获取 collection 文档数，失败返回 0。"""
        try:
            coll = self._vectorstore._collection
            return coll.count() if coll else 0
        except Exception:
            return 0
