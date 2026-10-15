"""应用配置：全部通过环境变量 / .env 注入。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_name: str = "ch3ngtao-web API"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # 面向用户的时间统一按这个时区来（容器默认 UTC，所以要显式指定）
    timezone: str = "Asia/Shanghai"

    # ---- 向量模型 ----
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_normalize: bool = True
    preload_embedding_model: bool = False

    # ---- 简历 RAG（FAQ 问答）----
    # 简历主人的称呼：助手提示词里用到的名字。对外环境填对外那份简历上的名字，
    # 自己的环境填自己的名字（两个环境各有一份 .env）
    resume_name: str = "李四"
    # 简历文件名（相对仓库根目录 / backend 目录，也可以写绝对路径）。
    # 部署时由 compose 从 .env 注入，代码里不写死用哪份简历。
    resume_file: str | None = None
    # 简历 PDF 路径（比 RESUME_FILE 更优先，一般由容器里的挂载路径给出）。
    # 都留空时才在仓库根目录、backend/data、backend 目录下按名字找 PDF。
    resume_pdf_path: str | None = None
    # RAG 专用的向量模型（中文简历建议用中文模型）。留空则复用上面的 EMBEDDING_MODEL。
    rag_embedding_model: str | None = "BAAI/bge-small-zh-v1.5"
    # 切分后的 chunk 与向量缓存文件（相对 backend 目录）。
    rag_cache_path: str = ".cache/rag-index.json"
    # LangChain 递归切分的粒度（字符数）。
    rag_chunk_size: int = 320
    rag_chunk_overlap: int = 60
    # 每次问答召回的 chunk 数量。
    rag_top_k: int = 5
    # 是否用「向量 + BM25」混合检索（中文短查询下比纯向量稳）。
    rag_hybrid: bool = True
    # 章节级提问（如「有哪些项目经验」「工作经历」）直接把该章节的条目全部交给模型。
    # 关掉就退回「只用 top-k 片段」，问一整节时容易只答出其中一两条。
    rag_section_aware: bool = True
    # 拼给模型的片段总字符上限（章节扩展 / 条目补全时用来兜底，避免上下文失控）。
    rag_max_context_chars: int = 4000
    # true = 检索结果判定为答不了的问题转普通对话（而不是回「简历里没有找到相关信息」）。
    faq_router_enabled: bool = True
    # true = 服务启动时就构建索引。
    rag_preload: bool = False

    # ---- Agent（带工具的会话）----
    # 补充知识库：运行时可追加的文本，切分后进同一个向量模型，供 agent 检索。
    agent_knowledge_path: str = ".cache/knowledge.json"
    agent_knowledge_chunk_size: int = 400
    agent_knowledge_chunk_overlap: int = 60
    # 一次提问里模型最多走多少步（推理 + 工具调用），防止死循环。
    agent_max_steps: int = 8
    # 返回历史消息时的条数上限。
    agent_history_limit: int = 50

    # ---- DeepSeek ----
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.7
    deepseek_max_tokens: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()
