import { useEffect, useState } from 'react'
import { CloseOutlined, MessageOutlined } from '@ant-design/icons'
import ChatPanel from './ChatPanel'
import useChat from './useChat'

/**
 * 右侧悬浮的会话气泡：点击后在页面内弹出对话窗口。
 * 对话走 /api/faq（简历知识库），知识库不可用时自动退回 /api/chat。
 */
export default function ChatWidget() {
  const chat = useChat()
  const [open, setOpen] = useState(false)
  const [hintDismissed, setHintDismissed] = useState(false)

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open])

  const openPanel = () => {
    setHintDismissed(true)
    setOpen(true)
    // 每次打开都确认一次索引状态：第一次可能还没构建好，后面就绪了能自动切回知识库。
    if (chat.status !== 'faq') chat.refreshStatus()
  }

  const toggle = () => {
    if (open) setOpen(false)
    else openPanel()
  }

  return (
    <div className="chat-widget">
      <ChatPanel chat={chat} open={open} onClose={() => setOpen(false)} />

      {!open && !hintDismissed && (
        <div className="chat-hint">
          <button type="button" className="chat-hint-text" onClick={openPanel}>
            有想问的？聊聊这份简历
          </button>
          <button
            type="button"
            className="chat-hint-close"
            aria-label="不再提示"
            onClick={() => setHintDismissed(true)}
          >
            <CloseOutlined />
          </button>
        </div>
      )}

      <button
        type="button"
        className={`chat-bubble${open ? ' is-open' : ''}`}
        aria-label={open ? '关闭对话窗口' : '打开对话窗口'}
        aria-expanded={open}
        onClick={toggle}
      >
        {open ? <CloseOutlined /> : <MessageOutlined />}
      </button>
    </div>
  )
}
