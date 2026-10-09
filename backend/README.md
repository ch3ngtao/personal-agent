# ch3ngtao-web backend

FastAPI 服务，提供两组能力：

- **向量**：`all-MiniLM-L6-v2`（sentence-transformers）本地推理，输出 384 维向量 / 余弦相似度。
- **大模型**：DeepSeek（OpenAI 兼容接口），支持一次性与 SSE 流式返回。

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
