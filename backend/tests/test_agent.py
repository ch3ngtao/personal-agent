"""Agent 接口测试。

不依赖大模型的用例直接跑；需要向量模型（补写知识、检索）的用例在模型不可用时 skip。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.main import app
from app.services import agent as agent_module


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class _UnconfiguredAgent:
    """模拟没配 DEEPSEEK_API_KEY 的情况。"""

    model_name = "deepseek-chat"
    configured = False


def test_info_lists_tools(client: TestClient) -> None:
    body = client.get("/api/agent/info").json()

    names = [tool["name"] for tool in body["tools"]]
    assert names == ["search_resume", "search_knowledge", "get_current_time"]
    assert all(tool["description"] for tool in body["tools"])
    assert body["thread_backend"].endswith("InMemorySaver")
    assert body["max_steps"] >= 4


def test_chat_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.get_agent_service", _UnconfiguredAgent)

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_chat_stream_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.get_agent_service", _UnconfiguredAgent)

    with client.stream("POST", "/api/agent/chat/stream", json={"message": "你好"}) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line.startswith("data: ")]

    payload = json.loads(events[0][len("data: ") :])
    assert payload["type"] == "error"
    assert "DEEPSEEK_API_KEY" in payload["error"]
    assert events[-1] == "data: [DONE]"


def test_thread_history_empty_and_reset(client: TestClient) -> None:
    body = client.get("/api/agent/threads/not-exist").json()
    assert body == {"thread_id": "not-exist", "messages": []}

    assert client.delete("/api/agent/threads/not-exist").json()["messages"] == []


def test_current_turn_only_keeps_latest_round() -> None:
    messages = [
        HumanMessage(content="第一轮问题"),
        AIMessage(content="第一轮回答"),
        HumanMessage(content="第二轮问题"),
        AIMessage(content="第二轮回答"),
    ]

    turn = agent_module._current_turn(messages)

    assert [message.content for message in turn] == ["第二轮问题", "第二轮回答"]


def test_knowledge_roundtrip(client: TestClient) -> None:
    """新增 → 列表 → 检索 → 删除；向量模型不可用时跳过。"""
    try:
        created = client.post(
            "/api/agent/knowledge",
            json={
                "title": "测试资料",
                "text": "语音助手重构后，长会话滚动帧率从 24fps 提升到 55fps。",
            },
        )
    except Exception as exc:  # noqa: BLE001 - 例如向量模型无法下载
        pytest.skip(f"向量模型不可用，跳过知识库用例：{exc}")

    if created.status_code != 200:
        pytest.skip(f"无法写入知识库，跳过用例：{created.text}")

    document = created.json()
    assert document["chunks"] >= 1

    listing = client.get("/api/agent/knowledge").json()
    assert any(item["id"] == document["id"] for item in listing["documents"])

    hit = client.post("/api/agent/knowledge/search", json={"query": "帧率提升到多少"}).json()
    assert hit["matches"]
    assert "55fps" in hit["matches"][0]["content"]

    assert client.delete(f"/api/agent/knowledge/{document['id']}").json()["deleted"] is True
    assert client.delete(f"/api/agent/knowledge/{document['id']}").json()["deleted"] is False
