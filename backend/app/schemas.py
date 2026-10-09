"""请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    embedding_model: str
    llm_model: str
    llm_configured: bool


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64, description="待编码的文本列表")


class EmbeddingResponse(BaseModel):
    model: str
    dimension: int
    vectors: list[list[float]]


class SimilarityRequest(BaseModel):
    source: str = Field(..., min_length=1, description="查询文本")
    targets: list[str] = Field(..., min_length=1, max_length=100, description="候选文本列表")


class SimilarityMatch(BaseModel):
    index: int
    text: str
    score: float


class SimilarityResponse(BaseModel):
    model: str
    dimension: int
    matches: list[SimilarityMatch]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False


class ChatResponse(BaseModel):
    model: str
    content: str
    usage: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# 简历 FAQ（RAG）
# --------------------------------------------------------------------------- #


class RagSource(BaseModel):
    """召回的一个简历片段。"""

    index: int = Field(..., description="chunk 序号，从 0 开始")
    content: str
    page: int | None = Field(default=None, description="片段所在的 PDF 页码（从 1 开始）")
    section: str | None = Field(default=None, description="片段所属的简历章节，如「工作经历」")
    score: float = Field(..., description="融合后的相关度，最高为 1")
    vector_score: float | None = Field(default=None, description="原始余弦相似度")


class RagChunk(BaseModel):
    """切分结果的预览（不带相关度）。"""

    index: int
    content: str
    page: int | None = None
    section: str | None = None
    chars: int


class RagStatusResponse(BaseModel):
    ready: bool = Field(..., description="知识库是否可用（找得到 PDF 且上次构建未报错）")
    indexed: bool = Field(..., description="索引是否已在内存中构建完成")
    building: bool
    loaded_from_cache: bool
    pdf_name: str | None = None
    pdf_path: str | None = None
    pdf_size: int | None = None
    pdf_modified_at: datetime | None = None
    pages: int
    chunks: int
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    embedding_dim: int
    vector_store: str
    hybrid_search: bool
    built_at: datetime | None = None
    llm_model: str
    llm_configured: bool
    error: str | None = None


class RagChunksResponse(BaseModel):
    model: str
    total: int
    chunks: list[RagChunk]


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="查询文本")
    top_k: int = Field(default=5, ge=1, le=20, description="召回数量")


class RagSearchResponse(BaseModel):
    query: str
    model: str
    matches: list[RagSource]


class FaqAskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    top_k: int = Field(default=5, ge=1, le=20, description="检索召回数量")
    history: list[ChatMessage] = Field(default_factory=list, description="多轮对话历史（可选）")


class FaqAskResponse(BaseModel):
    model: str
    question: str
    answer: str
    mode: Literal["faq", "chat"] = Field(
        default="faq",
        description="faq = 依据简历片段回答（sources 有值）；chat = 简历答不了，转普通对话",
    )
    sources: list[RagSource]
    usage: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Agent（带工具的会话）
# --------------------------------------------------------------------------- #


class AgentToolInfo(BaseModel):
    name: str
    description: str


class AgentInfoResponse(BaseModel):
    model: str
    configured: bool
    thread_backend: str = Field(..., description="会话记忆的存储方式")
    max_steps: int
    tools: list[AgentToolInfo]
    knowledge_documents: int
    knowledge_chunks: int


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户这一轮说的话")
    thread_id: str | None = Field(default=None, description="会话 id；不传则新建一个并返回")


class AgentStepOut(BaseModel):
    """agent 这一轮里的某次工具调用。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None


class AgentChatResponse(BaseModel):
    thread_id: str
    answer: str
    steps: list[AgentStepOut] = Field(default_factory=list)
    sources: list[RagSource] = Field(default_factory=list)
    usage: dict[str, Any] | None = None


class AgentThreadResponse(BaseModel):
    thread_id: str
    messages: list[ChatMessage]


class KnowledgeAddRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="资料标题")
    text: str = Field(..., min_length=1, description="正文，会切分后向量化")
    source: str | None = Field(default=None, description="可选的来源说明")


class KnowledgeDocumentOut(BaseModel):
    id: str
    title: str
    source: str | None = None
    chars: int
    chunks: int
    added_at: datetime


class KnowledgeListResponse(BaseModel):
    model: str
    total: int
    chunks: int
    documents: list[KnowledgeDocumentOut]


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)


class KnowledgeHitOut(BaseModel):
    document_id: str
    title: str
    content: str
    score: float
    vector_score: float | None = None


class KnowledgeSearchResponse(BaseModel):
    query: str
    model: str
    matches: list[KnowledgeHitOut]


class KnowledgeDeleteResponse(BaseModel):
    id: str
    deleted: bool
