"""问答路由：先检索简历，判断「这些片段能不能回答问题」，不能就转普通对话。

为什么需要这一步：``/api/faq/ask`` 原本一定会把检索到的片段塞给模型，
而简历 prompt 又规定「片段里没有就回答『简历里没有找到相关信息』」。
于是「今天几号」「帮我写段代码」这类和简历无关的问题，也会收到那句兜底文案。

判定**不能用检索分数**：融合后的 ``score`` 是每次在候选集里做归一化的相对分，
top-1 天然接近 1.0（实测「帮我写快速排序代码」也能拿 1.000）；``vector_score``
的相关/无关区间也大面积重叠（相关 0.39~0.61，无关 0.31~0.52）。
所以这里改用一次极短的模型判定：只输出 yes / no，``max_tokens=4``、温度 0。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.core import clock
from app.services.llm import DeepSeekService
from app.services.rag import ResumeChunk, ResumeIndex

logger = logging.getLogger(__name__)

# 判定用的 prompt：只输出 yes / no，避免模型解释。
ROUTER_SYSTEM_PROMPT = """你在判断「检索到的简历片段」能不能回答用户的问题。

只看片段本身，不要用你自己的知识补充。判断标准：
- 片段里能直接找到答案，或者能明确支撑答案 → yes
- 片段只是碰巧含有相同的技术词，实际答不了这个问题 → no
- 问题和候选人简历无关（日期、天气、写代码、闲聊等） → no
- 片段为空 → no

只输出 yes 或 no，不要输出任何其他内容。"""

# 转普通对话时的 prompt。注意两个点：
# 1. 注入当前时间——大模型自己没有时钟，不注入就只能瞎猜或拒答；
# 2. 明确告诉它这次没有简历资料，避免凭空编造候选人的经历。
CHAT_SYSTEM_PROMPT = """你是「示例用户」个人主页上的 AI 助手。现在是 {now}。

对方这个问题没有在简历资料里找到依据，所以这次不引用简历，用你的通用能力回答：
- 用简体中文，简洁准确，必要时分点。
- 与简历无关的问题（日期、时间、技术问题、闲聊等）正常回答。
- 涉及日期、时间、星期、相对时间时，一律以上面给出的当前时间为准——你自己没有时钟，
  不要凭记忆猜，也不要说「拿不到时间」。答案里的时间可能比真实时间晚几秒（生成需要耗时），
  精确到分钟即可，不确定就说明是大约时间。
- 绝对不要编造示例用户的经历、技能、学历、求职意向等信息——这次你手上没有他的资料。
  如果对方问的正是这些，就直接说明这次没有查到，建议他换个问法或直接联系本人。"""


@dataclass(slots=True)
class AnswerPlan:
    """一次问答的走法：用简历回答，还是转普通对话。"""

    mode: Literal["faq", "chat"]
    messages: list[dict[str, Any]]
    sources: list[ResumeChunk] = field(default_factory=list)
    judged: bool = False


def build_router_messages(question: str, chunks: Sequence[ResumeChunk]) -> list[dict[str, Any]]:
    context = "\n\n".join(f"[片段 {position}]\n{chunk.content}" for position, chunk in enumerate(chunks, start=1))
    return [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户的问题：{question}\n\n检索到的简历片段：\n{context}"},
    ]


def build_chat_messages(
    question: str,
    history: Sequence[dict[str, Any]] | None = None,
    moment: datetime | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT.format(now=clock.describe(moment))}
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


def parse_decision(text: str) -> bool | None:
    """把模型输出解析成布尔值，解析不了返回 ``None``。"""
    normalized = re.sub(r"[\s。.!！,，:：\"'`*]", "", (text or "").lower())
    if not normalized:
        return None
    if normalized.startswith(("yes", "是", "有")):
        return True
    if normalized.startswith(("no", "否", "没", "不是", "无法")):
        return False
    head = normalized[:12]
    if "yes" in head:
        return True
    if "no" in head:
        return False
    return None


async def can_answer_with_resume(
    llm: DeepSeekService,
    question: str,
    chunks: Sequence[ResumeChunk],
) -> bool:
    """判断检索到的片段能否回答问题。

    判定本身失败（网络异常、返回无法解析）时保守地按「命中」处理：
    宁可退回原来的兜底文案，也不要让简历问题被误判成闲聊、答出没有依据的内容。
    """
    if not chunks:
        return False

    try:
        content, _ = await llm.complete(
            build_router_messages(question, chunks),
            temperature=0.0,
            max_tokens=4,
        )
    except Exception as exc:  # noqa: BLE001 - 判定失败不应该让整个请求失败
        logger.warning("简历路由判定失败（%s），按「命中」处理", exc)
        return True

    decision = parse_decision(content)
    if decision is None:
        logger.warning("简历路由判定返回无法解析的内容 %r，按「命中」处理", content)
        return True
    return decision


async def plan_answer(
    *,
    index: ResumeIndex,
    llm: DeepSeekService,
    question: str,
    chunks: Sequence[ResumeChunk],
    history: Sequence[dict[str, Any]] | None = None,
    router_enabled: bool = True,
) -> AnswerPlan:
    """决定这次问答走哪条链路，并把要发给模型的 messages 准备好。"""
    if router_enabled:
        hit = await can_answer_with_resume(llm, question, chunks)
    else:
        hit = True

    if hit and chunks:
        sources = list(chunks)
        return AnswerPlan(
            mode="faq",
            messages=index.build_messages(question, sources, history),
            sources=sources,
            judged=router_enabled,
        )

    return AnswerPlan(
        mode="chat",
        messages=build_chat_messages(question, history),
        sources=[],
        judged=router_enabled,
    )
