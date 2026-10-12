import { useCallback, useRef, useState } from 'react'
import { api, type ChatMessage, type RagSource } from '../../api/client'
import { profile } from '../../data/resume'

export type ChatRole = 'user' | 'assistant'
/** 回答来源：faq = 简历知识库（RAG），chat = 纯 DeepSeek 对话。 */
export type ChatMode = 'faq' | 'chat'
export type ChatStatus = 'unknown' | 'connecting' | ChatMode

export interface ChatTurn {
  id: string
  role: ChatRole
  content: string
  /** 知识库命中的简历片段（仅 FAQ 通道有）。 */
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
  /** 探测一次后端：知识库可用就走 RAG，否则退回通用对话（浮层每次打开都会调）。 */
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
const TOP_K = 5

const SYSTEM_PROMPT: ChatMessage = {
  role: 'system',
  content:
    `你是「${profile.name}」个人主页上的简历助手，负责回答来访者关于这份简历的问题：工作经历、项目经验、技术栈、教育背景、求职意向等。`
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

/** 简历 FAQ：后端先返回命中的片段，再流式返回答案。 */
async function askFaq(
  question: string,
  history: ChatMessage[],
  signal: AbortSignal,
  onDelta: (delta: string) => void,
  onSources: (sources: RagSource[], mode: ChatMode) => void,
): Promise<void> {
  for await (const event of api.faqAskStream({ question, history, topK: TOP_K }, signal)) {
    if (event.type === 'sources') onSources(event.sources, event.mode)
    else onDelta(event.content)
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
      .faqStatus()
      .then((info) => {
        const next: ChatMode = info.ready && info.llm_configured ? 'faq' : 'chat'
        statusRef.current = next
        setStatus(next)
      })
      .catch(() => {
        // 后端还没上 FAQ 接口（404/未启动）时静默退回通用对话。
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

      const run = async () => {
        try {
          if (statusRef.current === 'faq') {
            try {
              await askFaq(question, history, controller.signal, absorb, (sources, mode) => {
                // 后端会判定这次能不能用简历回答：chat 表示已转普通对话，不展示引用。
                patchTurn(assistantId, { sources, mode })
              })
              if (!accumulated) throw new Error('简历知识库没有返回内容')
            } catch (faqError) {
              if (controller.signal.aborted) throw faqError
              // 已经吐字就不再重试，否则答案会出现两段拼接。
              if (accumulated) throw faqError
              // 索引没就绪 / 没配 KEY 时退回通用对话，至少能答上话。
              statusRef.current = 'chat'
              setStatus('chat')
              await askChat(question, history, controller.signal, absorb)
              patchTurn(assistantId, { mode: 'chat' })
            }
          } else {
            await askChat(question, history, controller.signal, absorb)
          }

          if (!accumulated) throw new Error('后端没有返回任何内容')
          finish({})
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
