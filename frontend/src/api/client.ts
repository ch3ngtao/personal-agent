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
  score: number
  vector_score: number | null
}

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

export const api = {
  health: () => request<HealthResponse>('/health'),

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
