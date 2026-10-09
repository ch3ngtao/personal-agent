import { useRef, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Flex,
  Input,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { api, type ChatMessage } from '../api/client'

const { Text } = Typography

const GREETING = '你好，我是 DeepSeek 助手。问点什么吧。'

const SYSTEM_PROMPT: ChatMessage = {
  role: 'system',
  content: '你是一个中文技术助手，回答简洁、准确，代码示例用 Markdown。',
}

export default function ChatDemo() {
  const { message } = AntdApp.useApp()
  const [turns, setTurns] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'流式' | '一次性'>('流式')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return

    setError(null)
    const history: ChatMessage[] = [...turns, { role: 'user', content: text }]
    setTurns(history)
    setInput('')
    setLoading(true)

    const payload: ChatMessage[] = [SYSTEM_PROMPT, ...history]

    try {
      if (mode === '流式') {
        setTurns([...history, { role: 'assistant', content: '' }])
        const controller = new AbortController()
        abortRef.current = controller

        let accumulated = ''
        for await (const delta of api.chatStream(payload, controller.signal)) {
          accumulated += delta
          setTurns([...history, { role: 'assistant', content: accumulated }])
        }

        if (!accumulated) {
          throw new Error('后端没有返回任何内容')
        }
      } else {
        const response = await api.chat(payload)
        setTurns([...history, { role: 'assistant', content: response.content }])
      }
    } catch (err) {
      const reason = (err as Error).message
      setError(reason)
      if (abortRef.current?.signal.aborted) {
        message.info('已停止生成')
      } else {
        setTurns(history)
      }
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }

  const bubbles: ChatMessage[] = [{ role: 'assistant', content: GREETING }, ...turns]

  return (
    <Card
      title={
        <Space>
          <span>DeepSeek 对话</span>
          <Tag color="blue">deepseek-chat</Tag>
        </Space>
      }
      extra={
        <Segmented
          size="small"
          value={mode}
          onChange={(value) => setMode(value as '流式' | '一次性')}
          options={['流式', '一次性']}
        />
      }
    >
      <Flex vertical gap={16}>
        {error && (
          <Alert
            type="error"
            showIcon
            message="调用失败"
            description={error}
            closable
            onClose={() => setError(null)}
          />
        )}

        <Flex
          vertical
          gap={12}
          style={{
            maxHeight: 420,
            overflowY: 'auto',
            padding: 12,
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
          }}
        >
          {bubbles.map((item, index) => {
            const isUser = item.role === 'user'
            return (
              <Flex key={index} justify={isUser ? 'flex-end' : 'flex-start'}>
                <div
                  style={{
                    maxWidth: '78%',
                    padding: '8px 12px',
                    borderRadius: 10,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    background: isUser ? '#1677ff' : '#ffffff',
                    color: isUser ? '#ffffff' : '#1f1f1f',
                    border: isUser ? 'none' : '1px solid #eceff5',
                  }}
                >
                  {item.content || (loading ? '…' : '')}
                </div>
              </Flex>
            )
          })}
          {loading && mode === '一次性' && (
            <Flex align="center" gap={8}>
              <Spin size="small" />
              <Text type="secondary">DeepSeek 正在思考…</Text>
            </Flex>
          )}
        </Flex>

        <Input.TextArea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault()
              void handleSend()
            }
          }}
          placeholder="输入问题，Enter 发送，Shift + Enter 换行"
          autoSize={{ minRows: 2, maxRows: 5 }}
          disabled={loading}
        />

        <Space>
          <Button type="primary" onClick={handleSend} loading={loading}>
            发送
          </Button>
          <Button
            onClick={() => abortRef.current?.abort()}
            disabled={!loading || mode !== '流式'}
          >
            停止
          </Button>
          <Button
            onClick={() => {
              setTurns([])
              setError(null)
            }}
            disabled={loading}
          >
            重置会话
          </Button>
        </Space>
      </Flex>
    </Card>
  )
}
