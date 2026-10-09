import { Fragment, type ReactNode } from 'react'

interface MarkdownProps {
  content: string
}

const FENCE = /^```(\w*)\s*$/
const HEADING = /^(#{1,6})\s+(.*)$/
const BULLET = /^\s*[-*•]\s+(.*)$/
const ORDERED = /^\s*\d+[.、)]\s+(.*)$/
const QUOTE = /^\s*>\s?(.*)$/
const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))/

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    BULLET.test(line) ||
    ORDERED.test(line) ||
    QUOTE.test(line)
  )
}

/** 行内语法：`代码`、**加粗**、[链接](url)。 */
function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = new RegExp(INLINE.source, 'g')
  let cursor = 0
  let match: RegExpExecArray | null = pattern.exec(text)

  while (match !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index))

    const token = match[0]
    if (token.startsWith('`')) {
      nodes.push(
        <code key={`c${match.index}`} className="chat-md-inline-code">
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={`b${match.index}`}>{token.slice(2, -2)}</strong>)
    } else {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token)
      nodes.push(
        link ? (
          <a key={`a${match.index}`} href={link[2]} target="_blank" rel="noreferrer noopener">
            {link[1]}
          </a>
        ) : (
          token
        ),
      )
    }

    cursor = match.index + token.length
    match = pattern.exec(text)
  }

  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

/**
 * 对话里最常见的几种 Markdown 写法：代码块、标题、列表、引用、行内样式。
 * 自己实现是为了不给浮层塞一个体积不小的 markdown 依赖，也避免整页 HTML 注入。
 */
function renderBlocks(content: string): ReactNode[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    if (FENCE.test(line)) {
      const lang = FENCE.exec(line)?.[1] ?? ''
      const code: string[] = []
      index += 1
      while (index < lines.length && !FENCE.test(lines[index])) {
        code.push(lines[index])
        index += 1
      }
      index += 1 // 跳过收尾的 ```
      blocks.push(
        <pre key={key++} className="chat-md-code" data-lang={lang || undefined}>
          <code>{code.join('\n')}</code>
        </pre>,
      )
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      blocks.push(
        <p key={key++} className="chat-md-heading">
          {renderInline(heading[2])}
        </p>,
      )
      index += 1
      continue
    }

    if (BULLET.test(line)) {
      const items: string[] = []
      while (index < lines.length) {
        const bullet = BULLET.exec(lines[index])
        if (!bullet) break
        items.push(bullet[1])
        index += 1
      }
      blocks.push(
        <ul key={key++} className="chat-md-list">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </ul>,
      )
      continue
    }

    if (ORDERED.test(line)) {
      const items: string[] = []
      while (index < lines.length) {
        const ordered = ORDERED.exec(lines[index])
        if (!ordered) break
        items.push(ordered[1])
        index += 1
      }
      blocks.push(
        <ol key={key++} className="chat-md-list">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </ol>,
      )
      continue
    }

    if (QUOTE.test(line)) {
      const quoted: string[] = []
      while (index < lines.length) {
        const quote = QUOTE.exec(lines[index])
        if (!quote) break
        quoted.push(quote[1])
        index += 1
      }
      blocks.push(
        <blockquote key={key++} className="chat-md-quote">
          {renderInline(quoted.join('\n'))}
        </blockquote>,
      )
      continue
    }

    // 段落：连续的非空行，保留原有换行。
    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={key++} className="chat-md-paragraph">
        {paragraph.map((text, lineIndex) => (
          <Fragment key={lineIndex}>
            {lineIndex > 0 && <br />}
            {renderInline(text)}
          </Fragment>
        ))}
      </p>,
    )
  }

  return blocks
}

export default function Markdown({ content }: MarkdownProps) {
  return <div className="chat-md">{renderBlocks(content)}</div>
}
