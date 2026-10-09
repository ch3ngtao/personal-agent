"""Agent 接口：带工具调用的会话，以及运行时可增删的补充知识库。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentInfoResponse,
    AgentStepOut,
    AgentThreadResponse,
    KnowledgeAddRequest,
    KnowledgeDeleteResponse,
    KnowledgeDocumentOut,
    KnowledgeHitOut,
    KnowledgeListResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RagSource,
)
from app.services.agent import AgentService, get_agent_service
from app.services.knowledge import KnowledgeDocument, get_knowledge_store
from app.services.llm import DeepSeekNotConfiguredError

router = APIRouter(prefix="/agent", tags=["agent"])

NOT_CONFIGURED = "DEEPSEEK_API_KEY 未配置，请在 backend/.env 中设置后重启服务"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sources(items: list[dict[str, Any]]) -> list[RagSource]:
    """工具 artifact 里的引用片段 → 接口模型。"""
    return [RagSource(**item) for item in items]


def _document(document: KnowledgeDocument) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut(
        id=document.id,
        title=document.title,
        source=document.source,
        chars=document.chars,
        chunks=document.chunks,
        added_at=document.added_at,
    )


def _require_configured(service: AgentService) -> None:
    if not service.configured:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)


@router.get("/info", response_model=AgentInfoResponse, summary="Agent 能力与工具清单")
async def agent_info() -> AgentInfoResponse:
    service = get_agent_service()
    knowledge = get_knowledge_store()
    documents = await run_in_threadpool(knowledge.list_documents)
    return AgentInfoResponse(
        model=service.model_name,
        configured=service.configured,
        thread_backend=f"{type(service.checkpointer).__module__}.{type(service.checkpointer).__name__}",
        max_steps=service.recursion_limit,
        tools=[
            {"name": definition.name, "description": (definition.description or "").strip()}
            for definition in service.tools
        ],
        knowledge_documents=len(documents),
        knowledge_chunks=await run_in_threadpool(lambda: knowledge.total_chunks),
    )


@router.post("/chat", response_model=AgentChatResponse, summary="Agent 对话（一次性返回）")
async def agent_chat(payload: AgentChatRequest) -> AgentChatResponse:
    service = get_agent_service()
    _require_configured(service)

    try:
        reply = await service.ainvoke(payload.message, payload.thread_id)
    except DeepSeekNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED) from exc
    except Exception as exc:  # noqa: BLE001 - 统一转成 502 返回给前端
        raise HTTPException(status_code=502, detail=f"Agent 调用失败: {exc}") from exc

    return AgentChatResponse(
        thread_id=reply.thread_id,
        answer=reply.answer,
        steps=[AgentStepOut(name=step.name, args=step.args, summary=step.summary) for step in reply.steps],
        sources=_sources(reply.sources),
        usage=reply.usage,
    )


@router.post("/chat/stream", summary="Agent 对话（SSE 流式，含工具调用事件）")
async def agent_chat_stream(payload: AgentChatRequest) -> StreamingResponse:
    service = get_agent_service()

    async def event_stream():
        if not service.configured:
            yield _sse({"type": "error", "error": NOT_CONFIGURED})
            yield "data: [DONE]\n\n"
            return
        try:
            async for event in service.astream(payload.message, payload.thread_id):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - 把异常推给前端而不是断开连接
            yield _sse({"type": "error", "error": f"Agent 调用失败: {exc}"})
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


@router.get("/threads/{thread_id}", response_model=AgentThreadResponse, summary="查看会话历史")
async def agent_thread(thread_id: str) -> AgentThreadResponse:
    service = get_agent_service()
    messages = await run_in_threadpool(service.history, thread_id)
    return AgentThreadResponse(thread_id=thread_id, messages=messages)


@router.delete("/threads/{thread_id}", response_model=AgentThreadResponse, summary="清空会话记忆")
async def agent_thread_reset(thread_id: str) -> AgentThreadResponse:
    service = get_agent_service()
    await run_in_threadpool(service.reset, thread_id)
    return AgentThreadResponse(thread_id=thread_id, messages=[])


@router.post("/knowledge", response_model=KnowledgeDocumentOut, summary="新增一篇补充知识")
async def knowledge_add(payload: KnowledgeAddRequest) -> KnowledgeDocumentOut:
    store = get_knowledge_store()
    try:
        document = await run_in_threadpool(store.add, payload.title, payload.text, payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 例如向量模型下载失败
        raise HTTPException(status_code=500, detail=f"写入知识库失败: {exc}") from exc
    return _document(document)


@router.get("/knowledge", response_model=KnowledgeListResponse, summary="查看补充知识库")
async def knowledge_list() -> KnowledgeListResponse:
    store = get_knowledge_store()
    documents = await run_in_threadpool(store.list_documents)
    return KnowledgeListResponse(
        model=store.model_name,
        total=len(documents),
        chunks=await run_in_threadpool(lambda: store.total_chunks),
        documents=[_document(document) for document in documents],
    )


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse, summary="检索补充知识库")
async def knowledge_search(payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    store = get_knowledge_store()
    hits = await run_in_threadpool(store.search, payload.query, payload.top_k)
    return KnowledgeSearchResponse(
        query=payload.query,
        model=store.model_name,
        matches=[
            KnowledgeHitOut(
                document_id=hit.document_id,
                title=hit.title,
                content=hit.content,
                score=hit.score,
                vector_score=hit.vector_score,
            )
            for hit in hits
        ],
    )


@router.delete("/knowledge/{document_id}", response_model=KnowledgeDeleteResponse, summary="删除一篇补充知识")
async def knowledge_delete(document_id: str) -> KnowledgeDeleteResponse:
    store = get_knowledge_store()
    deleted = await run_in_threadpool(store.remove, document_id)
    return KnowledgeDeleteResponse(id=document_id, deleted=deleted)
