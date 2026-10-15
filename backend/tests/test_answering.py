"""问答路由测试：命中简历走 RAG，答不了的问题转普通对话。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import answering
from app.services.rag import ResumeChunk


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class _FakeIndex:
    """只记录有没有走简历 prompt。"""

    def __init__(self) -> None:
        self.calls: list[list[ResumeChunk]] = []

    def build_messages(self, question: str, chunks: list[ResumeChunk], history=None) -> list[dict[str, Any]]:  # noqa: ANN001
        self.calls.append(list(chunks))
        return [{"role": "system", "content": "RESUME_PROMPT"}, {"role": "user", "content": question}]


class _FakeLLM:
    """判定用的假模型。"""

    model = "deepseek-chat"
    configured = True

    def __init__(self, answer: Any = "yes") -> None:
        self.answer = answer
        self.calls: list[tuple[list[dict[str, Any]], float | None, int | None]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, dict[str, int] | None]:
        self.calls.append((messages, temperature, max_tokens))
        if isinstance(self.answer, Exception):
            raise self.answer
        return str(self.answer), {"total_tokens": 6}


def _chunks() -> list[ResumeChunk]:
    return [ResumeChunk(index=0, content="2022.10-至今 XX 公司 前端工程师", page=1, section="工作经历", score=0.9)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes", True),
        ("Yes.", True),
        ("  YES  ", True),
        ("是的", True),
        ("no", False),
        ("No。", False),
        ("没有", False),
        ("无法回答", False),
        ("", None),
        ("这不是一个答案", None),
    ],
)
def test_parse_decision(text: str, expected: bool | None) -> None:
    assert answering.parse_decision(text) == expected


async def test_judge_uses_low_temperature_and_tiny_output() -> None:
    llm = _FakeLLM("no")

    assert await answering.can_answer_with_resume(llm, "今天几号", _chunks()) is False

    messages, temperature, max_tokens = llm.calls[0]
    assert temperature == 0.0
    assert max_tokens == 4
    assert "2022.10-至今" in messages[1]["content"]


async def test_empty_chunks_skip_judge() -> None:
    llm = _FakeLLM("yes")

    assert await answering.can_answer_with_resume(llm, "你好", []) is False
    assert llm.calls == []


async def test_judge_failure_falls_back_to_resume() -> None:
    llm = _FakeLLM(RuntimeError("网络断了"))

    assert await answering.can_answer_with_resume(llm, "他的薪资", _chunks()) is True


async def test_plan_uses_chat_when_not_answerable() -> None:
    index, llm = _FakeIndex(), _FakeLLM("no")

    plan = await answering.plan_answer(
        index=index,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        question="帮我写一段快速排序",
        chunks=_chunks(),
    )

    assert plan.mode == "chat"
    assert plan.sources == []
    assert index.calls == []  # 没有走简历 prompt
    system = plan.messages[0]["content"]
    assert system.startswith(f"你是「{get_settings().resume_name}」个人主页上的 AI 助手")
    assert "现在是" in system
    # 注入到分钟，模型才能回答「现在几点」；只给日期的话它只能拒答
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", system)
    # 转普通对话时不能把简历片段带进去
    assert all("2022.10-至今" not in message["content"] for message in plan.messages)


async def test_plan_uses_resume_when_answerable() -> None:
    index, llm = _FakeIndex(), _FakeLLM("yes")

    plan = await answering.plan_answer(
        index=index,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        question="他在哪家公司？",
        chunks=_chunks(),
    )

    assert plan.mode == "faq"
    assert len(plan.sources) == 1
    assert index.calls == [_chunks()]


async def test_router_can_be_disabled() -> None:
    index, llm = _FakeIndex(), _FakeLLM("no")

    plan = await answering.plan_answer(
        index=index,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        question="今天几号",
        chunks=_chunks(),
        router_enabled=False,
    )

    assert plan.mode == "faq"
    assert llm.calls == []  # 关掉路由就不再额外判定


def _patch_route(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """让 /api/faq/ask* 直接走指定的链路，并挡掉真实模型调用。"""

    async def fake_plan(*_args: Any, **_kwargs: Any) -> answering.AnswerPlan:
        sources = _chunks() if mode == "faq" else []
        return answering.AnswerPlan(mode=mode, messages=[{"role": "user", "content": "hi"}], sources=sources)

    class _StubLLM:
        model = "deepseek-chat"
        configured = True

        async def complete(self, *_args: Any, **_kwargs: Any) -> tuple[str, None]:
            return "普通对话的回答", None

        async def stream(self, *_args: Any, **_kwargs: Any):
            yield "普通"
            yield "对话"

    monkeypatch.setattr("app.api.routes.faq.plan_answer", fake_plan)
    monkeypatch.setattr("app.api.routes.faq.get_deepseek_service", _StubLLM)


def test_ask_reports_chat_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_route(monkeypatch, "chat")

    body = client.post("/api/faq/ask", json={"question": "今天几号"}).json()

    assert body["mode"] == "chat"
    assert body["sources"] == []
    assert body["answer"] == "普通对话的回答"


def test_ask_stream_reports_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_route(monkeypatch, "chat")

    with client.stream("POST", "/api/faq/ask/stream", json={"question": "今天几号"}) as response:
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]

    assert events[0]["mode"] == "chat"
    assert events[0]["sources"] == []
    assert "".join(event.get("content", "") for event in events) == "普通对话"


def test_ask_stream_reports_faq_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_route(monkeypatch, "faq")

    with client.stream("POST", "/api/faq/ask/stream", json={"question": "他在哪家公司"}) as response:
        first = next(
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: [DONE]"
        )

    assert first["mode"] == "faq"
    assert len(first["sources"]) == 1
