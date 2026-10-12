import { useCallback, useRef, useState } from 'react'
import { api, type ChatMessage, type RagSource } from '../../api/client'

export type ChatRole = 'user' | 'assistant'
/**
 * 回答来源：
 * - agent = 带工具的智能助手，自己决定要不要检索简历 / 查时间 / 查补充知识库；
 * - chat = agent 不可用时的兜底，纯 DeepSeek 对话。
 */
export type ChatMode = 'agent' | 'chat'
export type ChatStatus = 'unknown' | 'connecting' | ChatMode

export interface ChatTurn {
  id: string
  role: ChatRole
  content: string
  /** agent 调用检索工具时带回的片段，界面上单独展示引用。 */
  sources?: RagSource[]
  mode?: ChatMode
  /** 正在流式输出。 */
  streaming?: boolean
  /** 生成失败的原因，界面上给一个重试入口。 */
  error?: string
}

export interface ChatController {
  turns: ChatTurn[]
  status: ChatStatus
  sending: boolean
  send: (input: string) => void
  stop: () => void
  reset: () => void
  retry: (turnId: string) => void
  /** 探测一次后端：agent 就绪就走 agent，否则退回通用对话（浮层每次打开都会调）。 */
  refreshStatus: () => void
}

/** 空状态里的常见问题，点一下直接发送。 */
export const QUICK_QUESTIONS = [
  '介绍一下他的工作经历',
  '技术栈和擅长的方向？',
  '有哪些项目经验？',
  '他的求职意向是什么？',
  '怎么联系他？',
]

/** 送回后端的上下文轮数上限，避免多轮之后请求体越来越大。 */
const MAX_HISTORY_TURNS = 8

const SYSTEM_PROMPT: ChatMessage = {
  role: 'system',
  content:
    '你是「示例用户」个人主页上的简历助手，负责回答来访者关于这份简历的问题：工作经历、项目经验、技术栈、教育背景、求职意向等。'
    + '回答用简体中文，简洁分点；简历里没有的信息不要编造，直接说明不清楚并引导对方换个问法。',
}

function createId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 通用对话：带上历史消息，直接调 DeepSeek。 */
async function askChat(
  question: string,
  history: ChatMessage[],
  signal: AbortSignal,
  onDelta: (delta: string) => void,
): Promise<void> {
  const messages: ChatMessage[] = [...history, { role: 'user', content: question }]
  for await (const delta of api.chatStream([SYSTEM_PROMPT, ...messages], signal)) {
    onDelta(delta)
  }
}

/** 同一段内容可能被两个工具都命中，靠「章节 + 序号」判重。 */
function sourceKey(source: RagSource): string {
  return `${source.section ?? ''}#${source.index}`
}

/**
 * agent 会话：模型自己决定调不调工具。
 * 事件顺序是 meta（会话 id）→ tool_start / tool_end（引用片段）→ delta（答案增量）→ done（收尾）。
 */
async function askAgent(
  question: string,
  threadId: string | null,
  signal: AbortSignal,
  handlers: {
    onThread: (threadId: string) => void
    onSources: (sources: RagSource[]) => void
    onDelta: (delta: string) => void
  },
): Promise<void> {
  let streamed = false
  for await (const event of api.agentChatStream({ message: question, threadId }, signal)) {
    if (event.type === 'meta') {
      handlers.onThread(event.thread_id)
    } else if (event.type === 'tool_end') {
      if (event.sources.length) handlers.onSources(event.sources)
    } else if (event.type === 'delta') {
      streamed = true
      handlers.onDelta(event.content)
    } else if (event.type === 'done') {
      if (event.sources.length) handlers.onSources(event.sources)
      // 通常答案已经通过 delta 吐完了；没有增量时用收尾里的完整答案兜底。
      if (!streamed && event.answer) {
        streamed = true
        handlers.onDelta(event.answer)
      }
    }
  }
}

