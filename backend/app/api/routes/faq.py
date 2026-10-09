"""简历 FAQ 接口：PDF 切分状态、片段检索、RAG 问答（一次性 + 流式）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.schemas import (
    FaqAskRequest,
    FaqAskResponse,
    RagChunk,
    RagChunksResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagSource,
    RagStatusResponse,
)
from app.services.answering import AnswerPlan, plan_answer
from app.services.llm import get_deepseek_service
from app.services.rag import (
    RagIndexError,
    ResumeChunk,
    ResumeIndex,
    ResumePdfNotFoundError,
    get_resume_index,
)

router = APIRouter(prefix="/faq", tags=["faq"])

NOT_CONFIGURED = "DEEPSEEK_API_KEY 未配置，请在 backend/.env 中设置后重启服务"


def _source(chunk: ResumeChunk) -> RagSource:
    return RagSource(
        index=chunk.index,
        content=chunk.content,
        page=chunk.page,
        section=chunk.section,
        score=chunk.score,
        vector_score=chunk.vector_score,
    )


async def _search(index: ResumeIndex, query: str, top_k: int) -> list[ResumeChunk]:
    """检索是 CPU 密集操作（首次还会建索引），放到线程池里执行。"""
    try:
        return await run_in_threadpool(index.search, query, top_k)
    except ResumePdfNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RagIndexError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 例如向量模型下载失败，转成可读的错误返回
        raise HTTPException(status_code=500, detail=f"简历索引不可用: {exc}") from exc


async def _plan(question: str, top_k: int, history: list[dict[str, Any]]) -> tuple[AnswerPlan, ResumeIndex]:
    """检索 → 判定这次能不能用简历回答 → 组装 messages。"""
    settings = get_settings()
    index = get_resume_index()
    chunks = await _search(index, question, top_k)
    plan = await plan_answer(
        index=index,
        llm=get_deepseek_service(),
        question=question,
        chunks=chunks,
        history=history,
        router_enabled=settings.faq_router_enabled,
    )
    return plan, index


@router.get("/status", response_model=RagStatusResponse, summary="简历索引状态")
async def faq_status() -> RagStatusResponse:
    index = get_resume_index()
    status = index.status()
    llm = get_deepseek_service()
    return RagStatusResponse(
        ready=status.ready,
        indexed=status.indexed,
        building=status.building,
        loaded_from_cache=status.loaded_from_cache,
        pdf_name=status.pdf_name,
        pdf_path=status.pdf_path,
        pdf_size=status.pdf_size,
        pdf_modified_at=status.pdf_modified_at,
        pages=status.pages,
        chunks=status.chunks,
        chunk_size=status.chunk_size,
        chunk_overlap=status.chunk_overlap,
        embedding_model=status.embedding_model,
        embedding_dim=status.embedding_dim,
        vector_store=status.vector_store,
        hybrid_search=status.hybrid_search,
        built_at=status.built_at,
        llm_model=llm.model,
        llm_configured=llm.configured,
        error=status.error,
    )


@router.post("/index", response_model=RagStatusResponse, summary="构建 / 重建简历索引")
async def faq_build_index(
    force: bool = Query(default=False, description="true = 忽略缓存强制重建"),
) -> RagStatusResponse:
    index = get_resume_index()
    try:
        if force:
            await run_in_threadpool(index.rebuild)
        else:
            await run_in_threadpool(index.ensure_ready)
    except ResumePdfNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RagIndexError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 例如向量模型下载失败，转成可读的错误返回
        raise HTTPException(status_code=500, detail=f"简历索引构建失败: {exc}") from exc
    return await faq_status()


@router.get("/chunks", response_model=RagChunksResponse, summary="查看切分后的 chunk")
async def faq_chunks(
    limit: int | None = Query(default=None, ge=1, le=200, description="只返回前 N 个"),
) -> RagChunksResponse:
    index = get_resume_index()
    try:
        chunks = await run_in_threadpool(index.list_chunks, limit)
    except ResumePdfNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RagIndexError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 例如向量模型下载失败，转成可读的错误返回
        raise HTTPException(status_code=500, detail=f"简历索引不可用: {exc}") from exc

    return RagChunksResponse(
        model=index.embedding.service.model_name,
        total=index.status().chunks,
        chunks=[
            RagChunk(
                index=chunk.index,
                content=chunk.content,
                page=chunk.page,
                section=chunk.section,
                chars=chunk.chars,
            )
            for chunk in chunks
        ],
    )


@router.post("/search", response_model=RagSearchResponse, summary="只做检索，不调用大模型")
async def faq_search(payload: RagSearchRequest) -> RagSearchResponse:
    index = get_resume_index()
    matches = await _search(index, payload.query, payload.top_k)
    return RagSearchResponse(
        query=payload.query,
        model=index.embedding.service.model_name,
        matches=[_source(chunk) for chunk in matches],
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/ask", response_model=FaqAskResponse, summary="简历 FAQ 问答（一次性返回）")
async def faq_ask(payload: FaqAskRequest) -> FaqAskResponse:
    llm = get_deepseek_service()
    if not llm.configured:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)

    history = [message.model_dump() for message in payload.history]
    plan, _ = await _plan(payload.question, payload.top_k, history)

    try:
        content, usage = await llm.complete(plan.messages)
    except Exception as exc:  # noqa: BLE001 - 统一转成 502 返回给前端
        raise HTTPException(status_code=502, detail=f"DeepSeek 调用失败: {exc}") from exc

    return FaqAskResponse(
        model=llm.model,
        question=payload.question,
        answer=content,
        mode=plan.mode,
        sources=[_source(chunk) for chunk in plan.sources],
        usage=usage,
    )


@router.post("/ask/stream", summary="简历 FAQ 问答（SSE 流式）")
async def faq_ask_stream(payload: FaqAskRequest) -> StreamingResponse:
    llm = get_deepseek_service()

    # 检索与判定都在生成器外完成，避免阻塞事件循环。
    plan: AnswerPlan | None = None
    setup_error: str | None = None

    if not llm.configured:
        setup_error = NOT_CONFIGURED
    else:
        try:
            plan, _ = await _plan(
                payload.question,
                payload.top_k,
                [message.model_dump() for message in payload.history],
            )
        except HTTPException as exc:
            setup_error = str(exc.detail)

    async def event_stream():
        if setup_error or plan is None:
            yield _sse({"error": setup_error})
            yield "data: [DONE]\n\n"
            return

        # 先把走法与引用发给前端（mode=chat 时 sources 为空），再逐段推答案。
        yield _sse(
            {
                "model": llm.model,
                "mode": plan.mode,
                "sources": [_source(chunk).model_dump() for chunk in plan.sources],
            }
        )
        try:
            async for delta in llm.stream(plan.messages):
                yield _sse({"content": delta})
        except Exception as exc:  # noqa: BLE001 - 把异常推给前端而不是断开连接
            yield _sse({"error": f"DeepSeek 调用失败: {exc}"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
