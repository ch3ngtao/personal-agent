"""会话 agent：LangGraph 的「模型 ↔ 工具」循环 + 服务端会话记忆。

和 ``rag.py`` 的区别：

- ``rag.py`` 是**固定链路**：一定会检索一次简历，然后生成答案，工具由代码写死。
- 这里是**完整 agent**：把简历检索、补充知识库检索、取当天日期都注册成工具，
  由模型自己决定调不调、调哪个、要不要多轮调用，直到它认为答得出来为止；
  会话状态由 checkpointer 存在服务端，前端不用再把 history 传来传去。

想扩展能力：在 ``tools.py`` 里加一个 ``@tool`` 函数就行，不需要改这里。
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings, get_settings
from app.services.llm import DeepSeekNotConfiguredError
from app.services.tools import build_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是「示例用户」个人主页上的 AI 助手，负责回答来访者关于他的问题。

你有这些工具：
- search_resume：检索他的简历（工作经历、项目经验、技术栈、教育背景、求职意向）。
- search_knowledge：检索「补充知识库」，里面是简历之外额外录入的资料。
- get_current_time：取当前的日期和时间。

工作方式：
1. 凡是涉及他本人经历、技能、背景的问题，先调用检索工具查证，不要凭常识或记忆回答；
   一次没查到就换个关键词再查，或者换个工具查。
2. 简历里没有、补充知识库也没有的信息，直接说「简历里没有找到相关信息」，不要编造；
   也不要替候选人承诺到岗时间、薪资底线等他自己没有写过的内容。
3. 涉及日期、时间、星期的问题（「今天几号」「现在几点」），以及「2022.10-至今」这种需要
   判断「现在还在不在职」的表述，都必须先调用 get_current_time——你自己没有时钟，
   不查就会答错或拒答。
4. 中间过程（要不要查、查什么、查到什么）用自己的话简短交代即可，例如「我查一下他的项目经历」。

回答风格：
- 简体中文，先给结论再给依据，分点、简洁。
- 不要在正文里写「片段 1」「第 2 页」这类来源标注，引用的出处由界面单独展示。
- 语气客观中立，不过度营销。
- 对方问的是某一整节时（如「有哪些项目经验」「介绍下工作经历」），检索结果里该节的条目要**全部列出**，
  按「时间 · 名称（角色）」起头，再写关键内容；不要只挑其中一两条，也不要把「·索引」片段当成
  正式内容照抄。条目多时用简洁的列表，不要为了省篇幅省略中间的项目。
  简历如果分了几节写同类内容（例如【项目经历】之外还有【其他项目】），补充章节里的条目也要一并
  列出——只有名称没有细节的，就按名称列出，不要因为细节少而整节跳过。
"""

# 会话在服务端保留多少条历史（防止上下文无限增长）。
HISTORY_LIMIT = 40


@dataclass(slots=True)
class ToolStep:
    """一次工具调用，用于前端展示「agent 都干了什么」。"""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AgentReply:
    thread_id: str
    answer: str
    steps: list[ToolStep]
    sources: list[dict[str, Any]]
    usage: dict[str, Any] | None = None


