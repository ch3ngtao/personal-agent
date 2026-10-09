import type { ReactNode } from 'react'
import {
  FilterOutlined,
  SearchOutlined,
  SwapOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'

export interface DatabaseColumn {
  key: string
  label: string
  width: string
}

export interface DatabaseRow {
  id: string
  cells: ReactNode[]
  /** 有点击详情的行会带 hover 效果 */
  clickable?: boolean
}

interface DatabaseSectionProps {
  title: string
  /** 视图名，例如「List view」或条目数量统计 */
  viewLabel: string
  columns: DatabaseColumn[]
  rows: DatabaseRow[]
  onRowClick?: (id: string) => void
}

/**
 * Notion 数据库「列表视图」的外观：分区标题 + 视图切换条 + 表格。
 */
export default function DatabaseSection({
  title,
  viewLabel,
  columns,
  rows,
  onRowClick,
}: DatabaseSectionProps) {
  return (
    <section className="notion-section">
      <h2 className="notion-h2">{title}</h2>

      <div className="notion-viewbar">
        <span className="notion-viewchip">
          <UnorderedListOutlined />
          {viewLabel}
        </span>
        <span className="notion-viewtools">
          <FilterOutlined />
          <SwapOutlined />
          <SearchOutlined />
        </span>
      </div>

      <table className="notion-table">
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={{ width: column.width }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={row.clickable ? 'is-clickable' : undefined}
              onClick={row.clickable ? () => onRowClick?.(row.id) : undefined}
            >
              {row.cells.map((cell, index) => (
                <td key={columns[index]?.key ?? index}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
