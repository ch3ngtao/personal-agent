import { Drawer } from 'antd'
import type { DetailView } from '../../data/resume'

interface DetailDrawerProps {
  detail: DetailView | null
  onClose: () => void
}

/**
 * Notion 的 side peek：从右侧滑出，展示某条记录的完整内容。
 * 不遮罩整页，方便继续浏览左侧列表。
 */
export default function DetailDrawer({ detail, onClose }: DetailDrawerProps) {
  return (
    <Drawer
      open={detail !== null}
      onClose={onClose}
      placement="right"
      width={560}
      mask={false}
      title={null}
      styles={{ body: { padding: '8px 36px 56px' } }}
    >
      {detail && (
        <article>
          <div className="notion-detail-icon">{detail.icon}</div>
          <h1 className="notion-detail-title">{detail.title}</h1>
          {detail.subtitle && <div className="notion-detail-subtitle">{detail.subtitle}</div>}

          {detail.tags && detail.tags.length > 0 && (
            <div className="notion-detail-tags">
              {detail.tags.map((tag) => (
                <span key={tag} className="notion-detail-tag">
                  {tag}
                </span>
              ))}
            </div>
          )}

          {detail.metaRows && detail.metaRows.length > 0 && (
            <div className="notion-detail-meta">
              {detail.metaRows.map((row) => (
                <div key={row.label} className="notion-detail-meta-row">
                  <span className="notion-detail-meta-key">{row.label}</span>
                  <span>{row.value}</span>
                </div>
              ))}
            </div>
          )}

          {detail.description && <p className="notion-detail-description">{detail.description}</p>}

          {detail.sections?.map((section) => (
            <section key={section.heading}>
              <h3 className="notion-detail-section-title">{section.heading}</h3>
              {section.bullets.map((bullet, index) => (
                <div key={`${section.heading}-${index}`} className="notion-detail-bullet">
                  <span className="notion-detail-bullet-dot">•</span>
                  <span>
                    {bullet.label && (
                      <span className="notion-detail-bullet-label">{bullet.label}：</span>
                    )}
                    {bullet.text}
                  </span>
                </div>
              ))}
            </section>
          ))}
        </article>
      )}
    </Drawer>
  )
}
