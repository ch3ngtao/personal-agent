#!/usr/bin/env node
/**
 * 构建时用大模型把简历 PDF 转成前端要用的数据结构。
 *
 *   简历 PDF（按 RESUME_FILE / RESUME_NAME 找）
 *     → 抽纯文本 → 交给 DeepSeek 按固定结构输出 JSON → 校验 → 写 src/data/resume.generated.ts
 *
 * 省钱省时的点：生成结果按「PDF 内容哈希 + 生成规则版本 + 模型名」缓存，
 * 简历没更新就直接复用上一次的结果，不再调大模型。
 *
 * 兜底：生成不了（没网 / 没 Key / 模型输出不合法）时，非严格模式会沿用上一次的
 * 生成结果；连生成结果都没有就用 resume.default.json（公开版本），保证构建不挂。
 * 严格模式（RESUME_GEN_STRICT=1，给真实简历用）直接报错退出，避免悄悄用错数据。
 *
 * 常用环境变量：
 *   RESUME_FILE          简历文件名（相对 RESUME_DIR 或仓库根目录，也可写绝对路径）
 *   RESUME_NAME          只给名字时按 简历-<名字>.pdf 找
 *   RESUME_DIR           PDF 所在目录，默认仓库根目录
 *   RESUME_GEN_MODEL     生成用模型，默认取 DEEPSEEK_MODEL 或 deepseek-chat
 *   RESUME_GEN_CACHE_DIR 缓存目录，默认 src/data/.resume-cache
 *   RESUME_GEN_STRICT    1 = 必须生成成功，失败就报错退出
 *   DEEPSEEK_API_KEY     大模型 Key（也会自动读仓库根目录 / frontend / backend 的 .env）
 *
 * 参数：
 *   --force          忽略缓存，强制重新生成
 *   --emit-json PATH 额外把原始 JSON 写到指定路径（用来更新 resume.default.json）
 */

import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const FRONTEND_DIR = resolve(SCRIPT_DIR, '..')
const REPO_ROOT = resolve(FRONTEND_DIR, '..')
const DATA_DIR = join(FRONTEND_DIR, 'src', 'data')

const GENERATED_FILE = join(DATA_DIR, 'resume.generated.ts')
/** index.html 里标题 / 描述的来源：构建时注入，避免把名字写死在模板里 */
const META_FILE = join(DATA_DIR, 'resume.meta.json')
const DEFAULT_DATA_FILE = join(DATA_DIR, 'resume.default.json')

/** 生成规则版本：改提示词、改校验、改数据结构时 +1，旧缓存就会自动失效 */
const PROMPT_VERSION = 2

const DEFAULT_RESUME_FILE = '简历-李四.pdf'
const DEFAULT_MODEL = 'deepseek-chat'
const DEFAULT_BASE_URL = 'https://api.deepseek.com'
const MAX_ATTEMPTS = 3

// ---------------------------------------------------------------- 基础工具

const say = (message) => console.log(`[resume] ${message}`)
const warn = (message) => console.warn(`[resume] ⚠ ${message}`)

function fail(message) {
  console.error(`[resume] ✗ ${message}`)
  process.exit(1)
}

/** 从 KEY=VALUE 的 .env 里读一个值，忽略注释与空行 */
function readEnvFile(path, name) {
  if (!existsSync(path)) return undefined
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const index = trimmed.indexOf('=')
    if (index < 1) continue
    if (trimmed.slice(0, index).trim() !== name) continue
    let value = trimmed.slice(index + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    return value
  }
  return undefined
}

/** 环境变量优先，其次仓库根目录 / frontend / backend 的 .env */
function env(name) {
  const fromProcess = process.env[name]
  if (fromProcess !== undefined && fromProcess !== '') return fromProcess
  for (const file of [join(REPO_ROOT, '.env'), join(FRONTEND_DIR, '.env'), join(REPO_ROOT, 'backend', '.env')]) {
    const value = readEnvFile(file, name)
    if (value !== undefined && value !== '') return value
  }
  return ''
}

const isTruthy = (value) => ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase())

const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex')

/** 模型名里的 / : 等字符不能直接当文件名 */
const slugify = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

