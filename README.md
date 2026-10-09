# ch3ngtao-web

一个前后端分离的项目骨架：

- **前端**：React 18 + TypeScript + Vite + Ant Design 5（Node.js 22.x）
- **后端**：Python 3.12 + FastAPI + uv + Docker
- **向量模型**：`all-MiniLM-L6-v2`（sentence-transformers，384 维，本地推理）
- **简历 FAQ（RAG）**：LangChain 切分简历 PDF → 向量化 → 检索 → DeepSeek 生成答案
  （RAG 默认用中文向量模型 `BAAI/bge-small-zh-v1.5`，512 维）
- **Agent 会话**：LangGraph 的「模型 ↔ 工具」循环，带服务端会话记忆，可运行时补知识、加工具
- **大模型**：DeepSeek（OpenAI 兼容接口，`deepseek-chat`）

## 目录结构

```
ch3ngtao-web/
├── frontend/            # React + antd 前端
│   ├── src/
│   │   ├── api/         # 后端接口封装
│   │   ├── components/  # 页面组件（Notion 列表 / 抽屉 / 右下角会话气泡）
│   │   └── App.tsx      # 演示页：向量相似度 + DeepSeek 对话
│   ├── Dockerfile       # 构建后由 nginx 托管
│   └── nginx.conf       # SPA 路由 + /api 反向代理（支持 SSE）
├── backend/             # FastAPI 后端
│   ├── app/
│   │   ├── api/routes/  # health / embeddings / chat / faq / agent 路由
│   │   ├── core/        # 配置
│   │   └── services/    # 向量模型 + DeepSeek 客户端 + RAG（rag.py）+ Agent
│   ├── pyproject.toml   # uv 管理依赖
│   └── Dockerfile
└── docker-compose.yml   # api + web 一键启动
```

## 环境要求

| 组件 | 版本 |
| --- | --- |
| Node.js | 22.x（仓库内已提供 `.nvmrc`） |
| Python | 3.12（由 uv 自动安装，无需手动准备） |
| uv | >= 0.5 |
| Docker + Compose | 可选，用于容器化运行 |

## 本地开发

### 一键启动（推荐）

```bash
./dev.sh
```

脚本会自动完成：检查 uv、切到 Node 22（缺失时自动安装）、按需安装前后端依赖、生成 `backend/.env`，
然后同时启动后端与前端，日志按 `[api]` / `[web]` 前缀区分颜色。**Ctrl+C 会同时关闭两个服务**，
任一服务异常退出时也会自动收尾另一个，不会残留进程占用端口。

```bash
./dev.sh --help        # 查看全部选项
./dev.sh --no-install  # 跳过依赖检查，直接启动
```

端口可通过环境变量覆盖：`BACKEND_PORT`、`FRONTEND_PORT`、`BACKEND_HOST`。

也可以按下面的方式分别手动启动。

### 1. 后端

```bash
cd backend
cp .env.example .env        # 填入 DEEPSEEK_API_KEY
uv sync                     # 创建 .venv 并安装依赖
uv run uvicorn app.main:app --reload --port 8000
```

接口文档：<http://localhost:8000/docs>

> 首次调用向量接口时会自动下载 `all-MiniLM-L6-v2`（约 90 MB，缓存在 `~/.cache/huggingface`）。
> 也可以在 `.env` 里设置 `PRELOAD_EMBEDDING_MODEL=true`，让服务启动时就加载模型。
>
> 首次调用 FAQ 接口时还会下载中文向量模型 `BAAI/bge-small-zh-v1.5`（约 95 MB），
> 并把切分结果缓存到 `backend/.cache/rag-index.json`。

### 2. 前端

```bash
nvm use                     # 读取 .nvmrc，切到 Node 22
cd frontend
cp .env.example .env        # 可选，默认走 vite 代理到 localhost:8000
npm install
npm run dev
```

打开 <http://localhost:5173>。

## 容器化运行

