import { useEffect, useRef, useState } from 'react'
import { CheckOutlined, CopyOutlined, FileTextOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import Markdown from './Markdown'
import type { ChatTurn } from './useChat'

interface MessageBubbleProps {
  turn: ChatTurn
  onRetry?: (turnId: string) => void
}

function scoreLabel(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`
}

export default function MessageBubble({ turn, onRetry }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const timerRef = useRef<number | null>(null)
  const sourcesRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  // 展开引用后把新出现的片段滚进可视区，否则内容会顶到输入框下面。
  useEffect(() => {
    if (sourcesOpen) sourcesRef.current?.scrollIntoView({ block: 'nearest' })
  }, [sourcesOpen])

  const handleCopy = () => {
    if (!navigator.clipboard) return
    void navigator.clipboard
      .writeText(turn.content)
      .then(() => {
        setCopied(true)
        timerRef.current = window.setTimeout(() => setCopied(false), 1600)
      })
      .catch(() => {
        /* 剪贴板不可用时静默忽略，不影响阅读 */
      })
  }

  const isUser = turn.role === 'user'
  const sources = turn.sources ?? []
  const showTyping = Boolean(turn.streaming) && !turn.content

  if (isUser) {
    return (
      <div className="chat-msg is-user">
        <div className="chat-bubble-user">{turn.content}</div>
      </div>
    )
  }

  return (
    <div className="chat-msg is-assistant">
      <span className="chat-msg-avatar" aria-hidden>
        🤖
      </span>

      <div className="chat-msg-main">
        <div className={`chat-bubble-assistant${turn.error ? ' is-error' : ''}`}>
          {showTyping && (
            <span className="chat-typing" aria-label="正在回答">
              <i />
              <i />
              <i />
            </span>
          )}

          {turn.content && <Markdown content={turn.content} />}
          {turn.streaming && turn.content && <span className="chat-cursor" aria-hidden />}

          {turn.error && (
            <div className="chat-error">
              <span>回答失败：{turn.error}</span>
              {onRetry && (
                <Button size="small" icon={<ReloadOutlined />} onClick={() => onRetry(turn.id)}>
                  重试
                </Button>
              )}
            </div>
          )}
        </div>

        {sources.length > 0 && (
          <div className="chat-sources">
            <button
              type="button"
              className="chat-sources-toggle"
              onClick={() => setSourcesOpen((prev) => !prev)}
              aria-expanded={sourcesOpen}
            >
              <FileTextOutlined />
              引用了 {sources.length} 段简历内容
              <span className="chat-sources-caret">{sourcesOpen ? '收起' : '展开'}</span>
            </button>

            {sourcesOpen && (
              <div className="chat-sources-list" ref={sourcesRef}>
                {sources.map((source, position) => (
                  <article key={source.index} className="chat-source">
                    <header className="chat-source-head">
                      {/* 序号与答案里「片段 N」的引用保持一致，所以按召回顺序编号 */}
                      <span>片段 {position + 1}</span>
                      <span>
                        {source.page ? `第 ${source.page} 页 · ` : ''}
                        相关度 {scoreLabel(source.score)}
                      </span>
                    </header>
                    <p className="chat-source-text">{source.content}</p>
                  </article>
                ))}
              </div>
            )}
          </div>
        )}

        {turn.content && !turn.streaming && !turn.error && (
          <div className="chat-msg-tools">
            <Tooltip title={copied ? '已复制' : '复制'}>
              <button type="button" className="chat-msg-tool" onClick={handleCopy} aria-label="复制这条回答">
                {copied ? <CheckOutlined /> : <CopyOutlined />}
              </button>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  )
}
