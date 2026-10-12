import { useEffect, useState } from 'react'
import { CloseOutlined, MessageOutlined } from '@ant-design/icons'
import ChatPanel from './ChatPanel'
import useChat from './useChat'

/**
 * 右侧悬浮的会话气泡：点击后在页面内弹出对话窗口。
 * 对话走 /api/agent（带工具的智能助手），agent 不可用时自动退回 /api/chat。
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
    // 每次打开都确认一次：第一次可能后端还没起好，之后就绪了能自动切回 agent。
    if (chat.status !== 'agent') chat.refreshStatus()
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