```bash
cp .env.example .env        # 填入 DEEPSEEK_API_KEY
docker compose up --build
```

- 前端：<http://localhost:5173>
- 后端：<http://localhost:8000/docs>

模型权重会下载到名为 `hf-cache` 的 Docker 卷中，RAG 索引缓存在 `rag-cache` 卷中，
容器重建不会重复下载 / 重建。简历 PDF 通过只读挂载进入容器（`RESUME_PDF_PATH=/app/resume.pdf`），
文件名或路径不同时改根目录 `.env` 即可。

## 部署到服务器

服务器只需要装 Docker（含 compose 插件），不需要 Node / Python / git。`deploy.sh` 会把本地
代码打包上传（自动跳过 `node_modules`、`.venv`、`.env` 等），再在服务器上构建镜像并启动容器。

```bash
cp deploy.conf.example deploy.conf   # 填 DEPLOY_SSH=user@host，其余按需改
./deploy.sh --init                   # 首次部署：建目录、生成 .env、构建、启动
```

日常更新和排查：

```bash
./deploy.sh                # 上传代码 + 重新构建 + 重启 + 健康检查
./deploy.sh --no-build     # 只上传代码并重启容器（依赖没变时更快）
./deploy.sh --restart      # 不上传代码，只重启（改了服务器上的 .env 时用）
./deploy.sh --status       # 看容器状态与健康检查
./deploy.sh --logs api     # 实时日志，可跟 api 或 web
```

几处约定：

- 服务器地址、端口、部署目录都写在 `deploy.conf`（已被 `.gitignore` 忽略，也不会被上传），
  也可以用 `--host` / `--dir` 临时覆盖，或用同名环境变量覆盖。
- `.env` 只在服务器上生成一次，之后本地不会再覆盖它；里面存着 `DEEPSEEK_API_KEY`。
- 源码、依赖、nginx 配置都打包进镜像，改动后必须走默认模式重新构建；`--no-build` 只用于
  「代码没变、只是换了被挂载的文件」的场景（比如更新了根目录的简历 PDF）。
- 记得在云厂商安全组和服务器防火墙上放行对外端口（默认 `5173`）。

### 首次构建很慢怎么办

首次构建要拉 uv 镜像、装 PyTorch 等依赖，动辄二十分钟以上，中途断线还会白跑。建议放到
服务器后台执行：

```bash
./deploy.sh --detach      # 上传后在服务器后台构建，SSH 断了也不影响
./deploy.sh --build-log   # 跟一下进度
```

两个已知的卡点：

- **ghcr.io 极慢**。uv 的镜像来自 `ghcr.io`，国内服务器实测 20MB 要 20 多分钟。在
  `deploy.conf` 里设 `DEPLOY_UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:latest`
  （或 `ghcr.nju.edu.cn/astral-sh/uv:latest`）走加速，改完必须重新构建才生效。
- **PyPI 换镜像源没用**。依赖的下载地址写在 `uv.lock` 里，`uv sync --frozen` 只认锁文件
  里的 URL，改索引地址不会改变下载来源，这部分只能等首次下载完（uv 缓存会保留已下载的包，
  中断后重跑能接着来）。
- **模型权重连不上 HuggingFace**。向量模型（简历 FAQ 的中文模型、向量演示的 MiniLM）都从
  `huggingface.co` 下载，国内服务器常见 `[Errno 101] Network is unreachable`，症状是问答
  接口一直挂着不返回。在 `deploy.conf` 里设 `DEPLOY_HF_ENDPOINT=https://hf-mirror.com`，
  然后跑一次 `./deploy.sh --init`（会把缺的配置补进服务器 `.env` 并重启，不会覆盖已有值）。
  模型下载一次后会存在 `hf-cache` 卷里，之后不再下载。

