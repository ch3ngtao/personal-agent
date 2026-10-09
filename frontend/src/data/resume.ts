/**
 * 简历数据源：内容来自「简历-AI前端-示例用户.pdf」。
 * 页面结构与视觉参考 Notion「个人职业空间」模板。
 */

export interface Bullet {
  /** 小标题，例如「AI 产品前端（主导）」 */
  label?: string
  text: string
}

export interface DetailSection {
  heading: string
  bullets: Bullet[]
}

/** 抽屉里展示的详情内容 */
export interface DetailView {
  icon: string
  title: string
  subtitle?: string
  metaRows?: { label: string; value: string }[]
  tags?: string[]
  description?: string
  sections?: DetailSection[]
}

export const profile = {
  name: '示例用户',
  title: '个人职业空间',
  icon: '💻',
  summary:
    '8 年前端开发经验，近 3 年担任前端副组长，接触 AI 有 3 年，2 年 vibe coding 使用经验，主导示例科技语音助手、文本助手等对话式 AI 产品的前端开发与重构，并参与 Dify 工作流配置、LiteLLM 多模型接入与数字人 TTS 语音生成的功能落地。Vue / React 双栈，熟悉 TypeScript 与前端工程化，具备 0 到 1 项目搭建、性能优化及 H5 / 小程序 / App 混合开发能力，曾负责中国电信 10000 号新门户等大型 To B 系统的 Web 端建设。',
  gender: '男',
  age: 31,
  phone: '00000000000',
  email: 'noreply@example.com',
  intention: {
    position: 'AI 应用前端开发 / 前端开发（AI 方向）',
    city: '成都',
    salary: '面议',
    type: '社招',
  },
}

export interface SkillGroup {
  id: string
  category: string
  items: string[]
}

export const skills: SkillGroup[] = [
  {
    id: 'ai-app',
    category: 'AI 应用开发',
    items: [
      '语音助手 / 文本助手等对话式产品前端重构',
      'SSE / WebSocket 流式渲染、多轮会话与消息列表性能优化',
      'TTS 语音合成播放与字幕同步',
    ],
  },
  {
    id: 'llm',
    category: '大模型工程',
    items: [
      'Dify 应用与工作流配置、LiteLLM 多模型接入、Prompt 工程',
      '了解 LangChain、LangGraph 智能体开发',
    ],
  },
  {
    id: 'frontend',
    category: '前端核心',
    items: [
      'JavaScript（ES6+）/ TypeScript / HTML5 / CSS3',
      '熟练 Vue2、Vue3（Composition API）与 React（Hooks），了解 UmiJS',
      'Element、Ant Design、Vant',
    ],
  },
  {
    id: 'engineering',
    category: '工程化与性能',
    items: [
      'Webpack 构建优化、首屏与渲染性能优化',
      '微前端方案（qiankun）选型评估',
      'Git Flow 工作流、Code Review 与前端开发规范建设',
    ],
  },
  {
    id: 'visual',
    category: '可视化与跨端',
    items: [
      'ECharts / AntV 图表与数据大屏、可视化报表、xlsx.js 导出',
      '小程序、uni-app、Nuxt SSR、H5 与原生 App 混合开发（JSBridge）',
    ],
  },
  {
    id: 'backend',
    category: '服务端与部署',
    items: ['Node.js（Koa / Express）、Nginx 项目部署', 'Linux 常用命令、Git / SVN 版本管理'],
  },
]

export interface WorkExperience {
  id: string
  period: string
  company: string
  role: string
  direction: string
  stack: string[]
  highlights: Bullet[]
}

