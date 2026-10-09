import { useEffect, useRef, useState } from 'react'
import { ClearOutlined, CloseOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'
import { Button, Input, Tooltip } from 'antd'
import MessageBubble from './MessageBubble'
import { QUICK_QUESTIONS, type ChatController, type ChatStatus } from './useChat'

interface ChatPanelProps {
  chat: ChatController
  open: boolean
  onClose: () => void
}

const STATUS_TEXT: Record<ChatStatus, string> = {
  unknown: '点击气泡开始对话',
  connecting: '正在连接简历知识库…',
  faq: '已连接简历知识库',
  chat: '通用对话模式',
}

const STATUS_HINT: Record<ChatStatus, string> = {
  unknown: '打开后开始和助手对话',
  connecting: '正在确认简历索引状态',
  faq: '回答前会先检索简历片段，再交给 DeepSeek 组织语言',
  chat: '简历知识库暂未就绪，先直接由 DeepSeek 回答',
}

function statusTone(status: ChatStatus): string {
  if (status === 'faq') return 'is-ok'
  if (status === 'connecting' || status === 'chat') return 'is-warn'
  return 'is-idle'
}

/** 页面内的会话窗口：消息列表 + 输入区，浮在气泡上方。 */
export default function ChatPanel({ chat, open, onClose }: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const inputWrapRef = useRef<HTMLDivElement>(null)

  // 有新消息（含流式增量）时始终停在底部。
  useEffect(() => {
    const node = listRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [chat.turns])

  useEffect(() => {
    if (open) inputWrapRef.current?.querySelector('textarea')?.focus()
  }, [open])

  const submit = () => {
    const text = draft.trim()
    if (!text || chat.sending) return
    setDraft('')
    chat.send(text)
  }

  return (
    <aside
      className={`chat-panel${open ? ' is-open' : ''}`}
      role="dialog"
      aria-label="简历助手对话窗口"
      aria-hidden={!open}
    >
      <header className="chat-panel-header">
        <div className="chat-identity">
          <span className="chat-avatar" aria-hidden>
            🤖
          </span>
          <div className="chat-identity-text">
            <div className="chat-title">简历助手</div>
            <div className="chat-status" title={STATUS_HINT[chat.status]}>
              <span className={`chat-status-dot ${statusTone(chat.status)}`} />
              {STATUS_TEXT[chat.status]}
            </div>
          </div>
        </div>

        <div className="chat-panel-actions">
          <Tooltip title="清空对话">
            <Button
              type="text"
              size="small"
              aria-label="清空对话"
              icon={<ClearOutlined />}
              disabled={chat.turns.length === 0 && !chat.sending}
              onClick={chat.reset}
            />
          </Tooltip>
          <Tooltip title="收起">
            <Button
              type="text"
              size="small"
              aria-label="收起对话窗口"
              icon={<CloseOutlined />}
              onClick={onClose}
            />
          </Tooltip>
        </div>
      </header>

      <div className="chat-body" ref={listRef}>
        {chat.turns.length === 0 ? (
          <div className="chat-welcome">
            <div className="chat-welcome-title">你好，我是示例用户的简历助手 👋</div>
            <p className="chat-welcome-text">
              可以问我他的工作经历、项目经验、技术栈和求职意向，也可以随便聊聊。试试下面的问题：
            </p>
            <div className="chat-chips">
              {QUICK_QUESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  className="chat-chip"
                  onClick={() => chat.send(question)}
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        ) : (
          chat.turns.map((turn) => (
            <MessageBubble key={turn.id} turn={turn} onRetry={chat.retry} />
          ))
        )}
      </div>

      <footer className="chat-composer">
        <div ref={inputWrapRef}>
          <Input.TextArea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder="输入问题，Enter 发送"
            autoSize={{ minRows: 1, maxRows: 4 }}
            maxLength={500}
          />
        </div>

        <div className="chat-composer-actions">
          <span className="chat-tip">Enter 发送 · Shift + Enter 换行</span>
          {chat.sending ? (
            <Button size="small" icon={<StopOutlined />} onClick={chat.stop}>
              停止
            </Button>
          ) : (
            <Button
              type="primary"
              size="small"
              icon={<SendOutlined />}
              disabled={!draft.trim()}
              onClick={submit}
            >
              发送
            </Button>
          )}
        </div>
      </footer>
    </aside>
  )
}