## 后端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，同时返回模型配置状态 |
| POST | `/api/embeddings` | 批量文本向量化（384 维） |
| POST | `/api/similarity` | 计算 source 与候选文本的余弦相似度并排序 |
| POST | `/api/chat` | 调用 DeepSeek 对话（一次性返回） |
| POST | `/api/chat/stream` | 调用 DeepSeek 对话（SSE 流式返回） |
| GET | `/api/faq/status` | 简历索引状态：PDF、页数、chunk 数、向量模型与维度 |
| POST | `/api/faq/index` | 构建简历索引（`?force=true` 忽略缓存重建） |
| GET | `/api/faq/chunks` | 查看切分后的 chunk（`?limit=N`） |
| POST | `/api/faq/search` | 只做检索，返回命中片段与相关度 |
| POST | `/api/faq/ask` | 简历 FAQ 问答（一次性返回答案 + 引用片段） |
| POST | `/api/faq/ask/stream` | 简历 FAQ 问答（SSE：先推 `mode` 与命中片段，再流式推答案） |
| GET | `/api/agent/info` | Agent 的模型、工具清单、知识库概况 |
| POST | `/api/agent/chat` | Agent 对话（一次性返回答案 + 工具步骤 + 引用） |
| POST | `/api/agent/chat/stream` | Agent 对话（SSE：工具调用事件 + 答案增量） |
| GET | `/api/agent/threads/{id}` | 查看某个会话的历史消息 |
| DELETE | `/api/agent/threads/{id}` | 清空某个会话的记忆 |
| POST | `/api/agent/knowledge` | 往补充知识库新增一篇资料 |
| GET | `/api/agent/knowledge` | 查看补充知识库 |
| POST | `/api/agent/knowledge/search` | 检索补充知识库 |
| DELETE | `/api/agent/knowledge/{id}` | 删除一篇补充知识 |

### 右下角会话气泡

首页右下角常驻一个会话气泡，点击后在页面内弹出会话窗口（消息列表 + 输入框），支持
快捷问题、流式输出、引用片段展开、复制回答、停止与重试。

打开窗口时会先请求一次 `/api/faq/status`：

- 简历索引就绪且配置了 `DEEPSEEK_API_KEY` → 走 `/api/faq/ask/stream`，基于简历片段回答并展示引用；
- 后端还没上 FAQ 接口或索引未就绪 → 自动退回 `/api/chat/stream`，用通用对话兜底。

FAQ 调用在返回首段文字前失败时也会自动降级，用户不会看到空白窗口。

示例：

```bash
curl -X POST http://localhost:8000/api/similarity \
  -H 'Content-Type: application/json' \
  -d '{"source":"如何配置 API KEY？","targets":["环境变量怎么设置","今天天气不错","token 计费规则"]}'
```

### 简历 FAQ（RAG）

`backend/app/services/rag.py` 是一条完整的 LangChain RAG 流水线：

1. **读取**：`pypdf` 逐页读取简历 PDF，每页包成 LangChain 的 `Document`，保留页码；
2. **切分**：先按简历章节（求职意向 / 相关技能 / 工作经历 / 项目经历 …）和日期条目
   （如「2022.10-至今 示例科技」）切成语义块，再用 `RecursiveCharacterTextSplitter`
   递归切到默认 320 字 / 重叠 60 字（`RAG_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`）；
   每个片段会带上所属章节（有时还有公司 / 项目）作为上下文，多条目章节还会额外生成一条
   只列「时间 + 公司 / 项目 + 职位」的索引片段；
3. **向量化**：`EmbeddingService` 通过 `LangChainEmbeddings` 适配成 LangChain 的 `Embeddings`，
   写入 `InMemoryVectorStore`；默认用中文模型 `BAAI/bge-small-zh-v1.5`（`RAG_EMBEDDING_MODEL`，
   留空则复用 `EMBEDDING_MODEL`）；