/** 列表用的稳定 id：英文 slug 直接用，模型给了中文就退回位置编号 */
function normalizeId(raw, position, prefix) {
  const slug = slugify(raw ?? '')
  return /^[a-z][a-z0-9-]{1,40}$/.test(slug) ? slug : `${prefix}-${position + 1}`
}

const asText = (value) => (typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim())

function asTextList(value) {
  if (Array.isArray(value)) return value.map(asText).filter(Boolean)
  const text = asText(value)
  if (!text) return []
  return text
    .split(/[、,，;；|]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function normalizeBullets(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (typeof item === 'string') {
        const text = asText(item)
        return text ? { text } : null
      }
      if (!item || typeof item !== 'object') return null
      const text = asText(item.text ?? item.detail ?? item.content)
      if (!text) return null
      const label = asText(item.label ?? item.title)
      return label ? { label, text } : { text }
    })
    .filter(Boolean)
}

// ---------------------------------------------------------------- 数据校验

/**
 * 把模型返回的 JSON 收敛成页面要的结构：
 * 缺字段补空、类型不对就纠正，最后检查关键字段是否齐全。
 * @returns {{ data: object, problems: string[] }}
 */
function normalize(raw) {
  const problems = []
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { data: null, problems: ['顶层不是 JSON 对象'] }
  }

  const rawProfile = raw.profile && typeof raw.profile === 'object' ? raw.profile : {}
  const rawIntention = rawProfile.intention && typeof rawProfile.intention === 'object' ? rawProfile.intention : {}
  const age = Number.parseInt(asText(rawProfile.age).replace(/[^\d]/g, ''), 10)

  const profile = {
    name: asText(rawProfile.name),
    title: asText(rawProfile.title) || '个人职业空间',
    icon: asText(rawProfile.icon) || '💻',
    summary: asText(rawProfile.summary),
    gender: asText(rawProfile.gender),
    age: Number.isFinite(age) ? age : 0,
    phone: asText(rawProfile.phone),
    email: asText(rawProfile.email),
    intention: {
      position: asText(rawIntention.position),
      city: asText(rawIntention.city),
      salary: asText(rawIntention.salary) || '面议',
      type: asText(rawIntention.type) || '社招',
    },
  }
  if (!profile.name) problems.push('profile.name 为空')
  if (!profile.summary) problems.push('profile.summary 为空')

  const skills = (Array.isArray(raw.skills) ? raw.skills : [])
    .map((item, index) => {
      if (!item || typeof item !== 'object') return null
      const items = asTextList(item.items ?? item.points)
      const category = asText(item.category ?? item.name)
      if (!category || items.length === 0) return null
      return { id: normalizeId(item.id, index, 'skill'), category, items }
    })
    .filter(Boolean)
  if (skills.length === 0) problems.push('skills 为空')

  const workExperiences = (Array.isArray(raw.workExperiences) ? raw.workExperiences : [])
    .map((item, index) => {
      if (!item || typeof item !== 'object') return null
      const company = asText(item.company)
      if (!company) return null
      return {
        id: normalizeId(item.id, index, 'work'),
        period: asText(item.period),
        company,
        role: asText(item.role),
        direction: asText(item.direction),
        stack: asTextList(item.stack),
        highlights: normalizeBullets(item.highlights ?? item.details),
      }
    })
    .filter(Boolean)
  if (workExperiences.length === 0) problems.push('workExperiences 为空')

  const projects = (Array.isArray(raw.projects) ? raw.projects : [])
    .map((item, index) => {
      if (!item || typeof item !== 'object') return null
      const name = asText(item.name ?? item.project)
      if (!name) return null
      return {
        id: normalizeId(item.id, index, 'project'),
        period: asText(item.period),
        name,
        role: asText(item.role),
        description: asText(item.description),
        stack: asTextList(item.stack),
        highlights: normalizeBullets(item.highlights ?? item.details),
      }
    })
    .filter(Boolean)
  if (projects.length === 0) problems.push('projects 为空')

  const educations = (Array.isArray(raw.educations) ? raw.educations : [])
    .map((item, index) => {
      if (!item || typeof item !== 'object') return null
      const school = asText(item.school)
      if (!school) return null
      return {
        id: normalizeId(item.id, index, 'education'),
        period: asText(item.period),
        school,
        degree: asText(item.degree),
      }
    })
    .filter(Boolean)

  const otherProjects = asText(raw.otherProjects ?? raw.others)

  // id 重复会让详情抽屉点错条目，统一加后缀去重
  for (const list of [skills, workExperiences, projects, educations]) {
    const seen = new Set()
    for (const item of list) {
      let id = item.id
      let suffix = 2
      while (seen.has(id)) id = `${item.id}-${suffix++}`
      item.id = id
      seen.add(id)
    }
  }

  return {
    data: { profile, skills, workExperiences, projects, otherProjects, educations },
    problems,
  }
}

