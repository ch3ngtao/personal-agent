from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse
from app.services.llm import get_deepseek_service

router = APIRouter(tags=["chat"])

NOT_CONFIGURED = "DEEPSEEK_API_KEY 未配置，请在 backend/.env 中设置后重启服务"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse, summary="DeepSeek 对话")
async def chat(payload: ChatRequest) -> ChatResponse:
    service = get_deepseek_service()
    if not service.configured:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)

    messages = [message.model_dump() for message in payload.messages]
    try:
        content, usage = await service.complete(messages)
    except Exception as exc:  # noqa: BLE001 - 统一转成 502 返回给前端
        raise HTTPException(status_code=502, detail=f"DeepSeek 调用失败: {exc}") from exc

    return ChatResponse(model=service.model, content=content, usage=usage)


@router.post("/chat/stream", summary="DeepSeek 对话（SSE 流式）")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    service = get_deepseek_service()
    messages = [message.model_dump() for message in payload.messages]

    async def event_stream():
        if not service.configured:
            yield _sse({"error": NOT_CONFIGURED})
            return
        try:
            async for delta in service.stream(messages):
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