class AgentService:
    """进程内单例：一个 agent 图 + 一个 checkpointer + 一个线程池。"""

    def __init__(
        self,
        settings: Settings | None = None,
        tools: Sequence[BaseTool] | None = None,
        checkpointer: InMemorySaver | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tools: list[BaseTool] = list(tools) if tools is not None else build_tools()
        self.checkpointer = checkpointer or InMemorySaver()
        self.recursion_limit = max(4, self.settings.agent_max_steps)
        self._graph = None
        self._lock = threading.Lock()

    # ---- 模型与图 ----

    @property
    def configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    @property
    def model_name(self) -> str:
        return self.settings.deepseek_model

    def _build_model(self) -> ChatOpenAI:
        if not self.configured:
            raise DeepSeekNotConfiguredError("DEEPSEEK_API_KEY 未配置")
        return ChatOpenAI(
            model=self.settings.deepseek_model,
            base_url=self.settings.deepseek_base_url,
            api_key=self.settings.deepseek_api_key,
            temperature=self.settings.deepseek_temperature,
            max_tokens=self.settings.deepseek_max_tokens,
            timeout=60,
            max_retries=1,
            stream_usage=True,
        )

    @property
    def graph(self):
        """懒加载构建 agent 图：``model → tools → model → …`` 直到给出答案。"""
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    self._graph = create_agent(
                        model=self._build_model(),
                        tools=self.tools,
                        system_prompt=SYSTEM_PROMPT,
                        checkpointer=self.checkpointer,
                        name="resume_agent",
                    )
        return self._graph

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": self.recursion_limit}

    @staticmethod
    def new_thread_id() -> str:
        return uuid.uuid4().hex[:16]

    # ---- 会话 ----

    def history(self, thread_id: str) -> list[dict[str, str]]:
        """读回某个会话的消息（只保留有文字的 user / assistant 轮次）。"""
        if not self.configured:
            return []
        state = self.graph.get_state(self._config(thread_id))
        messages: Sequence[BaseMessage] = (state.values or {}).get("messages", [])
        history: list[dict[str, str]] = []
        for message in messages:
            if isinstance(message, AIMessage):
                text = _message_text(message)
                if text:
                    history.append({"role": "assistant", "content": text})
            elif isinstance(message, HumanMessage):
                text = _message_text(message)
                if text:
                    history.append({"role": "user", "content": text})
        return history[-HISTORY_LIMIT:]

    def reset(self, thread_id: str) -> None:
        """清空某个会话的记忆（线程 id 可以继续复用）。"""
        self.checkpointer.delete_thread(thread_id)

    # ---- 调用 ----

    async def ainvoke(self, message: str, thread_id: str | None = None) -> AgentReply:
        """跑一轮完整对话（非流式）。"""
        thread_id = thread_id or self.new_thread_id()
        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=self._config(thread_id),
        )
        messages: Sequence[BaseMessage] = result.get("messages", [])
        steps, sources = _collect_steps(_current_turn(messages))
        return AgentReply(
            thread_id=thread_id,
            answer=_last_answer(messages),
            steps=steps,
            sources=sources,
            usage=_usage(messages),
        )

    async def astream(self, message: str, thread_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """跑一轮对话，边跑边吐事件。

        事件类型：

        - ``model``：本次用的模型名
        - ``tool_start`` / ``tool_end``：agent 正在调哪个工具、拿到多少结果
        - ``delta``：答案的流式增量
        - ``done``：收尾，带上完整答案、引用片段和用量
        """
        thread_id = thread_id or self.new_thread_id()
        yield {"type": "meta", "thread_id": thread_id, "model": self.model_name}

        config = self._config(thread_id)
        async for event in self.graph.astream_events(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                text = _message_text(chunk) if isinstance(chunk, AIMessageChunk) else ""
                if text:
                    yield {"type": "delta", "content": text}
            elif kind == "on_tool_start":
                yield {
                    "type": "tool_start",
                    "name": str(event.get("name") or ""),
                    "args": event["data"].get("input") or {},
                }
            elif kind == "on_tool_end":
                payload = event["data"].get("output")
                artifact = _artifact_of(payload)
                yield {
                    "type": "tool_end",
                    "name": str(event.get("name") or ""),
                    "sources": list(artifact.get("sources", [])) if artifact else [],
                    "query": artifact.get("query") if artifact else None,
                }

        state = await self.graph.aget_state(config)
        messages: Sequence[BaseMessage] = (state.values or {}).get("messages", [])
        turn = _current_turn(messages)
        steps, sources = _collect_steps(turn)
        yield {
            "type": "done",
            "thread_id": thread_id,
            "answer": _last_answer(messages),
            "steps": [{"name": step.name, "args": step.args, "summary": step.summary} for step in steps],
            "sources": sources,
            "usage": _usage(turn),
        }


# --------------------------------------------------------------------------- #
# 消息解析工具
# --------------------------------------------------------------------------- #


def _message_text(message: Any) -> str:
    """兼容 content 是字符串或多模态块列表两种情况。"""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _artifact_of(payload: Any) -> dict[str, Any] | None:
    """工具返回的 artifact（结构化引用）不会进模型上下文，这里取回给前端。"""
    artifact = getattr(payload, "artifact", None)
    return artifact if isinstance(artifact, dict) else None


def _current_turn(messages: Sequence[BaseMessage]) -> Sequence[BaseMessage]:
    """只保留最后一条用户消息之后的部分，避免把历史轮次的工具调用算进本次结果。"""
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _last_answer(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _message_text(message)
            if text:
                return text
    return ""


def _collect_steps(messages: Sequence[BaseMessage]) -> tuple[list[ToolStep], list[dict[str, Any]]]:
    """把消息序列里的工具调用整理成步骤 + 引用片段。"""
    pending: dict[str, dict[str, Any]] = {}
    steps: list[ToolStep] = []
    sources: list[dict[str, Any]] = []

    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                pending[str(call.get("id") or "")] = {
                    "name": str(call.get("name") or ""),
                    "args": dict(call.get("args") or {}),
                }
        elif isinstance(message, ToolMessage):
            call = pending.pop(str(message.tool_call_id or ""), None)
            artifact = message.artifact if isinstance(message.artifact, dict) else None
            found = list(artifact.get("sources", [])) if artifact else []
            sources.extend(found)
            steps.append(
                ToolStep(
                    name=call["name"] if call else str(message.name or ""),
                    args=call["args"] if call else {},
                    summary=f"命中 {len(found)} 段" if found else _message_text(message)[:80],
                    sources=found,
                )
            )
    return steps, sources


def _usage(messages: Sequence[BaseMessage]) -> dict[str, Any] | None:
    """累加各次模型调用的 token 用量。"""
    total: dict[str, int] = {}
    for message in messages:
        metadata = getattr(message, "usage_metadata", None)
        if not isinstance(metadata, dict):
            continue
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = metadata.get(key)
            if isinstance(value, int):
                total[key] = total.get(key, 0) + value
    return total or None


_agent_service: AgentService | None = None
_agent_lock = threading.Lock()


def get_agent_service() -> AgentService:
    """进程内单例。"""
    global _agent_service
    if _agent_service is None:
        with _agent_lock:
            if _agent_service is None:
                _agent_service = AgentService()
    return _agent_service
