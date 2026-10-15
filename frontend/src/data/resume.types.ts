/**
 * 简历数据的类型定义（手写，稳定）。
 *
 * 数据本身由构建脚本从简历 PDF 生成，写在 ``resume.generated.ts`` 里；
 * 兜底数据是 ``resume.default.json``（公开版本）。页面与组件统一从
 * ``data/resume.ts`` 取数据与类型，不要直接引用生成文件。
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

export interface Profile {
  name: string
  title: string
  icon: string
  summary: string
  gender: string
  age: number
  phone: string
  email: string
  intention: {
    position: string
    city: string
    salary: string
    type: string
  }
}

export interface SkillGroup {
  id: string
  category: string
  items: string[]
}

export interface WorkExperience {
  id: string
  period: string
  company: string
  role: string
  direction: string
  stack: string[]
  highlights: Bullet[]
}

export interface ProjectExperience {
  id: string
  period: string
  name: string
  role: string
  description: string
  stack: string[]
  highlights: Bullet[]
}

export interface Education {
  id: string
  period: string
  school: string
  degree: string
}

/** 这批数据是怎么来的，用于构建日志与排查（也会写进生成文件）。 */
export interface ResumeSource {
  /** 简历 PDF 文件名 */
  file: string
  /** PDF 内容哈希，简历改了这里就会变 */
  sha256: string
  /** 生成用的模型 */
  model: string
  /** 生成规则版本，改了提示词/校验逻辑会 +1，用来让旧缓存失效 */
  promptVersion: number
  /** 生成时间（ISO 字符串） */
  generatedAt: string
  /** 是否直接复用上一次的生成结果（简历内容没变） */
  fromCache: boolean
  /** 是否退回了兜底数据（没生成成功） */
  fallback: boolean
}