// ---------------------------------------------------------------- 大模型

function buildMessages(pdfText, example, retryHint) {
  const system = [
    '你是简历信息抽取助手，把简历 PDF 的纯文本转成结构化 JSON。',
    '',
    '硬性要求：',
    '1. 只输出一个 JSON 对象，不要 markdown 代码块、不要注释、不要任何解释文字。',
    '2. 字段名与结构与示例完全一致，不要增删字段、不要改字段类型。',
    '3. 只使用简历原文里的信息，不要编造经历、数字、时间、联系方式；原文没有的字段填空字符串或空数组。',
    '4. 文本保留中文原文，可以去掉换行噪音、整理成通顺的一句话，但不要改变事实与数字。',
    '5. id 用小写英文短横线 slug（如 huayun、assistant、ai-app），同一数组内不重复。',
    '6. highlights 是分点细节：label 是 4-8 个字的小标题（可省略），text 是一句话，尽量保留原文的数字与成果。',
    '7. profile.summary 是首页用的一段自我介绍（80-160 字），把原文第一段整理通顺。',
    '8. otherProjects 把零散的小项目/经历合并成一段用「、」连接的文字。',
    '9. skills[].items 要拆成短条目：原文用「；」分隔的要点拆成多个数组元素，每条 10-30 字，不要把整段塞成一条。',
    '10. stack 只放技术名词（如 Vue3、TypeScript、Kubernetes），用「/」或「、」分隔的原文要拆成多个数组元素，保持简短。',
  ].join('\n')

  const user = [
    '这是数据结构示例（内容与本次任务无关，只看字段与层级）：',
    '```json',
    JSON.stringify(example, null, 2),
    '```',
    '',
    '把下面这份简历转成同样的 JSON：',
    '"""',
    pdfText,
    '"""',
    retryHint ? `\n上一次输出不可用：${retryHint}。请修正后重新输出完整 JSON。` : '',
  ].join('\n')

  return [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ]
}

