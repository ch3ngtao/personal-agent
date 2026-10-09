# ch3ngtao-web

一个前后端分离的项目骨架：

- **前端**：React 18 + TypeScript + Vite + Ant Design 5（Node.js 22.x）
- **后端**：Python 3.12 + FastAPI + uv + Docker
- **向量模型**：`all-MiniLM-L6-v2`（sentence-transformers，384 维，本地推理）
- **大模型**：DeepSeek（OpenAI 兼容接口，`deepseek-chat`）

## 目录结构

```
ch3ngtao-web/
├── frontend/            # React + antd 前端
│   ├── src/
│   │   ├── api/         # 后端接口封装
│   │   └── App.tsx      # 演示页：向量相似度 + DeepSeek 对话
│   ├── Dockerfile       # 构建后由 nginx 托管
│   └── nginx.conf       # SPA 路由 + /api 反向代理（支持 SSE）
├── backend/             # FastAPI 后端
│   ├── app/
│   │   ├── api/routes/  # health / embeddings / chat 路由
│   │   ├── core/        # 配置
│   │   └── services/    # 向量模型 + DeepSeek 客户端
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

模型权重会下载到名为 `hf-cache` 的 Docker 卷中，容器重建不会重复下载。

## 后端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，同时返回模型配置状态 |
| POST | `/api/embeddings` | 批量文本向量化（384 维） |
| POST | `/api/similarity` | 计算 source 与候选文本的余弦相似度并排序 |
| POST | `/api/chat` | 调用 DeepSeek 对话（一次性返回） |
| POST | `/api/chat/stream` | 调用 DeepSeek 对话（SSE 流式返回） |

示例：

```bash
curl -X POST http://localhost:8000/api/similarity \
  -H 'Content-Type: application/json' \
  -d '{"source":"如何配置 API KEY？","targets":["环境变量怎么设置","今天天气不错","token 计费规则"]}'
```

## 代码检查

```bash
cd backend && uv run ruff check .
cd frontend && npm run lint
```