export const workExperiences: WorkExperience[] = [
  {
    id: 'huayun',
    period: '2022.10 - 至今',
    company: '示例科技',
    role: '前端工程师',
    direction: '语音助手、文本助手、智能客服、呼叫中心、可视化报表',
    stack: ['Vue3', 'Vue2', 'React', 'TypeScript', 'Ant Design', 'Less', 'Axios', 'SSE', 'WebSocket', 'Dify', 'LiteLLM'],
    highlights: [
      {
        label: 'AI 产品前端（主导）',
        text: '主导示例科技语音助手、文本助手的前端开发与重构，负责对话会话链路、消息流式渲染与多轮交互体验。',
      },
      {
        label: '大模型与数字人协作',
        text: '参与算法部门的 Dify 应用与工作流配置、LiteLLM 多模型接入配置，通过每次调用的模型绑定模型计费；使用 Python 对接数字人 TTS 语音合成功能。',
      },
      {
        label: '核心门户交付',
        text: '负责电信 10000 号新门户系统开发，独立完成鉴权系统、数据脱敏体系等核心模块，保障需求如期交付并在线上稳定运行。',
      },
      {
        label: '架构与规范',
        text: '主导公司内部系统首页与多产品统一门户重构，负责项目整体搭建、目录结构与代码风格统一，提出基于 qiankun 的多项目统一管理方案并完成选型评估。',
      },
      {
        label: '研发提效与性能',
        text: '抽离通用业务组件与插件，同类需求开发代码量减少 80%，打包体积由 50MB 降至 22MB，首屏加载时间降低 3s 左右。',
      },
      {
        label: '团队与质量',
        text: '作为前端副组长主导二开项目前端部分，梳理遗留代码逻辑并组织组内技术分享；负责业务代码 Code Review 与 Git Flow 规范落地。',
      },
    ],
  },
  {
    id: 'guangkesuo',
    period: '2020.03 - 2022.10',
    company: '示例数据所',
    role: '前端工程师',
    direction: '电子商务（Bazirim 商城）',
    stack: ['Vue2', 'React', 'TypeScript', 'Ant Design', 'ECharts', 'uni-app', 'Nuxt.js', 'Sass', 'Less', '小程序'],
    highlights: [
      {
        label: '多端交付',
        text: '负责电商 H5 商城与微信小程序开发，完成 H5 与原生 App 的混合开发对接，搭建完整的电商购物平台。',
      },
      {
        label: '后台重构与可视化',
        text: '基于 UmiJS + Ant Design 完成管理后台重构；使用 React + ECharts 搭建电商数据报表，支撑运营侧数据分析。',
      },
      {
        label: '政务项目与技术演进',
        text: '主导公司政务项目开发与交付，同期落地 Vue3 Composition API 与 Hooks 组合式开发实践。',
      },
    ],
  },
  {
    id: 'futong',
    period: '2018.08 - 2019.12',
    company: '示例云科技',
    role: '前端开发',
    direction: '企业服务（企业云平台）',
    stack: ['Vue', 'Vuex', 'Vue Router', 'Element UI', 'ECharts', 'Axios', 'Sass'],
    highlights: [
      {
        label: '多端开发与组件化',
        text: '负责 App / PC / 微信端页面快速构建，沉淀通用组件提升团队复用效率；落地 ES6 与 Vue / React 编程实践，上手 ECharts、AntV 可视化开发。',
      },
    ],
  },
]

export interface ProjectExperience {
  id: string
  period: string
  name: string
  role: string
  description: string
  stack: string[]
  highlights: Bullet[]
}