async function callModel({ baseUrl, apiKey, model, pdfText, example, hint }) {
  const response = await fetch(`${baseUrl.replace(/\/+$/, '')}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      temperature: 0,
      max_tokens: 8000,
      response_format: { type: 'json_object' },
      messages: buildMessages(pdfText, example, hint),
    }),
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`大模型返回 ${response.status}：${body.slice(0, 300)}`)
  }

  const payload = await response.json()
  const content = payload?.choices?.[0]?.message?.content
  if (typeof content !== 'string' || !content.trim()) throw new Error('大模型返回内容为空')
  return content
}

/** 模型偶尔会裹一层 ```json，这里剥掉再解析 */
function parseJson(content) {
  let text = content.trim()
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fence) text = fence[1].trim()
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('返回内容里没有 JSON 对象')
  return JSON.parse(text.slice(start, end + 1))
}

// ---------------------------------------------------------------- 渲染

function renderTypeScript(data, source) {
  const header = [
    '/**',
    ' * 本文件由 scripts/generate-resume-data.mjs 在构建时自动生成，请勿手改。',
    ` * 来源简历：${source.file}（sha256 ${source.sha256.slice(0, 12)}…）`,
    ` * 生成方式：${source.model} / 规则版本 v${source.promptVersion}${
      source.fromCache ? ' / 复用缓存' : ''
    }${source.fallback ? ' / 兜底数据' : ''}`,
    ` * 生成时间：${source.generatedAt}`,
    ' */',
    '',
    "import type { Education, Profile, ProjectExperience, ResumeSource, SkillGroup, WorkExperience } from './resume.types'",
    '',
  ].join('\n')

  const json = (value) => JSON.stringify(value, null, 2)

  const body = [
    `export const resumeSource: ResumeSource = ${json(source)}`,
    '',
    `export const profile: Profile = ${json(data.profile)}`,
    '',
    `export const skills: SkillGroup[] = ${json(data.skills)}`,
    '',
    `export const workExperiences: WorkExperience[] = ${json(data.workExperiences)}`,
    '',
    `export const projects: ProjectExperience[] = ${json(data.projects)}`,
    '',
    `export const otherProjects: string = ${JSON.stringify(data.otherProjects ?? '')}`,
    '',
    `export const educations: Education[] = ${json(data.educations)}`,
    '',
  ].join('\n')

  return `${header}\n${body}`
}

function writeGenerated(data, source) {
  mkdirSync(DATA_DIR, { recursive: true })
  writeFileSync(GENERATED_FILE, renderTypeScript(data, source), 'utf8')
  // 页面 <title> 与 meta description 也来自简历本身，这样两个环境各显示各的名字
  writeFileSync(
    META_FILE,
    JSON.stringify(
      {
        name: data.profile.name,
        title: data.profile.title,
        summary: data.profile.summary,
        source: source.file,
      },
      null,
      2,
    ) + '\n',
    'utf8',
  )
}

// ---------------------------------------------------------------- 主流程

async function extractPdfText(buffer) {
  const { extractText, getDocumentProxy } = await import('unpdf')
  const pdf = await getDocumentProxy(new Uint8Array(buffer))
  const result = await extractText(pdf, { mergePages: true })
  const text = Array.isArray(result.text) ? result.text.join('\n') : result.text
  return String(text ?? '').replace(/\n{3,}/g, '\n\n').trim()
}

function loadExample(envPath) {
  const explicit = asText(envPath)
  const candidates = explicit ? [explicit] : [DEFAULT_DATA_FILE]
  for (const candidate of candidates) {
    const path = isAbsolute(candidate) ? candidate : resolve(REPO_ROOT, candidate)
    if (!existsSync(path)) continue
    const raw = JSON.parse(readFileSync(path, 'utf8'))
    return raw?.data && typeof raw.data === 'object' ? raw.data : raw
  }
  if (explicit) fail(`示例数据不存在：${explicit}`)
  return null
}

async function main() {
  const args = process.argv.slice(2)
  const force = args.includes('--force')
  const emitIndex = args.indexOf('--emit-json')
  const emitJsonPath = emitIndex >= 0 ? args[emitIndex + 1] : null
  if (emitIndex >= 0 && !emitJsonPath) fail('--emit-json 后面要跟一个路径')

  const resumeDir = asText(env('RESUME_DIR'))
  const resumeName = asText(env('RESUME_NAME'))
  const resumeFile = asText(env('RESUME_FILE')) || (resumeName ? `简历-${resumeName}.pdf` : DEFAULT_RESUME_FILE)
  const pdfPath = isAbsolute(resumeFile)
    ? resumeFile
    : join(resumeDir ? (isAbsolute(resumeDir) ? resumeDir : resolve(REPO_ROOT, resumeDir)) : REPO_ROOT, resumeFile)

  const strict = isTruthy(env('RESUME_GEN_STRICT'))
  const model = asText(env('RESUME_GEN_MODEL')) || asText(env('DEEPSEEK_MODEL')) || DEFAULT_MODEL
  const baseUrl = asText(env('DEEPSEEK_BASE_URL')) || DEFAULT_BASE_URL
  const apiKey = asText(env('DEEPSEEK_API_KEY'))
  const cacheDir = asText(env('RESUME_GEN_CACHE_DIR')) || join(DATA_DIR, '.resume-cache')
  const example = loadExample(env('RESUME_GEN_EXAMPLE'))
  const fileName = pdfPath.split('/').pop()

  say(`简历文件：${pdfPath}`)

  // ---- 兜底数据（公开版本）----
  const fallback = () => {
    if (existsSync(GENERATED_FILE)) {
      warn('本次没能重新生成，沿用上一次的生成结果')
      return false
    }
    if (!example) fail('既没有生成结果，也没有兜底数据 resume.default.json，无法继续')
    const { data, problems } = normalize(example)
    if (!data) fail(`兜底数据不可用：${problems.join('；')}`)
    writeGenerated(data, {
      file: 'resume.default.json',
      sha256: sha256(readFileSync(DEFAULT_DATA_FILE)),
      model: 'fallback',
      promptVersion: PROMPT_VERSION,
      generatedAt: new Date().toISOString(),
      fromCache: true,
      fallback: true,
    })
    warn('已改用兜底数据 resume.default.json（注意：这不是本次简历的内容）')
    return false
  }

  if (!existsSync(pdfPath)) {
    const message = `找不到简历 PDF：${pdfPath}（可用 RESUME_FILE / RESUME_NAME 指定）`
    if (strict) fail(message)
    warn(message)
    fallback()
    return
  }

  const bytes = readFileSync(pdfPath)
  const hash = sha256(bytes)
  const cacheFile = join(cacheDir, `${hash.slice(0, 16)}-v${PROMPT_VERSION}-${slugify(model)}.json`)
  say(`内容哈希：${hash.slice(0, 12)}…（${bytes.length} 字节）`)

  // ---- 命中缓存：简历没更新，直接用上次的结果 ----
  if (!force && existsSync(cacheFile)) {
    try {
      const cached = JSON.parse(readFileSync(cacheFile, 'utf8'))
      const { data, problems } = normalize(cached.data)
      if (data && problems.length === 0) {
        writeGenerated(data, {
          file: fileName,
          sha256: hash,
          model,
          promptVersion: PROMPT_VERSION,
          generatedAt: cached.generatedAt ?? new Date().toISOString(),
          fromCache: true,
          fallback: false,
        })
        say(`简历没有更新，复用上次的生成结果（未调用大模型）：工作 ${data.workExperiences.length} 段 / 项目 ${data.projects.length} 个 / 技能 ${data.skills.length} 组`)
        if (emitJsonPath) writeFileSync(resolve(emitJsonPath), JSON.stringify(data, null, 2) + '\n', 'utf8')
        return
      }
      warn('缓存数据校验没过，重新生成')
    } catch (error) {
      warn(`缓存读取失败（${error.message}），重新生成`)
    }
  }

  // ---- 需要重新生成 ----
  const blockers = []
  if (!apiKey) blockers.push('没有配置 DEEPSEEK_API_KEY')
  if (!example) blockers.push('缺少 resume.default.json 作为格式示例')

  if (blockers.length === 0) {
    try {
      let pdfText = ''
      try {
        pdfText = await extractPdfText(bytes)
      } catch (error) {
        blockers.push(`PDF 解析失败（${error.message}）`)
      }

      if (!pdfText) {
        blockers.push('PDF 里没抽到文字（可能是纯图片扫描版）')
      } else {
        let hint = ''
        for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
          say(`调用 ${model} 生成数据（第 ${attempt}/${MAX_ATTEMPTS} 次）…`)
          try {
            const content = await callModel({ baseUrl, apiKey, model, pdfText, example, hint })
            const { data, problems } = normalize(parseJson(content))
            if (data && problems.length === 0) {
              mkdirSync(cacheDir, { recursive: true })
              const generatedAt = new Date().toISOString()
              writeFileSync(
                cacheFile,
                JSON.stringify({ generatedAt, hash, model, promptVersion: PROMPT_VERSION, data }, null, 2) + '\n',
                'utf8',
              )
              writeGenerated(data, {
                file: fileName,
                sha256: hash,
                model,
                promptVersion: PROMPT_VERSION,
                generatedAt,
                fromCache: false,
                fallback: false,
              })
              if (emitJsonPath) writeFileSync(resolve(emitJsonPath), JSON.stringify(data, null, 2) + '\n', 'utf8')
              say(`生成完成并写入缓存：工作 ${data.workExperiences.length} 段 / 项目 ${data.projects.length} 个 / 技能 ${data.skills.length} 组`)
              return
            }
            hint = problems.join('；') || '结构与要求不一致'
            warn(`第 ${attempt} 次结果不可用：${hint}`)
          } catch (error) {
            hint = error.message
            warn(`第 ${attempt} 次调用失败：${error.message}`)
          }
        }
        blockers.push(`${MAX_ATTEMPTS} 次都没能生成可用数据（最后一次：${hint}）`)
      }
    } catch (error) {
      blockers.push(error.message)
    }
  }

  const message = `简历数据生成失败：${blockers.join('；')}`
  if (strict) fail(message)
  warn(message)
  fallback()
}

main().catch((error) => {
  console.error(`[resume] ✗ 生成脚本异常：${error.stack ?? error.message}`)
  process.exit(1)
})