4. **检索**：向量相似度 + BM25 关键词得分加权融合（0.6 / 0.4），取 `RAG_TOP_K`（默认 5）个片段；
5. **生成**：把片段拼进 Prompt 交给 DeepSeek，只允许依据片段作答，简历里没有的直接说明。
   答案正文不带「片段 x · 第 x 页」这类标注，来源由接口的 `sources` 字段单独返回、界面单独展示。
   system prompt 里会带上今天的日期，这样「2022.10-至今」才能判断出是否仍然在职。

**问答路由**：检索之后、生成之前，会先用一次极短的模型判定（只输出 yes / no，`max_tokens=4`、
温度 0）确认「这些片段到底能不能回答这个问题」：

- 能 → 走 RAG，返回 `mode="faq"` + 引用片段；
- 不能（问日期、天气、写代码、闲聊，或片段只是碰巧撞词）→ 转普通对话，
  返回 `mode="chat"`、`sources=[]`，服务端会把当前日期时间（精确到分钟）注入 system prompt——
  大模型自己没有时钟，不注入就只能拒答或瞎猜。

这一步不能靠检索分数替代：融合后的 `score` 是每次在候选集里归一化的相对分，top-1 天然接近
1.0；`vector_score` 的相关/无关区间也大面积重叠（实测相关 0.39~0.61、无关 0.31~0.52）。
不想要这个行为时设 `FAQ_ROUTER_ENABLED=false` 即可退回原来的纯 RAG。

切分结果与向量会缓存到 `backend/.cache/rag-index.json`，PDF 内容或切分参数变化时自动失效重建。

```bash
# 看索引状态（不触发构建）
curl http://localhost:8000/api/faq/status

# 构建索引并查看切分结果
curl -X POST http://localhost:8000/api/faq/index
curl http://localhost:8000/api/faq/chunks?limit=3

# 只检索（不消耗大模型额度）
curl -X POST http://localhost:8000/api/faq/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"他的期望薪资是多少？","top_k":5}'

# 完整问答
curl -X POST http://localhost:8000/api/faq/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"他做过哪些 AI 相关的项目？"}'
```

### Agent 会话（带工具 + 记忆）

`/api/faq/*` 是**固定链路**：一定会检索一次简历再生成答案。`/api/agent/*` 是**完整 agent**：
把能力注册成工具，由模型自己决定查不查、查哪个、查几轮，会话记忆存在服务端。

| | `/api/faq/*` | `/api/agent/*` |
| --- | --- | --- |
| 控制流 | 代码写死的「检索 → 生成」 | 模型自主的「模型 ↔ 工具」循环 |
| 工具 | 无 | `search_resume` / `search_knowledge` / `get_current_time` |
| 多轮记忆 | 前端回传 `history` | 服务端 checkpointer，按 `thread_id` 保存 |
| 适用场景 | 单纯问简历，追求快和确定 | 需要多跳、跨知识源、多轮追问 |

```bash
# 看 agent 有哪些工具
curl http://localhost:8000/api/agent/info

# 对话（不传 thread_id 会自动新建并返回，后续轮次带上它即可续上上下文）
curl -X POST http://localhost:8000/api/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"他最近在哪家公司？现在还在职吗？"}'

# 流式：先返回 meta，再返回 tool_start / tool_end（agent 在调什么工具），最后是答案增量
curl -N -X POST http://localhost:8000/api/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"他做过性能优化吗？","thread_id":"<上一步返回的 id>"}'

# 运行中给 agent 补知识，立刻可被 search_knowledge 检索到
curl -X POST http://localhost:8000/api/agent/knowledge \
  -H 'Content-Type: application/json' \
  -d '{"title":"项目复盘","text":"语音助手重构后长会话帧率从 24fps 提升到 55fps。"}'
```

加新工具不用改 agent：在 `backend/app/services/tools.py` 的 `build_tools()` 里加一个
`@tool` 函数，函数名、docstring 和类型标注会自动变成模型看到的工具描述与参数 schema。

## 代码检查

```bash
cd backend && uv run ruff check .
cd frontend && npm run lint
```
