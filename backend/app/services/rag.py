"""简历 FAQ 的 RAG 流水线：LangChain 切分 PDF → 向量化 → 检索 → DeepSeek 生成答案。

每一步都对应一个 LangChain 组件，方便按官方文档对照阅读：

1. **读取**：``pypdf`` 逐页读取简历 PDF，每页包成 ``langchain_core`` 的 ``Document``，
   metadata 里保留页码，供答案做引用。
   （官方的 ``PyPDFLoader`` 来自已停止维护的 ``langchain-community``，这里直接用底层
   ``pypdf``，少一个依赖也少一条弃用告警。）
2. **切分**：先按简历的章节标题（求职意向 / 相关技能 / 工作经历 / 项目经历 …）和
   日期开头的条目（如「2022.10-至今 XX 公司」）切成语义块，再用
   ``RecursiveCharacterTextSplitter`` 按「段落 → 换行 → 中文标点」递归切到目标粒度。
   每个 chunk 会带上所属章节（有时还有所属公司 / 项目）作为上下文前缀，
   否则「他现在在哪家公司」这类问题会因为公司名和经历详情被切散而召回不到。
   识别不到章节结构时退回「逐页 + 递归切分」的简单策略。
3. **向量化**：复用项目里的 ``EmbeddingService``，通过 ``LangChainEmbeddings`` 适配成
   LangChain 的 ``Embeddings`` 接口，写入 ``InMemoryVectorStore``（numpy 余弦相似度）。
   默认用中文模型 ``BAAI/bge-small-zh-v1.5``；配置留空时复用全局的
   ``all-MiniLM-L6-v2``。
4. **检索**：向量相似度 + BM25 关键词得分加权融合。MiniLM 是英文模型，对中文短查询的
   语义区分度有限，多一路关键词召回能明显提稳；bge 中文模型则主要靠向量这一路。
5. **生成**：把命中的 chunk 拼成带页码的上下文，交给 DeepSeek 生成答案，并强制要求
   「只依据片段回答」。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.core import clock
from app.core.config import Settings, get_settings
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.llm import DeepSeekService, get_deepseek_service
from app.services.retrieval import BM25, rank

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

# 切分优先级：先按自然段，再按换行，最后退到中文标点和空白。
SEPARATORS = ["\n\n", "\n", "。", "；", "！", "？", ". ", "，", "、", " ", ""]

# 简历的章节标题，用来做结构感知切分（长标题排前面，避免被短标题截断）。
SECTION_TITLES = (
    "个人信息",
    "基本信息",
    "求职意向",
    "教育经历",
    "工作经历",
    "实习经历",
    "项目经历",
    "项目经验",
    "相关技能",
    "专业技能",
    "技能清单",
    "其他项目",
    "荣誉奖项",
    "自我评价",
    "证书",
)
_SECTION_RE = re.compile(
    r"^(?P<title>" + "|".join(sorted(SECTION_TITLES, key=len, reverse=True)) + r")\s*(?:[：:]\s*(?P<rest>.*))?$"
)
# 「2022.10-至今 XX 公司」「2014.9-2018.7 XX 学院」这类条目起始行。
_ENTRY_RE = re.compile(
    r"^\d{4}\s*[./\-年]\s*\d{1,2}(?:\s*月)?\s*[-–—~至]\s*(?:\d{4}|至今|现在|present)",
    re.IGNORECASE,
)

# 找 PDF 的顺序：仓库根目录 → backend/data → backend 目录。
PDF_SEARCH_DIRS = (REPO_ROOT, BACKEND_DIR / "data", BACKEND_DIR)
# 什么都没配时的兜底简历：仓库里跟踪的对外版本（只为「光跑后端、不带任何配置」的场景）。
# 部署和本地开发都由配置决定用哪份：RESUME_PDF_PATH 优先，其次是 RESUME_FILE。
DEFAULT_PDF_NAME = "简历-李四.pdf"

# 切分策略版本：策略一变，旧缓存自动失效。
CHUNKING_STRATEGY = "section-aware-v1"

# 这些章节是「条目列表」结构，会额外生成一条只列条目名的索引片段：
# 「他最近在哪家公司」「有哪些项目」这类问题靠正文片段很难排到前面，
# 但一条纯「时间 + 名称 + 职位」的短索引片段就很好命中。
INDEXED_SECTIONS = ("工作经历", "实习经历", "项目经历", "项目经验", "教育经历")

# 分组时给索引片段的专用 key；整节召回但一次都没命中时用的兜底相关度。
_INDEX_ENTRY = "·索引"
_SECTION_BASE_SCORE = 0.5

# 「章节级提问」的识别词。问「有哪些项目经验」时，只按相似度取 top-k 会漏条目
# （实测 4 个项目只召回 2 个碎片），这类问题改成把整节条目一起交给模型。
# 顺序有意义：先匹配更具体的章节，「其他项目」要排在「项目经历」前面。
SECTION_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "其他项目": ("其他项目",),
    "项目经历": ("项目经历", "项目经验", "项目", "作品", "做过哪些"),
    "工作经历": ("工作经历", "工作经", "职业经历", "履历", "任职", "公司"),
    "教育经历": ("教育经历", "教育背景", "学历", "学校", "毕业"),
    "相关技能": ("相关技能", "专业技能", "技能清单", "技术栈", "技能", "擅长"),
    "求职意向": ("求职意向", "意向岗位", "期望薪资", "求职"),
    "自我评价": ("自我评价",),
}

# 被问到的章节要连同这些「补充章节」一起给出：简历常把项目分两节写，
# 只给【项目经历】正文会把末尾【其他项目】里那一串项目整段漏掉。
RELATED_SECTIONS: dict[str, tuple[str, ...]] = {
    "项目经历": ("其他项目",),
    "项目经验": ("其他项目",),
    "工作经历": ("实习经历",),
}


class ResumePdfNotFoundError(FileNotFoundError):
    """找不到简历 PDF 时抛出。"""


class RagIndexError(RuntimeError):
    """索引构建 / 加载失败时抛出。"""


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ResumeChunk:
    """切分后的一个片段，``score`` 为检索相关度。"""

    index: int
    content: str
    page: int | None = None
    start_index: int | None = None
    section: str | None = None
    score: float = 0.0
    vector_score: float | None = None

    @property
    def chars(self) -> int:
        return len(self.content)


@dataclass(slots=True)
class RagStatus:
    """索引状态，供 ``/api/faq/status`` 展示。"""

    # ready = 知识库可用（找得到 PDF、上次构建没报错），冷启动时就是 true；
    # indexed = 索引已经在内存里建好（首次问答时才构建）。
    ready: bool = False
    indexed: bool = False
    building: bool = False
    loaded_from_cache: bool = False
    pdf_name: str | None = None
    pdf_path: str | None = None
    pdf_size: int | None = None
    pdf_modified_at: datetime | None = None
    pages: int = 0
    chunks: int = 0
    chunk_size: int = 0
    chunk_overlap: int = 0
    embedding_model: str = ""
    embedding_dim: int = 0
    vector_store: str = "InMemoryVectorStore"
    hybrid_search: bool = True
    built_at: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class _IndexData:
    """索引的内存态：向量库 + 全量 chunk + 构建信息。"""

    store: InMemoryVectorStore
    chunks: list[ResumeChunk]
    source: Path
    pages: int
    fingerprint: str
    built_at: datetime
    loaded_from_cache: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# LangChain 适配层
# --------------------------------------------------------------------------- #


class LangChainEmbeddings(Embeddings):
    """把项目里的 ``EmbeddingService`` 适配成 LangChain 的 ``Embeddings`` 接口。

    这样上层就能直接用 LangChain 的 ``InMemoryVectorStore``，而向量模型仍是同一个
    ``all-MiniLM-L6-v2``，不会多加载一份权重。
    """

    def __init__(self, service: EmbeddingService) -> None:
        self.service = service

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.service.encode(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.service.encode([text])[0]


@lru_cache
def _cached_embedding_service(model_name: str, device: str, normalize: bool) -> EmbeddingService:
    """按模型名复用向量模型实例（懒加载）。"""
    return EmbeddingService(model_name, device=device, normalize=normalize)


def resolve_embedding_service(settings: Settings) -> EmbeddingService:
    """RAG / 补充知识库统一的向量模型选择。

    配了 ``RAG_EMBEDDING_MODEL`` 就用它（中文简历建议用中文模型），留空则复用项目全局的
    ``EMBEDDING_MODEL``。简历和补充知识必须用同一个模型，检索结果才可比。
    """
    model_name = (settings.rag_embedding_model or "").strip()
    if not model_name or model_name == settings.embedding_model:
        return get_embedding_service()
    return _cached_embedding_service(model_name, settings.embedding_device, settings.embedding_normalize)


# --------------------------------------------------------------------------- #
# 索引
# --------------------------------------------------------------------------- #


class ResumeIndex:
    """简历索引：负责构建、缓存、检索和问答。"""

    def __init__(
        self,
        settings: Settings | None = None,
        embedding_service: EmbeddingService | None = None,
        llm_service: DeepSeekService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding = LangChainEmbeddings(embedding_service or resolve_embedding_service(self.settings))
        self.llm = llm_service or get_deepseek_service()

        self.chunk_size = self.settings.rag_chunk_size
        self.chunk_overlap = self.settings.rag_chunk_overlap
        self.hybrid = self.settings.rag_hybrid
        self.section_aware = self.settings.rag_section_aware
        self.max_context_chars = max(0, self.settings.rag_max_context_chars)
        self.default_top_k = self.settings.rag_top_k
        self._cache_path = self._resolve_cache_path(self.settings.rag_cache_path)

        self._data: _IndexData | None = None
        self._lock = threading.Lock()
        self._building = False
        self._error: str | None = None
        self._bm25: BM25 | None = None
        self._bm25_index: int | None = None

        self.pdf_path = self.resolve_pdf_path(self.settings.resume_pdf_path, self.settings.resume_file)

    # ---- 路径 ----

    @property
    def resume_label(self) -> str:
        """日志 / 排查里用哪个名字称呼当前这份简历。

        优先用配置的 RESUME_FILE：容器里挂载后路径统一是 /app/resume.pdf，
        只打路径看不出这个环境用的是哪一份。
        """
        if self.settings.resume_file:
            return str(self.settings.resume_file)
        return self.pdf_path.name if self.pdf_path else "未配置"

    @staticmethod
    def _resolve_cache_path(raw: str) -> Path:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else (BACKEND_DIR / path)

    @staticmethod
    def resolve_pdf_path(configured: str | None, filename: str | None = None) -> Path | None:
        """按「RESUME_PDF_PATH → RESUME_FILE → 仓库根目录 / backend/data / backend 里的 PDF」找简历。

        用哪份简历完全由配置决定，代码里只有最后那个兜底默认值。
        """
        candidates: list[Path] = []

        for value in (configured, filename):
            if not value:
                continue
            raw = Path(str(value)).expanduser()
            candidates.extend([raw] if raw.is_absolute() else [raw, BACKEND_DIR / raw, REPO_ROOT / raw])

        for directory in PDF_SEARCH_DIRS:
            candidates.append(directory / DEFAULT_PDF_NAME)
            if directory.is_dir():
                candidates.extend(sorted(directory.glob("*.pdf")))

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _require_pdf(self) -> Path:
        if self.pdf_path is None or not self.pdf_path.is_file():
            searched = ", ".join(str(path) for path in PDF_SEARCH_DIRS)
            raise ResumePdfNotFoundError(
                f"找不到简历 PDF，请在 .env 里配置 RESUME_FILE 或 RESUME_PDF_PATH（已搜索：{searched}）"
            )
        return self.pdf_path

    # ---- 构建 ----

    def _read_pages(self, pdf_path: Path) -> tuple[list[tuple[int, str]], int]:
        """第 1 步：读取 PDF，返回 ``[(页码, 文本), ...]`` 与总页数。"""
        reader = PdfReader(str(pdf_path))
        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            if text:
                pages.append((page_number, text))
        return pages, len(reader.pages)

    def _splitter(self) -> RecursiveCharacterTextSplitter:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=SEPARATORS,
            add_start_index=True,
            strip_whitespace=True,
        )
        return splitter

    def _split_pages(self, pages: Sequence[tuple[int, str]], source_name: str) -> list[Document]:
        """第 2 步：结构感知切分。"""
        content_blocks = _collect_blocks(pages)
        if not content_blocks:
            return self._split_pages_flat(pages, source_name)

        blocks = _with_index_blocks(content_blocks)
        _assign_offsets(blocks)

        documents: list[Document] = []
        splitter = self._splitter()
        for block in blocks:
            pieces = splitter.split_documents([Document(page_content=block.text)])
            for position, piece in enumerate(pieces):
                offset = int(piece.metadata.get("start_index", 0))
                content = piece.page_content
                # 续块的正文里没有条目标题，补上，避免「这家公司在干什么」这类问题断上下文。
                if position and block.header:
                    content = f"{block.header}\n{content}"
                if block.section and not content.lstrip().startswith("【"):
                    content = f"【{block.section}】\n{content}"
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": source_name,
                            "page": block.page_at(offset),
                            "section": block.section,
                            "start_index": block.start + offset,
                        },
                    )
                )
        return documents

    def _split_pages_flat(self, pages: Sequence[tuple[int, str]], source_name: str) -> list[Document]:
        """兜底策略：识别不到章节结构时，按页递归切分。"""
        documents = [
            Document(page_content=text, metadata={"source": source_name, "page": page}) for page, text in pages
        ]
        return self._splitter().split_documents(documents)

    def _build(self) -> _IndexData:
        pdf_path = self._require_pdf()
        page_texts, page_count = self._read_pages(pdf_path)
        if not page_texts:
            raise RagIndexError(f"{pdf_path.name} 没有可提取的文本，无法建立索引")

        splits = self._split_pages(page_texts, pdf_path.name)
        if not splits:
            raise RagIndexError(f"{pdf_path.name} 切分后没有内容")

        chunks: list[ResumeChunk] = []
        for index, split in enumerate(splits):
            split.metadata = {**split.metadata, "chunk_index": index}
            chunks.append(
                ResumeChunk(
                    index=index,
                    content=split.page_content,
                    page=split.metadata.get("page"),
                    start_index=split.metadata.get("start_index"),
                    section=split.metadata.get("section"),
                )
            )

        # 第 3 步：向量化并写入 LangChain 向量库。
        store = InMemoryVectorStore.from_documents(splits, self.embedding)

        data = _IndexData(
            store=store,
            chunks=chunks,
            source=pdf_path,
            pages=page_count,
            fingerprint=self._fingerprint(pdf_path),
            built_at=_now(),
        )
        self._save_cache(data)
        return data

    def _fingerprint(self, pdf_path: Path) -> str:
        """PDF 或切分参数一变，缓存就失效。"""
        stat = pdf_path.stat()
        return json.dumps(
            {
                "path": str(pdf_path),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "strategy": CHUNKING_STRATEGY,
                "model": self.embedding.service.model_name,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    # ---- 缓存 ----

    def _save_cache(self, data: _IndexData) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            data.store.dump(str(self._cache_path))
            self._meta_path().write_text(
                json.dumps(
                    {
                        "fingerprint": data.fingerprint,
                        "source": str(data.source),
                        "pages": data.pages,
                        "chunk_size": self.chunk_size,
                        "chunk_overlap": self.chunk_overlap,
                        "embedding_model": self.embedding.service.model_name,
                        "built_at": data.built_at.isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # 缓存写不进去不影响功能，只是下次要重新构建
            logger.warning("写入 RAG 索引缓存失败（%s），下次启动会重新构建", exc)

    def _meta_path(self) -> Path:
        return self._cache_path.with_suffix(".meta.json")

    def _load_cache(self) -> _IndexData | None:
        pdf_path = self.pdf_path
        if pdf_path is None or not (self._cache_path.is_file() and self._meta_path().is_file()):
            return None

        try:
            meta = json.loads(self._meta_path().read_text(encoding="utf-8"))
            if meta.get("fingerprint") != self._fingerprint(pdf_path):
                return None
            store = InMemoryVectorStore.load(str(self._cache_path), self.embedding)
            chunks = [
                ResumeChunk(
                    index=int(document.metadata.get("chunk_index", position)),
                    content=document.page_content,
                    page=document.metadata.get("page"),
                    start_index=document.metadata.get("start_index"),
                    section=document.metadata.get("section"),
                )
                for position, document in enumerate(_store_documents(store))
            ]
            chunks.sort(key=lambda chunk: chunk.index)
            return _IndexData(
                store=store,
                chunks=chunks,
                source=pdf_path,
                pages=int(meta.get("pages", 0)),
                fingerprint=meta["fingerprint"],
                built_at=datetime.fromisoformat(meta["built_at"]),
                loaded_from_cache=True,
            )
        except Exception as exc:  # noqa: BLE001 - 缓存坏了就重建，不影响可用性
            logger.warning("读取 RAG 索引缓存失败（%s），将重新构建", exc)
            return None

    # ---- 对外：状态 / 懒加载 ----

    def ensure_ready(self) -> _IndexData:
        """第一次用到时才构建索引（进程内只构建一次）。"""
        if self._data is not None:
            return self._data

        with self._lock:
            if self._data is not None:
                return self._data
            self._building = True
            try:
                data = self._load_cache()
                if data is None:
                    logger.info("正在构建简历索引：%s（配置的简历文件：%s）", self.pdf_path, self.resume_label)
                    data = self._build()
                    logger.info("简历索引构建完成：%s 个 chunk", len(data.chunks))
                else:
                    logger.info("已从缓存加载简历索引：%s 个 chunk", len(data.chunks))
                self._data = data
                self._error = None
                return data
            except Exception as exc:
                self._error = str(exc)
                raise
            finally:
                self._building = False

    def rebuild(self) -> _IndexData:
        """强制重新切分并向量化。"""
        with self._lock:
            self._building = True
            try:
                data = self._build()
            except Exception as exc:
                self._error = str(exc)
                raise
            finally:
                self._building = False

        self._data = data
        self._bm25 = None
        self._error = None
        return data

    @property
    def building(self) -> bool:
        return self._building

    def status(self) -> RagStatus:
        data = self._data
        pdf_path = self.pdf_path
        pdf_stat = None
        if pdf_path is not None and pdf_path.is_file():
            try:
                pdf_stat = pdf_path.stat()
            except OSError:  # pragma: no cover - 极端并发删除场景
                pdf_stat = None

        return RagStatus(
            ready=pdf_stat is not None and self._error is None,
            indexed=data is not None,
            building=self._building,
            loaded_from_cache=bool(data and data.loaded_from_cache),
            pdf_name=pdf_path.name if pdf_path else None,
            pdf_path=str(pdf_path) if pdf_path else None,
            pdf_size=pdf_stat.st_size if pdf_stat else None,
            pdf_modified_at=datetime.fromtimestamp(pdf_stat.st_mtime).astimezone() if pdf_stat else None,
            pages=data.pages if data else 0,
            chunks=len(data.chunks) if data else 0,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            embedding_model=self.embedding.service.model_name,
            embedding_dim=self.embedding.service.dimension if data else 0,
            hybrid_search=self.hybrid,
            built_at=data.built_at if data else None,
            error=self._error,
        )

    def list_chunks(self, limit: int | None = None) -> list[ResumeChunk]:
        data = self.ensure_ready()
        return data.chunks[:limit] if limit else list(data.chunks)

    # ---- 检索 ----

    def _bm25_for(self, data: _IndexData) -> BM25:
        if self._bm25 is None or self._bm25_index != len(data.chunks):
            self._bm25 = BM25([chunk.content for chunk in data.chunks])
            self._bm25_index = len(data.chunks)
        return self._bm25

    def search(self, query: str, top_k: int | None = None) -> list[ResumeChunk]:
        """第 4 步：召回与问题最相关的 chunk。

        分两种情况：

        * **章节级提问**（「有哪些项目经验」「工作经历」）→ 把该章节的条目全部返回。
          一条经历常被切成多个碎片，只取 top-k 会让「4 个项目只答出 2 个」。
        * **其余提问** → 正常混合检索，再把命中片段补全成完整条目（半句话开头的
          续块和它的首块一起给模型，答案才不会断头）。

        关掉 ``RAG_SECTION_AWARE`` 就退回纯 top-k 老行为。
        """
        data = self.ensure_ready()
        k = max(1, min(top_k or self.default_top_k, len(data.chunks)))

        # 向量路：多取一些候选，便于融合排序。
        pool = max(k * 4, 12)
        vector_hits = data.store.similarity_search_with_score(query, k=min(pool, len(data.chunks)))
        vector_scores: dict[int, float] = {
            int(document.metadata["chunk_index"]): float(score) for document, score in vector_hits
        }

        # 关键词路 + 融合排序（与「补充知识库」共用 retrieval.rank）。
        ordered = rank(
            query,
            vector_scores,
            top_k=k,
            bm25=self._bm25_for(data),
            hybrid=self.hybrid,
            candidate_limit=pool,
        )
        hits = [
            _with_scores(data.chunks[index], score=score, vector=vector_scores.get(index)) for index, score in ordered
        ]

        if not self.section_aware:
            return hits

        sections = match_sections(query)
        if sections:
            expanded = self._section_chunks(data, sections, hits)
            if expanded:
                return expanded
        return self._expand_entries(data, hits)

    # ---- 检索后的补全 ----

    def _section_chunks(
        self,
        data: _IndexData,
        sections: Sequence[str],
        hits: Sequence[ResumeChunk],
    ) -> list[ResumeChunk]:
        """整节返回：索引片段（列全条目名）+ 这些章节下合并后的完整条目。"""
        wanted = set(sections)
        groups = {key: group for key, group in _group_by_entry(data.chunks).items() if key[0] in wanted}
        if not groups:
            return []

        # 用命中的最高分当作整节的「相关度」，界面上不会出现一堆 0%。
        base_score = next((hit.score for hit in hits if hit.section in wanted), _SECTION_BASE_SCORE)

        selected: list[ResumeChunk] = []
        budget = self.max_context_chars

        # 索引片段（只列「时间 + 名称 + 职位」）放最前面：它保证条目名一个不落。
        for section in sections:
            index_group = groups.pop((section, _INDEX_ENTRY), None)
            if index_group:
                entry = _merge_group(index_group, self.chunk_overlap)
                selected.append(_rescore(entry, base_score))
                budget -= entry.chars

        for group in groups.values():
            if budget <= 0:
                break
            entry = _merge_group(group, self.chunk_overlap)
            selected.append(_rescore(entry, base_score))
            budget -= entry.chars
        return selected

    def _expand_entries(self, data: _IndexData, hits: Sequence[ResumeChunk]) -> list[ResumeChunk]:
        """把命中的碎片补成完整条目，并去掉重复条目。"""
        groups = _group_by_entry(data.chunks)
        expanded: list[ResumeChunk] = []
        seen: set[tuple[str | None, str]] = set()
        budget = self.max_context_chars
        for hit in hits:
            key = _entry_key(hit)
            group = groups.get(key)
            if not group or key in seen:
                continue
            entry = _merge_group(group, self.chunk_overlap)
            if expanded and budget - entry.chars <= 0:
                break
            seen.add(key)
            budget -= entry.chars
            expanded.append(_rescore(entry, hit.score))
        return expanded or list(hits)

    # ---- 生成 ----

    def build_messages(
        self,
        question: str,
        chunks: Sequence[ResumeChunk],
        history: Sequence[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        context = "\n\n".join(
            f"[片段 {position} · 第 {chunk.page or '?'} 页]\n{chunk.content}"
            for position, chunk in enumerate(chunks, start=1)
        )
        # 简历里常写「2022.10-至今」，模型需要知道今天是几号才能判断是否仍然在职。
        today = clock.describe(with_time=False)
        prompt = SYSTEM_PROMPT.format(name=self.settings.resume_name)
        system = f"{prompt}\n\n今天的日期是 {today}，判断「至今」「最近」这类表述时以此为准。"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": f"简历片段：\n\n{context}\n\n提问：{question}"})
        return messages


SYSTEM_PROMPT = """你是「{name}」个人简历的问答助手，负责回答来访者关于这份简历的问题。

