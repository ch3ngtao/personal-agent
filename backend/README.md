# ch3ngtao-web backend

FastAPI 服务，提供两组能力：

- **向量**：`all-MiniLM-L6-v2`（sentence-transformers）本地推理，输出 384 维向量 / 余弦相似度。
- **简历 FAQ（RAG）**：LangChain 切分简历 PDF → 向量化 → 检索 → DeepSeek 生成答案。
- **Agent 会话**：LangGraph 的「模型 ↔ 工具」循环 + 服务端会话记忆 + 可增删的补充知识库。
- **大模型**：DeepSeek（OpenAI 兼容接口），支持一次性与 SSE 流式返回。

## 简历 FAQ（RAG）

`app/services/rag.py` 把简历 PDF 变成可检索的知识库：

```
简历 PDF ──pypdf 逐页读取──▶ Document ──按章节 / 条目切块 + 递归切分──▶ chunk
        ──EmbeddingService（LangChain Embeddings 适配）──▶ InMemoryVectorStore
        ──向量 + BM25 混合检索──▶ top-k 片段 ──DeepSeek──▶ 答案 + sources
```

切分做了结构感知：先按简历章节（求职意向 / 相关技能 / 工作经历 / 项目经历 …）和日期条目
（如「2022.10-至今 示例科技」）切块，再在块内递归切到目标粒度，并给每个片段补上章节
（必要时还有公司 / 项目）上下文——简历常把公司名放在页尾、详情放到下一页，逐页切分会把
两者拆开，导致「他最近在哪家公司」这类问题召回不到。多条目章节还会额外生成一条只列
「时间 + 公司 / 项目 + 职位」的索引片段，专门承接这类问题。

答案正文不再输出「片段 x · 第 x 页」标注，命中的片段由接口的 `sources` 字段返回
（含 `index` / `page` / `section` / `score`），由前端单独展示。

检索之后还会做一次**问答路由**（`app/services/answering.py`）：用一次极短的模型判定
（只输出 yes / no，`max_tokens=4`、温度 0）确认这些片段能不能回答问题——

- 能 → 走 RAG，`mode="faq"`，带 `sources`；
- 不能（日期、天气、写代码、闲聊，或片段只是撞词）→ 转普通对话，`mode="chat"`、`sources=[]`，
  并在 system prompt 里注入当前日期时间（精确到分钟）——大模型自己没有时钟，不注入就只能拒答或瞎猜。

简历链路的 system prompt 里也会补一句今天的日期，否则模型没法判断「2022.10-至今」是否仍然在职。
时间统一由 `app/core/clock.py` 按配置的 `TIMEZONE` 取：容器基础镜像默认是 UTC，
直接用 `datetime.now().astimezone()` 会差 8 小时（凌晨时段连日期都是错的），所以显式指定时区，
并依赖 `tzdata` 提供 IANA 时区数据（slim 镜像不自带）。

判定不用检索分数是因为它分不开：融合 `score` 是每次在候选集里归一化的相对分，top-1 天然接近
1.0（实测「帮我写快速排序代码」也能拿 1.000）；`vector_score` 的相关/无关区间大面积重叠
（相关 0.39~0.61、无关 0.31~0.52）。判定调用失败或返回无法解析时保守地按「命中」处理，
宁可退回兜底文案，也不要让简历问题被误判成闲聊。设 `FAQ_ROUTER_ENABLED=false` 可关闭。

