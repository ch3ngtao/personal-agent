import { useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Flex,
  Layout,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { api, type HealthResponse } from './api/client'
import ChatDemo from './components/ChatDemo'
import EmbeddingDemo from './components/EmbeddingDemo'

const { Header, Content, Footer } = Layout
const { Title, Text } = Typography

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .health()
      .then((data) => {
        if (alive) setHealth(data)
      })
      .catch((err: Error) => {
        if (alive) setError(err.message)
      })
    return () => {
      alive = false
    }
  }, [])

  const status: 'success' | 'error' | 'processing' = error
    ? 'error'
    : health
      ? 'success'
      : 'processing'

  const statusText = error ? '后端未连接' : health ? '后端正常' : '检测中…'

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f6fa' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          paddingInline: 24,
          background: '#001529',
        }}
      >
        <Flex align="center" gap={16} wrap>
          <Title level={4} style={{ margin: 0, color: '#fff', whiteSpace: 'nowrap' }}>
            ch3ngtao-web
          </Title>
          <Space wrap>
            <Tag color="geekblue">React + Ant Design</Tag>
            <Tag color="green">FastAPI</Tag>
            <Tag color="purple">all-MiniLM-L6-v2</Tag>
            <Tag color="blue">DeepSeek</Tag>
          </Space>
        </Flex>
        <Badge status={status} text={<span style={{ color: '#fff' }}>{statusText}</span>} />
      </Header>

      <Content style={{ width: '100%', maxWidth: 1040, margin: '0 auto', padding: 24 }}>
        {error && (
          <Alert
            type="error"
            showIcon
            message="无法连接后端 API"
            description={`${error}。请确认已在 backend 目录执行 uv run uvicorn app.main:app --reload`}
            style={{ marginBottom: 16 }}
          />
        )}

        {health && !health.llm_configured && (
          <Alert
            type="warning"
            showIcon
            message="DeepSeek 尚未配置"
            description="请在 backend/.env 中设置 DEEPSEEK_API_KEY 后重启后端服务。向量接口不受影响。"
            style={{ marginBottom: 16 }}
          />
        )}

        <Tabs
          defaultActiveKey="embedding"
          items={[
            { key: 'embedding', label: '向量检索', children: <EmbeddingDemo /> },
            { key: 'chat', label: 'DeepSeek 对话', children: <ChatDemo /> },
          ]}
        />
      </Content>

      <Footer style={{ textAlign: 'center', background: 'transparent' }}>
        <Text type="secondary">
          React 18 · Ant Design 5 · FastAPI · uv · Docker · Python 3.12 · Node 22
        </Text>
      </Footer>
    </Layout>
  )
}
