import { useState } from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  Empty,
  Flex,
  Input,
  List,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { api, type SimilarityMatch } from '../api/client'

const { Text, Paragraph } = Typography

const DEFAULT_SOURCE = '如何配置 DeepSeek 的 API KEY？'
const DEFAULT_TARGETS = [
  '环境变量怎么设置',
  'token 是怎么计费的',
  '今天上海的天气怎么样',
].join('\n')

export default function EmbeddingDemo() {
  const { message } = AntdApp.useApp()
  const [source, setSource] = useState(DEFAULT_SOURCE)
  const [targetsText, setTargetsText] = useState(DEFAULT_TARGETS)
  const [matches, setMatches] = useState<SimilarityMatch[]>([])
  const [model, setModel] = useState<string>('')
  const [loading, setLoading] = useState(false)

  const handleRun = async () => {
    const trimmedSource = source.trim()
    const targets = targetsText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)

    if (!trimmedSource || targets.length === 0) {
      message.warning('请填写查询文本和至少一条候选文本')
      return
    }

    setLoading(true)
    try {
      const result = await api.similarity(trimmedSource, targets)
      setMatches(result.matches)
      setModel(result.model)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card
      title={
        <Space>
          <span>向量相似度</span>
          <Tag color="purple">all-MiniLM-L6-v2</Tag>
          <Tag>384 维 · 本地推理</Tag>
        </Space>
      }
    >
      <Flex vertical gap={16}>
        <div>
          <Text strong>查询文本</Text>
          <Input.TextArea
            value={source}
            onChange={(event) => setSource(event.target.value)}
            autoSize={{ minRows: 2, maxRows: 4 }}
            placeholder="输入一句话"
            style={{ marginTop: 8 }}
          />
        </div>

        <div>
          <Text strong>候选文本（每行一条）</Text>
          <Input.TextArea
            value={targetsText}
            onChange={(event) => setTargetsText(event.target.value)}
            autoSize={{ minRows: 3, maxRows: 6 }}
            placeholder={'第一句\n第二句'}
            style={{ marginTop: 8 }}
          />
        </div>

        <Space>
          <Button type="primary" onClick={handleRun} loading={loading}>
            计算相似度
          </Button>
          <Button
            onClick={() => {
              setSource('')
              setTargetsText('')
              setMatches([])
            }}
            disabled={loading}
          >
            清空
          </Button>
        </Space>

        {loading && (
          <Flex align="center" gap={8}>
            <Spin size="small" />
            <Text type="secondary">首次运行需要加载向量模型，请稍候…</Text>
          </Flex>
        )}

        {!loading && matches.length === 0 && (
          <Empty description="还没有结果，点击「计算相似度」试试" />
        )}

        {matches.length > 0 && (
          <List
            header={<Text type="secondary">{model} · 按余弦相似度排序</Text>}
            bordered
            dataSource={matches}
            renderItem={(item, index) => (
              <List.Item>
                <Flex vertical gap={6} style={{ width: '100%' }}>
                  <Flex justify="space-between" align="center" gap={12}>
                    <Space>
                      <Tag color={index === 0 ? 'green' : 'default'}>#{index + 1}</Tag>
                      <Paragraph style={{ margin: 0 }}>{item.text}</Paragraph>
                    </Space>
                    <Text strong>{item.score.toFixed(4)}</Text>
                  </Flex>
                  <Progress
                    percent={Math.max(0, Math.min(100, Math.round(item.score * 100)))}
                    showInfo={false}
                    strokeColor={index === 0 ? '#52c41a' : '#1677ff'}
                    size="small"
                  />
                </Flex>
              </List.Item>
            )}
          />
        )}
      </Flex>
    </Card>
  )
}
