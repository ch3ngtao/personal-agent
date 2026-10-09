from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    EmbeddingRequest,
    EmbeddingResponse,
    SimilarityMatch,
    SimilarityRequest,
    SimilarityResponse,
)
from app.services.embeddings import get_embedding_service

router = APIRouter(tags=["embeddings"])


@router.post("/embeddings", response_model=EmbeddingResponse, summary="文本向量化")
async def create_embeddings(payload: EmbeddingRequest) -> EmbeddingResponse:
    service = get_embedding_service()
    vectors = await run_in_threadpool(service.encode, payload.texts)
    return EmbeddingResponse(
        model=service.model_name,
        dimension=len(vectors[0]) if vectors else 0,
        vectors=vectors,
    )


@router.post("/similarity", response_model=SimilarityResponse, summary="余弦相似度排序")
async def similarity(payload: SimilarityRequest) -> SimilarityResponse:
    service = get_embedding_service()
    ranked = await run_in_threadpool(service.similarity, payload.source, payload.targets)
    return SimilarityResponse(
        model=service.model_name,
        dimension=service.dimension,
        matches=[SimilarityMatch(index=index, text=text, score=score) for index, text, score in ranked],
    )
