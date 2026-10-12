const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api'

export interface HealthResponse {
  status: string
  app: string
  environment: string
  embedding_model: string
  llm_model: string
  llm_configured: boolean
}

export interface EmbeddingResponse {
  model: string
  dimension: number
  vectors: number[][]
}

export interface SimilarityMatch {
  index: number
  text: string
  score: number
}

export interface SimilarityResponse {
  model: string
  dimension: number
  matches: SimilarityMatch[]
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  model: string
  content: string
  usage: Record<string, unknown> | null
}

/** 简历 FAQ（RAG）召回的一个片段。 */
export interface RagSource {
  index: number
  content: string
  page: number | null
  /** 片段所属的简历章节；补充知识库的片段则是资料标题。 */
  section?: string | null
  score: number
  vector_score: number | null
}

/** GET /api/agent/info：agent 的模型、工具与会话记忆概况。 */
export interface AgentInfoResponse {
  model: string
  configured: boolean
  thread_backend: string
  max_steps: number
  tools: { name: string; description: string }[]
  knowledge_documents: number
  knowledge_chunks: number
}

/** agent 这一轮里的某次工具调用。 */
export interface AgentStep {
  name: string
  args: Record<string, unknown>
  summary: string | null
}

/**
 * agent 的流式事件：
 * meta（会话 id）→ tool_start / tool_end（在调什么工具、拿到哪些片段）→ delta（答案增量）→ done（收尾）。
 */
export type AgentStreamEvent =
  | { type: 'meta'; thread_id: string; model: string }
  | { type: 'tool_start'; name: string; args: Record<string, unknown> }
  | { type: 'tool_end'; name: string; sources: RagSource[]; query: string | null }
  | { type: 'delta'; content: string }
  | {
      type: 'done'
      thread_id: string
      answer: string
      steps: AgentStep[]
      sources: RagSource[]
      usage: Record<string, unknown> | null
    }
  | { type: 'error'; error: string }

/** GET /api/faq/status：索引与模型配置状态。 */
export interface FaqStatusResponse {
  ready: boolean
  building: boolean
  loaded_from_cache: boolean
  pdf_name: string | null
  pages: number
  chunks: number
  embedding_model: string
  embedding_dim: number
  vector_store: string
  hybrid_search: boolean
  built_at: string | null
  llm_model: string
  llm_configured: boolean
  error: string | null
}

/** 后端判定这次问答走哪条链路：faq = 依据简历回答，chat = 转普通对话。 */
export type RagAnswerMode = 'faq' | 'chat'

/** POST /api/faq/ask：带简历片段的问答结果。 */
export interface FaqAskResponse {
  model: string
  question: string
  answer: string
  mode: RagAnswerMode
  sources: RagSource[]
  usage: Record<string, unknown> | null
}

/** FAQ 流式事件：先给命中的简历片段，再逐段推送答案。 */
export type FaqStreamEvent =
  | { type: 'sources'; model: string | null; mode: RagAnswerMode; sources: RagSource[] }
  | { type: 'delta'; content: string }

interface SsePayload {
  content?: string
  error?: string
  model?: string
  mode?: RagAnswerMode
  sources?: RagSource[]
}

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown }
    if (typeof data.detail === 'string') return data.detail
    return JSON.stringify(data.detail ?? data)
  } catch {
    return `${response.status} ${response.statusText}`
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return (await response.json()) as T
}

/** 解析 SSE 响应，逐个产出 data: 后面的 JSON 负载。 */
async function* parseSse<T>(response: Response): AsyncGenerator<T, void, unknown> {
  if (!response.body) {
    throw new Error('响应没有携带内容流')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const event of events) {
      for (const line of event.split('\n')) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        if (!raw || raw === '[DONE]') continue

        try {
          yield JSON.parse(raw) as T
        } catch {
          continue
        }
      }
    }
  }
}

/** DeepSeek 对话（SSE 流式），逐段产出文本增量。 */
async function* chatStream(
  messages: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<string, void, unknown> {
  const response = await fetch(`${BASE_URL}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, stream: true }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(await readError(response))
  }

  for await (const payload of parseSse<SsePayload>(response)) {
    if (payload.error) throw new Error(payload.error)
    if (payload.content) yield payload.content
  }
}

/** 简历 FAQ 问答（SSE 流式）：先返回命中片段，再逐段返回答案。 */
async function* faqAskStream(
  payload: { question: string; history: ChatMessage[]; topK?: number },
  signal?: AbortSignal,
): AsyncGenerator<FaqStreamEvent, void, unknown> {
  const response = await fetch(`${BASE_URL}/faq/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: payload.question,
      history: payload.history,
      top_k: payload.topK ?? 5,
    }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(await readError(response))
  }

  for await (const event of parseSse<SsePayload>(response)) {
    if (event.error) throw new Error(event.error)
    if (event.sources) {
      yield {
        type: 'sources',
        model: event.model ?? null,
        mode: event.mode ?? 'faq',
        sources: event.sources,
      }
    }
    if (event.content) {
      yield { type: 'delta', content: event.content }
    }
  }
}

/**
 * agent 会话（SSE 流式）：模型自己决定要不要调工具、调哪个、几轮。
 * 传 thread_id 续上上一轮的会话记忆（记忆存在服务端，不需要回传 history）。
 */
async function* agentChatStream(
  payload: { message: string; threadId?: string | null },
  signal?: AbortSignal,
): AsyncGenerator<AgentStreamEvent, void, unknown> {
  const response = await fetch(`${BASE_URL}/agent/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: payload.message, thread_id: payload.threadId ?? null }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(await readError(response))
  }

  for await (const event of parseSse<AgentStreamEvent>(response)) {
    if (event.type === 'error') throw new Error(event.error)
    yield event
  }
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  agentInfo: () => request<AgentInfoResponse>('/agent/info'),

  agentChatStream,

  agentThreadReset: (threadId: string) =>
    request<{ thread_id: string; messages: ChatMessage[] }>(`/agent/threads/${threadId}`, {
      method: 'DELETE',
    }),

  embed: (texts: string[]) =>
    request<EmbeddingResponse>('/embeddings', {
      method: 'POST',
      body: JSON.stringify({ texts }),
    }),

  similarity: (source: string, targets: string[]) =>
    request<SimilarityResponse>('/similarity', {
      method: 'POST',
      body: JSON.stringify({ source, targets }),
    }),

  chat: (messages: ChatMessage[]) =>
    request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, stream: false }),
    }),

  chatStream,

  faqStatus: () => request<FaqStatusResponse>('/faq/status'),

  faqAsk: (question: string, history: ChatMessage[], topK = 5) =>
    request<FaqAskResponse>('/faq/ask', {
      method: 'POST',
      body: JSON.stringify({ question, history, top_k: topK }),
    }),

  faqAskStream,
}
