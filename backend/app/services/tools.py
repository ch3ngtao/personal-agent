"""Agent 可调用的工具。

每个检索类工具都用 ``@tool(response_format="content_and_artifact")``：返回给模型的是
排版好的文本，而结构化的 ``sources``（页码 / 章节 / 相关度）放进 artifact——artifact 不会
进模型上下文，只用来给前端展示引用，避免把 JSON 噪声喂给模型。

想加新工具（查 GitHub、调内部接口、查日历…）：在 ``build_tools()`` 里再定义一个函数即可，
``@tool`` 会自动把函数名、docstring 和类型标注变成模型看到的工具描述和参数 schema。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from app.core import clock
from app.services.knowledge import get_knowledge_store
from app.services.rag import get_resume_index

RESUME_TOOL = "search_resume"
KNOWLEDGE_TOOL = "search_knowledge"
TIME_TOOL = "get_current_time"


def _format_hits(header: str, hits: list[tuple[str, float, str]]) -> str:
    """把命中片段排版成模型好读的文本：``[(来源, 相关度, 正文)]``。"""
    lines = [header]
    for position, (label, score, content) in enumerate(hits, start=1):
        lines.append(f"\n[{position}] {label}（相关度 {score:.2f}）\n{content}")
    return "\n".join(lines)


def build_tools() -> list[BaseTool]:
    """构造 agent 的工具集。"""
    resume_index = get_resume_index()
    knowledge_store = get_knowledge_store()

    @tool(response_format="content_and_artifact")
    def search_resume(query: str, top_k: int = 5) -> tuple[str, dict[str, Any]]:
        """在「示例用户的简历」里检索信息：工作经历、项目经验、技术栈、教育背景、求职意向等。

        任何和候选人本人经历、技能、背景相关的问题都应该先用这个工具查一次，
        不要凭常识或对话历史直接回答简历相关的问题。

        Args:
            query: 检索用的关键词或一句自然语言问题，例如「他做过的 AI 项目」。
            top_k: 返回片段数量，默认 5。
        """
        chunks = resume_index.search(query, top_k)
        if not chunks:
            return "简历里没有检索到相关内容。", {"tool": RESUME_TOOL, "query": query, "sources": []}

        text = _format_hits(
            f"在简历里检索「{query}」，命中 {len(chunks)} 段：",
            [
                (f"{chunk.section or '简历'} · 第 {chunk.page or '?'} 页", chunk.score, chunk.content)
                for chunk in chunks
            ],
        )
        artifact = {
            "tool": RESUME_TOOL,
            "query": query,
            "sources": [
                {
                    "index": chunk.index,
                    "content": chunk.content,
                    "page": chunk.page,
                    "section": chunk.section,
                    "score": chunk.score,
                    "vector_score": chunk.vector_score,
                }
                for chunk in chunks
            ],
        }
        return text, artifact

    @tool(response_format="content_and_artifact")
    def search_knowledge(query: str, top_k: int = 4) -> tuple[str, dict[str, Any]]:
        """在「补充知识库」里检索简历之外的内容：项目复盘、面试问答、补充说明等用户后加的资料。

        简历里查不到、或者问题明显在问「补充资料」时用它。如果知识库为空，会明确告诉你，
        这时不要编造内容。

        Args:
            query: 检索用的关键词或一句自然语言问题。
            top_k: 返回片段数量，默认 4。
        """
        hits = knowledge_store.search(query, top_k)
        if not hits:
            return "补充知识库还是空的，里面没有任何资料。", {
                "tool": KNOWLEDGE_TOOL,
                "query": query,
                "sources": [],
            }

        text = _format_hits(
            f"在补充知识库里检索「{query}」，命中 {len(hits)} 段：",
            [(f"资料《{hit.title}》", hit.score, hit.content) for hit in hits],
        )
        artifact = {
            "tool": KNOWLEDGE_TOOL,
            "query": query,
            "sources": [
                {
                    "index": position,
                    "content": hit.content,
                    "page": None,
                    "section": hit.title,
                    "score": hit.score,
                    "vector_score": hit.vector_score,
                }
                for position, hit in enumerate(hits)
            ],
        }
        return text, artifact

    @tool
    def get_current_time() -> str:
        """获取当前的日期和时间（几点几分、星期几）。

        两类问题必须用它：一是问「今天几号」「现在几点」这类时间问题——你自己没有时钟，
        凭记忆答一定会错；二是简历里出现「2022.10-至今」这类表述，需要结合今天判断
        「现在还在不在这家公司」。
        """
        return f"现在是 {clock.describe()}。"

    return [search_resume, search_knowledge, get_current_time]
