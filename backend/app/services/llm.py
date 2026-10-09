"""DeepSeek 客户端（OpenAI 兼容协议）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings


class DeepSeekNotConfiguredError(RuntimeError):
    """缺少 DEEPSEEK_API_KEY 时抛出。"""


class DeepSeekService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.deepseek_model
        self.temperature = settings.deepseek_temperature
        self.max_tokens = settings.deepseek_max_tokens
        self._api_key = settings.deepseek_api_key
        self._base_url = settings.deepseek_base_url
        self._client: AsyncOpenAI | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def client(self) -> AsyncOpenAI:
        if not self._api_key:
            raise DeepSeekNotConfiguredError("DEEPSEEK_API_KEY 未配置")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def complete(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any] | None]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage.model_dump() if response.usage else None
        return content, usage

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


@lru_cache
def get_deepseek_service() -> DeepSeekService:
    return DeepSeekService()