相关配置（见 `.env.example`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RESUME_PDF_PATH` | 空 | 简历 PDF 路径；留空自动在仓库根目录 / `backend/data` / `backend` 里找第一个 PDF |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | RAG 专用向量模型；留空则复用 `EMBEDDING_MODEL` |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `320` / `60` | LangChain 切分粒度与重叠字符数 |
| `RAG_TOP_K` | `5` | 每次问答召回的片段数 |
| `RAG_HYBRID` | `true` | 是否启用「向量 + BM25」混合检索 |
| `RAG_SECTION_AWARE` | `true` | 整节提问（「有哪些项目经验」）时把该章节条目全部交给模型，并带上补充章节（项目经历 + 其他项目），避免 top-k 漏条目 |
| `RAG_MAX_CONTEXT_CHARS` | `4000` | 章节扩展 / 条目补全后拼给模型的最大字符数 |
| `RAG_CACHE_PATH` | `.cache/rag-index.json` | chunk 与向量的缓存文件，PDF 或参数变化自动失效 |
| `RAG_PRELOAD` | `false` | 服务启动时就构建索引 |

接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/faq/status` | 索引状态（PDF、页数、chunk 数、向量模型与维度） |
| POST | `/api/faq/index` | 构建索引，`?force=true` 强制重建 |
| GET | `/api/faq/chunks` | 查看切分后的 chunk |
| POST | `/api/faq/search` | 只检索，不调用大模型 |
| POST | `/api/faq/ask` | 问答（一次性返回答案 + 引用片段） |
| POST | `/api/faq/ask/stream` | 问答（SSE：先推片段，再流式推答案） |

## Agent

`app/services/agent.py` 用 ``langchain.agents.create_agent``（底层是 LangGraph）搭了一个
「模型 ↔ 工具」循环，和固定的 RAG 链路分开：

| | `/api/faq/*` | `/api/agent/*` |
| --- | --- | --- |
| 控制流 | 代码写死的检索 → 生成 | 模型自主决定调不调工具、调几轮 |
| 工具 | 无 | `search_resume`、`search_knowledge`、`get_current_time` |
| 多轮记忆 | 前端回传 `history` | 服务端 checkpointer（`InMemorySaver`，按 `thread_id`） |

前端右下角的会话气泡走的是 agent；`/api/faq/*` 保留为固定链路，可单独调用、便于对照。

相关文件：

| 文件 | 作用 |
| --- | --- |
| `app/services/agent.py` | agent 图、模型、checkpointer、会话读写与流式事件 |
| `app/services/tools.py` | 工具定义；加工具改这里即可 |
| `app/services/knowledge.py` | 补充知识库：运行时新增文本 → 切分 → 向量化 → 检索 |
| `app/services/retrieval.py` | 简历索引与知识库共用的「向量 + BM25」融合打分 |

接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/agent/info` | 模型、工具清单、知识库概况 |
| POST | `/api/agent/chat` | 对话（一次性，返回答案 + 工具步骤 + 引用） |
| POST | `/api/agent/chat/stream` | 对话（SSE：meta / tool_start / tool_end / delta / done） |
| GET | `/api/agent/threads/{id}` | 会话历史 |
| DELETE | `/api/agent/threads/{id}` | 清空会话记忆 |
| POST | `/api/agent/knowledge` | 新增一篇补充知识 |
| GET | `/api/agent/knowledge` | 查看补充知识库 |
| POST | `/api/agent/knowledge/search` | 检索补充知识库 |
| DELETE | `/api/agent/knowledge/{id}` | 删除一篇补充知识 |

配置（见 `.env.example`）：`AGENT_MAX_STEPS` 控制一次提问里最多走多少步，
`AGENT_KNOWLEDGE_PATH` / `AGENT_KNOWLEDGE_CHUNK_SIZE` / `AGENT_KNOWLEDGE_CHUNK_OVERLAP`
控制补充知识库的落盘位置与切分粒度。

> 会话记忆目前用的是内存版 checkpointer，进程重启后会话会清空。
> 要持久化，把 `InMemorySaver` 换成 `langgraph-checkpoint-sqlite` 的 `AsyncSqliteSaver`
> 或 Postgres saver 即可，`AgentService` 的构造参数已经留好了注入点。

## 运行

```bash
cp .env.example .env      # 填 DEEPSEEK_API_KEY
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
uv run pytest
uv run ruff check .
```
