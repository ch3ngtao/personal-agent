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

/** 解析 SSE 流，逐段产出文本增量。 */
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

        let payload: { content?: string; error?: string }
        try {
          payload = JSON.parse(raw) as { content?: string; error?: string }
        } catch {
          continue
        }

        if (payload.error) throw new Error(payload.error)
        if (payload.content) yield payload.content
      }
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
}
