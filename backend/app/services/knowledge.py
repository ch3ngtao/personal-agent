"""补充知识库：运行时可追加的文本 → 切分 → 向量化 → 检索。

简历是固定的 PDF，而「其他知识」（项目复盘、常见问答、述职材料…）是随时想加就加的，
所以这里单独做一个可增删的向量库，agent 通过 ``search_knowledge`` 工具检索它。

落盘在 ``backend/.cache/knowledge.json``（向量库 dump）+ ``.meta.json``（文档清单），
进程重启后自动恢复；和简历索引一样，向量模型变了会自动判定缓存失效。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings, get_settings
from app.services.embeddings import EmbeddingService
from app.services.rag import BACKEND_DIR, LangChainEmbeddings, resolve_embedding_service
from app.services.retrieval import BM25, rank

logger = logging.getLogger(__name__)

SEPARATORS = ["\n\n", "\n", "。", "；", "！", "？", ". ", "，", "、", " ", ""]


@dataclass(slots=True)
class KnowledgeDocument:
    """一篇补充知识。"""

    id: str
    title: str
    source: str | None
    chars: int
    chunk_ids: list[str]
    added_at: datetime

    @property
    def chunks(self) -> int:
        return len(self.chunk_ids)


@dataclass(slots=True)
class KnowledgeHit:
    """一次检索命中的片段。"""

    content: str
    score: float
    vector_score: float | None
    document_id: str
    title: str


class KnowledgeStore:
    """可增删的向量知识库（进程内单例，带落盘缓存）。"""

    def __init__(
        self,
        settings: Settings | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding = LangChainEmbeddings(embedding_service or resolve_embedding_service(self.settings))
        self.chunk_size = self.settings.agent_knowledge_chunk_size
        self.chunk_overlap = self.settings.agent_knowledge_chunk_overlap

        cache = Path(self.settings.agent_knowledge_path).expanduser()
        self.cache_path = cache if cache.is_absolute() else BACKEND_DIR / cache

        self._store: InMemoryVectorStore | None = None
        self._documents: dict[str, KnowledgeDocument] = {}
        self._lock = threading.Lock()
        self._bm25: BM25 | None = None
        self._bm25_size: int | None = None
        self._contents: dict[str, str] = {}

    # ---- 基础 ----

    @property
    def model_name(self) -> str:
        return self.embedding.service.model_name

    def _meta_path(self) -> Path:
        return self.cache_path.with_suffix(".meta.json")

    def _documents_path(self) -> Path:
        return self.cache_path.with_suffix(".docs.json")

    def _ensure_loaded(self) -> None:
        if self._store is not None:
            return
        with self._lock:
            if self._store is not None:
                return
            self._store = InMemoryVectorStore(embedding=self.embedding)
            self._documents = {}
            self._contents = {}
            self._load()

    # ---- 持久化 ----

    def _fingerprint(self) -> str:
        return json.dumps(
            {
                "model": self.model_name,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
            sort_keys=True,
        )

    def _save(self) -> None:
        if self._store is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._store.dump(str(self.cache_path))
            self._meta_path().write_text(
                json.dumps({"fingerprint": self._fingerprint()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._documents_path().write_text(
                json.dumps(
                    [
                        {
                            "id": document.id,
                            "title": document.title,
                            "source": document.source,
                            "chars": document.chars,
                            "chunk_ids": document.chunk_ids,
                            "added_at": document.added_at.isoformat(),
                        }
                        for document in self._documents.values()
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # 写不进去不影响本次会话内的检索
            logger.warning("写入知识库缓存失败（%s），重启后需要重新导入", exc)

    def _load(self) -> None:
        if not (self.cache_path.is_file() and self._meta_path().is_file()):
            return
        try:
            meta = json.loads(self._meta_path().read_text(encoding="utf-8"))
            if meta.get("fingerprint") != self._fingerprint():
                logger.info("知识库缓存与当前向量模型不匹配，忽略缓存")
                return
            self._store = InMemoryVectorStore.load(str(self.cache_path), self.embedding)
            for record in self._store.store.values():
                self._contents[str(record.get("id"))] = str(record.get("text") or "")
            if self._documents_path().is_file():
                for item in json.loads(self._documents_path().read_text(encoding="utf-8")):
                    document = KnowledgeDocument(
                        id=item["id"],
                        title=item["title"],
                        source=item.get("source"),
                        chars=int(item.get("chars", 0)),
                        chunk_ids=list(item.get("chunk_ids", [])),
                        added_at=datetime.fromisoformat(item["added_at"]),
                    )
                    self._documents[document.id] = document
        except Exception as exc:  # noqa: BLE001 - 缓存坏了就从空库开始
            logger.warning("读取知识库缓存失败（%s），将从空库开始", exc)
            self._store = InMemoryVectorStore(embedding=self.embedding)
            self._documents = {}
            self._contents = {}

    # ---- 写 ----

    def add(self, title: str, text: str, source: str | None = None) -> KnowledgeDocument:
        """新增一篇知识：切分 → 向量化 → 入库。"""
        content = text.strip()
        if not content:
            raise ValueError("text 不能为空")

        self._ensure_loaded()
        document_id = uuid.uuid4().hex[:12]
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=SEPARATORS,
            strip_whitespace=True,
        )
        pieces = [piece for piece in splitter.split_text(content) if piece.strip()]
        if not pieces:
            raise ValueError("切分后没有内容")

        chunk_ids = [f"{document_id}::{index}" for index in range(len(pieces))]
        with self._lock:
            assert self._store is not None
            metadatas = [{"doc_id": document_id, "title": title, "chunk_index": index} for index in range(len(pieces))]
            self._store.add_texts(
                texts=pieces,
                metadatas=metadatas,
                ids=chunk_ids,
            )
            for chunk_id, piece in zip(chunk_ids, pieces, strict=True):
                self._contents[chunk_id] = piece
            document = KnowledgeDocument(
                id=document_id,
                title=title,
                source=source,
                chars=len(content),
                chunk_ids=chunk_ids,
                added_at=datetime.now().astimezone(),
            )
            self._documents[document_id] = document
            self._bm25 = None
            self._save()
        return document

    def remove(self, document_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            document = self._documents.pop(document_id, None)
            if document is None:
                return False
            assert self._store is not None
            self._store.delete(ids=document.chunk_ids)
            for chunk_id in document.chunk_ids:
                self._contents.pop(chunk_id, None)
            self._bm25 = None
            self._save()
        return True

    def clear(self) -> int:
        self._ensure_loaded()
        with self._lock:
            count = len(self._documents)
            self._store = InMemoryVectorStore(embedding=self.embedding)
            self._documents = {}
            self._contents = {}
            self._bm25 = None
            self._save()
        return count

    # ---- 读 ----

    def list_documents(self) -> list[KnowledgeDocument]:
        self._ensure_loaded()
        return sorted(self._documents.values(), key=lambda document: document.added_at, reverse=True)

    @property
    def total_chunks(self) -> int:
        self._ensure_loaded()
        return sum(document.chunks for document in self._documents.values())

    def is_empty(self) -> bool:
        self._ensure_loaded()
        return not self._documents

    def _ids(self) -> list[str]:
        assert self._store is not None
        return list(self._store.store.keys())

    def _bm25_for(self, ids: list[str]) -> BM25:
        if self._bm25 is None or self._bm25_size != len(ids):
            self._bm25 = BM25([self._contents.get(chunk_id, "") for chunk_id in ids])
            self._bm25_size = len(ids)
        return self._bm25

    def search(self, query: str, top_k: int = 4) -> list[KnowledgeHit]:
        self._ensure_loaded()
        assert self._store is not None
        ids = self._ids()
        if not ids:
            return []

        k = max(1, min(top_k, len(ids)))
        hits = self._store.similarity_search_with_score(query, k=min(max(k * 4, 12), len(ids)))
        position = {chunk_id: index for index, chunk_id in enumerate(ids)}
        vector_scores = {
            position[str(document.id)]: float(score) for document, score in hits if str(document.id) in position
        }

        ordered = rank(query, vector_scores, top_k=k, bm25=self._bm25_for(ids), candidate_limit=max(k * 4, 12))
        results: list[KnowledgeHit] = []
        for index, score in ordered:
            chunk_id = ids[index]
            record = self._store.store.get(chunk_id, {})
            metadata = record.get("metadata") or {}
            results.append(
                KnowledgeHit(
                    content=str(record.get("text") or ""),
                    score=score,
                    vector_score=round(vector_scores[index], 4) if index in vector_scores else None,
                    document_id=str(metadata.get("doc_id", "")),
                    title=str(metadata.get("title", "")),
                )
            )
        return results


_knowledge_store: KnowledgeStore | None = None
_knowledge_lock = threading.Lock()


def get_knowledge_store() -> KnowledgeStore:
    """进程内单例。"""
    global _knowledge_store
    if _knowledge_store is None:
        with _knowledge_lock:
            if _knowledge_store is None:
                _knowledge_store = KnowledgeStore()
    return _knowledge_store
