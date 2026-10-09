from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.preload_embedding_model:
        from app.services.embeddings import get_embedding_service

        logger.info("预加载向量模型 %s ...", settings.embedding_model)
        await run_in_threadpool(lambda: get_embedding_service().model)
        logger.info("向量模型加载完成")
    if settings.rag_preload:
        from app.services.rag import get_resume_index

        logger.info("预加载简历索引 ...")
        try:
            await run_in_threadpool(get_resume_index().ensure_ready)
            logger.info("简历索引加载完成")
        except Exception as exc:  # noqa: BLE001 - 预加载失败不阻止服务启动
            logger.warning("简历索引预加载失败：%s（首次调用 FAQ 接口时会重试）", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="FastAPI + all-MiniLM-L6-v2 + LangChain 简历 RAG + DeepSeek",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