规则：
1. 只依据下面提供的简历片段回答，片段里没有的信息一律不要编造，也不要用你的先验知识补充。
2. 如果片段里确实没有相关信息，直接回答「简历里没有找到相关信息」，并提示可以换个问法，
   例如询问工作经历、项目经验、技术栈、求职意向等。
3. 用简体中文回答，简洁分点；直接说自己想说的内容即可，不要在正文里写「片段 1」「第 2 页」
   这类来源标注，引用的出处会由界面单独展示。
4. 语气客观中立，不要过度营销，也不要替候选人做出承诺（如到岗时间、薪资底线等片段中没有的内容）。
5. 对方问的是某一整节时（如「有哪些项目经验」「介绍下工作经历」），片段里该节的条目要**全部列出**，
   按「时间 · 名称（角色）」起头，再写关键内容；不要只挑其中一两条，也不要把「·索引」片段当成
   正式内容照抄。条目多时用简洁的列表，不要为了省篇幅省略中间的项目。
   简历如果分了几节写同类内容（例如【项目经历】之外还有【其他项目】），补充章节里的条目也要一并
   列出——只有名称没有细节的，就按名称列出，不要因为细节少而整节跳过。
"""


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _normalize_text(text: str) -> str:
    """PDF 抽取的文本常有零散空格与多余空行，这里收敛一次，提升切分质量。"""
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


@dataclass(slots=True)
class _Block:
    """一个切分单元：某章节下的整段内容，或某条经历 / 项目的完整描述。"""

    section: str | None
    header: str | None
    text: str
    start: int
    # (块内文本偏移, 页码)，用来把子块映射回它所在的页
    page_marks: list[tuple[int, int]]

    def page_at(self, offset: int) -> int | None:
        page = self.page_marks[0][1] if self.page_marks else None
        for mark_offset, mark_page in self.page_marks:
            if mark_offset > offset:
                break
            page = mark_page
        return page


def _collect_blocks(pages: Sequence[tuple[int, str]]) -> list[_Block]:
    """把逐页文本按「章节标题 + 日期条目」切成语义块。

    简历的排版经常把「工作经历 / 2022.10-至今 XX 公司」放在页尾、把详情放到下一页，
    逐页切分会把公司名和它的工作内容拆到两个 chunk 里。这里先按结构切块，
    再让后续的递归切分只在块内部生效，保证一条经历不会被切散。
    """
    blocks: list[_Block] = []
    section: str | None = None
    header: str | None = None
    lines: list[tuple[str, int]] = []

    def flush() -> None:
        nonlocal lines, header
        if lines:
            text = "\n".join(line for line, _ in lines)
            marks: list[tuple[int, int]] = []
            cursor = 0
            for line, page in lines:
                marks.append((cursor, page))
                cursor += len(line) + 1
            blocks.append(_Block(section=section, header=header, text=text, start=0, page_marks=marks))
        lines = []
        header = None

    for page, text in pages:
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            heading = _SECTION_RE.match(line)
            if heading:
                flush()
                section = heading.group("title")
                rest = (heading.group("rest") or "").strip()
                if rest:
                    lines.append((rest, page))
                continue

            if section and _ENTRY_RE.match(line):
                flush()
                header = line
                lines.append((line, page))
                continue

            lines.append((line, page))

    flush()
    return blocks


def _with_index_blocks(blocks: Sequence[_Block]) -> list[_Block]:
    """为多条目章节插入一条「索引片段」，只列「时间 + 公司/项目 + 职位」。

    正文片段里，公司名常被技术栈、职责描述稀释，问「他最近在哪家公司」时排不到前面；
    一条格式统一的短索引片段能让这类问题稳定命中。
    """
    grouped: dict[str, list[_Block]] = {}
    for block in blocks:
        if block.section and block.header:
            grouped.setdefault(block.section, []).append(block)

    merged: list[_Block] = []
    inserted: set[str] = set()
    for block in blocks:
        section = block.section
        if section and section in INDEXED_SECTIONS and section not in inserted:
            entries = grouped.get(section, [])
            inserted.add(section)
            if len(entries) >= 2:
                merged.append(_index_block(section, entries))
        merged.append(block)
    return merged


def _index_block(section: str, entries: Sequence[_Block]) -> _Block:
    lines = [f"【{section}·索引】"]
    for entry in entries:
        lines.append(entry.header or "")
        body = entry.text.split("\n")
        # 紧接着的一行通常是职位 / 角色，带上更利于回答「做什么方向」。
        if len(body) > 1:
            lines.append(body[1])
    return _Block(
        section=section,
        header=None,
        text="\n".join(line for line in lines if line),
        start=0,
        page_marks=[(0, entries[0].page_marks[0][1])],
    )


def _assign_offsets(blocks: Sequence[_Block]) -> None:
    """补齐每个块在整篇文本中的起始偏移（给 chunk 的 start_index 用）。"""
    cursor = 0
    for block in blocks:
        block.start = cursor
        cursor += len(block.text) + 1


def _now() -> datetime:
    return datetime.now().astimezone()


def _with_scores(chunk: ResumeChunk, score: float, vector: float | None) -> ResumeChunk:
    return ResumeChunk(
        index=chunk.index,
        content=chunk.content,
        page=chunk.page,
        start_index=chunk.start_index,
        section=chunk.section,
        score=round(max(0.0, min(1.0, score)), 4),
        vector_score=None if vector is None else round(vector, 4),
    )


def _rescore(chunk: ResumeChunk, score: float) -> ResumeChunk:
    """整节 / 补全出来的条目没有独立打分，沿用触发它的那次命中的分数。"""
    return _with_scores(chunk, score=score, vector=None)


def match_section(query: str) -> str | None:
    """判断问题是不是在问某一个整节（「有哪些项目经验」→「项目经历」）。"""
    normalized = re.sub(r"\s+", "", query or "")
    if not normalized:
        return None
    for section, aliases in SECTION_QUERY_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return section
    return None


def match_sections(query: str) -> list[str]:
    """整节提问要一起给出的章节：主体章节 + 它的补充章节。"""
    section = match_section(query)
    if section is None:
        return []
    return [section, *RELATED_SECTIONS.get(section, ())]


def _is_index_chunk(chunk: ResumeChunk) -> bool:
    """是否为「只列条目名」的索引片段。"""
    first_line = _first_line(chunk.content)
    return first_line.startswith("【") and _INDEX_ENTRY in first_line


def _first_line(content: str) -> str:
    return next((line.strip() for line in content.split("\n") if line.strip()), "")


def _entry_header(chunk: ResumeChunk) -> str:
    """条目首行（去掉 ``【章节】`` 前缀），如「2023.07-至今 语音助手 / 文本助手」。"""
    lines = [line.strip() for line in chunk.content.split("\n") if line.strip()]
    if lines and lines[0].startswith("【"):
        lines = lines[1:]
    return lines[0] if lines else ""


def _entry_key(chunk: ResumeChunk) -> tuple[str | None, str]:
    """把碎片归到所属条目：``(章节, 条目标题)``。索引片段单独归一类。"""
    if _is_index_chunk(chunk):
        return chunk.section, _INDEX_ENTRY
    return chunk.section, _entry_header(chunk)


def _group_by_entry(chunks: Sequence[ResumeChunk]) -> dict[tuple[str | None, str], list[ResumeChunk]]:
    """同一条目的多个碎片连在一起（切分顺序即文档顺序）。"""
    groups: dict[tuple[str | None, str], list[ResumeChunk]] = {}
    for chunk in chunks:
        groups.setdefault(_entry_key(chunk), []).append(chunk)
    return groups


def _strip_chunk_prefix(content: str, header: str) -> str:
    """去掉续块开头重复的 ``【章节】`` 与条目标题，只留正文。"""
    lines = content.split("\n")
    if lines and lines[0].strip().startswith("【"):
        lines = lines[1:]
    if lines and header and lines[0].strip() == header:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _merge_group(group: Sequence[ResumeChunk], overlap: int) -> ResumeChunk:
    """把同一条目被切开的碎片拼回完整一段，并去掉 chunk_overlap 造成的重复。"""
    lead = group[0]
    if len(group) == 1:
        return lead

    header = _entry_header(lead)
    merged = lead.content
    for chunk in group[1:]:
        body = _strip_chunk_prefix(chunk.content, header)
        if not body:
            continue
        # 切分器让相邻片段有 overlap 个字符的重叠，这里按最长公共部分削掉。
        for size in range(min(len(body), overlap + 40), 0, -1):
            if merged.endswith(body[:size]):
                body = body[size:]
                break
        if not body:
            continue
        merged = f"{merged.rstrip()}\n{body.lstrip()}"

    return ResumeChunk(
        index=lead.index,
        content=merged,
        page=lead.page,
        start_index=lead.start_index,
        section=lead.section,
        score=lead.score,
        vector_score=lead.vector_score,
    )


def _store_documents(store: InMemoryVectorStore) -> list[Document]:
    """``InMemoryVectorStore`` 没有「列出全部文档」的公开接口，这里按插入顺序读内部表。"""
    documents: list[Document] = []
    for record in store.store.values():
        text = record.get("text")
        if text is None:
            continue
        documents.append(Document(page_content=text, metadata=dict(record.get("metadata") or {})))
    return documents


_resume_index: ResumeIndex | None = None
_resume_index_lock = threading.Lock()


def get_resume_index() -> ResumeIndex:
    """进程内单例。"""
    global _resume_index
    if _resume_index is None:
        with _resume_index_lock:
            if _resume_index is None:
                _resume_index = ResumeIndex()
    return _resume_index