export const projects: ProjectExperience[] = [
  {
    id: 'assistant',
    period: '2023.07 - 至今',
    name: '语音助手 / 文本助手',
    role: '前端负责人',
    description: '公司自研的语音助手与文本助手产品。',
    stack: ['Vue3', 'React', 'SSE', 'WebSocket', 'Dify', 'LiteLLM'],
    highlights: [
      {
        label: '前端重构',
        text: '主导语音助手与文本助手前端架构重构，重写会话消息组件与流式渲染逻辑，支撑多轮对话与长会话场景。',
      },
      {
        label: '从 0 开发',
        text: '独立完成文本助手开发，覆盖会话、历史记录、知识库配置、SOP 流程等多个核心模块。',
      },
      {
        label: 'AI 能力接入',
        text: '参与 Dify 应用与工作流配置、LiteLLM 多模型接入；完成数字人 TTS 语音合成结果的播放与字幕同步。',
      },
    ],
  },
  {
    id: 'portal-10000',
    period: '2022.10 - 2023.06',
    name: '电信 10000 号新门户系统',
    role: '前端开发',
    description: '中国电信 10000 号门户重构，并升级部分功能。',
    stack: ['Vue2 全家桶', 'Element UI', 'WebSocket'],
    highlights: [
      {
        label: '模块开发与性能优化',
        text: '负责门户模块开发、公共组件抽离与鉴权模块；优化请求链路，并负责版本控制与环境配置。',
      },
    ],
  },
  {
    id: 'report-platform',
    period: '2023.03 - 2023.07',
    name: '可视化报表平台',
    role: '前端开发',
    description: '以公司内部需求为主做报表平台产品线，定制化开发客户需求。',
    stack: ['React', 'TypeScript', 'Ant Design', 'DataRT'],
    highlights: [
      {
        label: '定制交付',
        text: '基于数据可视化产品线完成电信客户定制化功能开发，梳理二开项目整体代码架构，并按公司产品规划推进内部报表产品线迭代。',
      },
    ],
  },
  {
    id: 'bazirim-h5',
    period: '2020.06 - 2022.10',
    name: 'Bazirim 电商 H5 商城',
    role: '前端开发',
    description: '电商 H5 商城，嵌入 App 实现混合开发，面向新疆用户的商品在线交易平台。',
    stack: ['Vue 全家桶', 'JSBridge', '微信支付'],
    highlights: [
      {
        label: '混合开发与营销',
        text: '通过 WebView 与原生 App 交互，完成商品浏览、下单等核心链路，抽离公共组件解决多机型屏幕兼容；接入微信支付并开发签到小镇、转盘抽奖等多个营销活动页。',
      },
    ],
  },
]

export const otherProjects =
  '示例科技产品门户（多产品统一门户，提出 qiankun 多项目统一管理方案）、Bazirim 商城后台重构（UmiJS / React，含 Excel 导出与高德地图接入）、物流系统 App（uni-app，PDA 端开发与打包部署）、Bazirim-Market 微信分销小程序（原生小程序，登录与支付链路）、供应商管理平台、运营数据大屏（React + ECharts）'

export interface Education {
  id: string
  period: string
  school: string
  degree: string
}

export const educations: Education[] = [
  {
    id: 'university',
    period: '2014.9 - 2018.7',
    school: '示例大学',
    degree: '统招本科',
  },
]

/* ------------------------------------------------------------------ */
/* 详情数据组装                                                        */
/* ------------------------------------------------------------------ */

export function workDetail(item: WorkExperience): DetailView {
  return {
    icon: '🏢',
    title: item.company,
    subtitle: `${item.role} ｜ ${item.direction}`,
    metaRows: [{ label: '在职时间', value: item.period }],
    tags: item.stack,
    sections: [{ heading: '工作内容', bullets: item.highlights }],
  }
}

export function projectDetail(item: ProjectExperience): DetailView {
  return {
    icon: '🚀',
    title: item.name,
    subtitle: item.role,
    metaRows: [
      { label: '项目时间', value: item.period },
      { label: '担任角色', value: item.role },
    ],
    tags: item.stack,
    description: item.description,
    sections: [{ heading: '工作内容', bullets: item.highlights }],
  }
}

export function skillDetail(item: SkillGroup): DetailView {
  return {
    icon: '🧩',
    title: item.category,
    subtitle: '相关技能',
    sections: [{ heading: '技能要点', bullets: item.items.map((text) => ({ text })) }],
  }
}

export function educationDetail(item: Education): DetailView {
  return {
    icon: '🎓',
    title: item.school,
    subtitle: item.degree,
    metaRows: [{ label: '在校时间', value: item.period }],
  }
}
