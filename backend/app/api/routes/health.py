from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthResponse
from app.services.llm import get_deepseek_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health() -> HealthResponse:
    settings = get_settings()
    llm = get_deepseek_service()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.environment,
        embedding_model=settings.embedding_model,
        llm_model=llm.model,
        llm_configured=llm.configured,
    )