export default function useChat(): ChatController {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [status, setStatus] = useState<ChatStatus>('unknown')
  const [sending, setSending] = useState(false)

  // 流式回调里要拿到「最新」的会话，用 ref 同步一份，避免闭包读到旧数组。
  const turnsRef = useRef<ChatTurn[]>([])
  const statusRef = useRef<ChatStatus>('unknown')
  const sendingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  /** agent 的会话 id：记忆存在服务端，续聊只要把它带回去。 */
  const threadIdRef = useRef<string | null>(null)

  const commit = useCallback((updater: (prev: ChatTurn[]) => ChatTurn[]) => {
    const next = updater(turnsRef.current)
    turnsRef.current = next
    setTurns(next)
  }, [])

  const patchTurn = useCallback(
    (id: string, patch: Partial<ChatTurn> | ((turn: ChatTurn) => Partial<ChatTurn>)) => {
      commit((prev) =>
        prev.map((turn) =>
          turn.id === id ? { ...turn, ...(typeof patch === 'function' ? patch(turn) : patch) } : turn,
        ),
      )
    },
    [commit],
  )

  const refreshStatus = useCallback(() => {
    statusRef.current = 'connecting'
    setStatus('connecting')
    void api
      .agentInfo()
      .then((info) => {
        const next: ChatMode = info.configured ? 'agent' : 'chat'
        statusRef.current = next
        setStatus(next)
      })
      .catch(() => {
        // 后端还没上 agent 接口（404/未启动）时静默退回通用对话。
        statusRef.current = 'chat'
        setStatus('chat')
      })
  }, [])

  const send = useCallback(
    (input: string) => {
      const question = input.trim()
      if (!question || sendingRef.current) return

      const history: ChatMessage[] = turnsRef.current
        .filter((turn) => turn.content.trim() && !turn.error)
        .slice(-MAX_HISTORY_TURNS)
        .map((turn) => ({ role: turn.role, content: turn.content }))

      const assistantId = createId()
      commit((prev) => [
        ...prev,
        { id: createId(), role: 'user', content: question },
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ])

      sendingRef.current = true
      setSending(true)
      const controller = new AbortController()
      abortRef.current = controller

      let accumulated = ''
      const absorb = (delta: string) => {
        accumulated += delta
        patchTurn(assistantId, { content: accumulated })
      }
      const finish = (patch: Partial<ChatTurn>) => {
        patchTurn(assistantId, { streaming: false, content: accumulated, ...patch })
      }

      // agent 可能连着查几个工具，引用是分批回来的，这里攒起来并去重。
      let collected: RagSource[] = []
      const absorbSources = (incoming: RagSource[]) => {
        const seen = new Set(collected.map(sourceKey))
        const fresh = incoming.filter((item) => !seen.has(sourceKey(item)))
        if (!fresh.length) return
        collected = [...collected, ...fresh]
        patchTurn(assistantId, { sources: collected })
      }

      // 探测还没回来时也先按 agent 走：它是主链路，失败了再退回通用对话。
      let usedMode: ChatMode = statusRef.current === 'chat' ? 'chat' : 'agent'

      const run = async () => {
        try {
          if (statusRef.current !== 'chat') {
            try {
              await askAgent(question, threadIdRef.current, controller.signal, {
                onThread: (threadId) => {
                  threadIdRef.current = threadId
                },
                onSources: absorbSources,
                onDelta: absorb,
              })
              if (!accumulated) throw new Error('助手没有返回内容')
            } catch (agentError) {
              if (controller.signal.aborted) throw agentError
              // 已经吐字就不再重试，否则答案会出现两段拼接。
              if (accumulated) throw agentError
              // agent 没起来（未配 KEY / 服务未就绪）时退回通用对话，至少能答上话。
              statusRef.current = 'chat'
              setStatus('chat')
              usedMode = 'chat'
              await askChat(question, history, controller.signal, absorb)
            }
          } else {
            usedMode = 'chat'
            await askChat(question, history, controller.signal, absorb)
          }

          if (!accumulated) throw new Error('后端没有返回任何内容')
          finish({ mode: usedMode })
        } catch (error) {
          const reason = error instanceof Error ? error.message : String(error)
          if (controller.signal.aborted) {
            if (accumulated) finish({ content: `${accumulated}\n\n（已停止生成）` })
            else commit((prev) => prev.filter((turn) => turn.id !== assistantId))
            return
          }
          finish({ error: reason })
        } finally {
          sendingRef.current = false
          setSending(false)
          abortRef.current = null
        }
      }

      void run()
    },
    [commit, patchTurn],
  )

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    const threadId = threadIdRef.current
    threadIdRef.current = null
    // 服务端的会话记忆也要一起清掉，否则清空界面之后它还记着上一轮的上下文。
    if (threadId) void api.agentThreadReset(threadId).catch(() => undefined)
    commit(() => [])
  }, [commit])

  const retry = useCallback(
    (turnId: string) => {
      const list = turnsRef.current
      const target = list.findIndex((turn) => turn.id === turnId)
      if (target < 0) return

      let userIndex = -1
      for (let index = target - 1; index >= 0; index -= 1) {
        if (list[index].role === 'user') {
          userIndex = index
          break
        }
      }
      if (userIndex < 0) return

      const question = list[userIndex].content
      commit(() => list.slice(0, userIndex))
      send(question)
    },
    [commit, send],
  )

  return { turns, status, sending, send, stop, reset, retry, refreshStatus }
}
