import { Drawer, Tabs } from 'antd'
import ChatDemo from './ChatDemo'
import EmbeddingDemo from './EmbeddingDemo'

interface ApiDemoDrawerProps {
  open: boolean
  onClose: () => void
}

/** 后端能力演示入口，收在抽屉里，不干扰简历主页。 */
export default function ApiDemoDrawer({ open, onClose }: ApiDemoDrawerProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      width={760}
      title="后端能力演示"
      styles={{ body: { paddingTop: 8 } }}
    >
      <Tabs
        defaultActiveKey="chat"
        items={[
          { key: 'chat', label: 'DeepSeek 对话', children: <ChatDemo /> },
          { key: 'embedding', label: '向量检索', children: <EmbeddingDemo /> },
        ]}
      />
    </Drawer>
  )
}
