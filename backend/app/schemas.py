"""请求 / 响应模型。"""

from __future__ import annotations

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
