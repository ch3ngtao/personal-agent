import { useState } from 'react'
import { GithubOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import ChatWidget from '../components/chat/ChatWidget'
import DatabaseSection, { type DatabaseRow } from '../components/notion/DatabaseSection'
import DetailDrawer from '../components/notion/DetailDrawer'
import {
  educations,
  educationDetail,
  otherProjects,
  profile,
  projectDetail,
  projects,
  skillDetail,
  skills,
  workDetail,
  workExperiences,
  type DetailView,
} from '../data/resume'

export default function CareerSpace() {
  const [detail, setDetail] = useState<DetailView | null>(null)

  const openWork = (id: string) => {
    const item = workExperiences.find((work) => work.id === id)
    if (item) setDetail(workDetail(item))
  }

  const openProject = (id: string) => {
    const item = projects.find((project) => project.id === id)
    if (item) setDetail(projectDetail(item))
  }

  const openSkill = (id: string) => {
    const item = skills.find((skill) => skill.id === id)
    if (item) setDetail(skillDetail(item))
  }

  const openEducation = (id: string) => {
    const item = educations.find((education) => education.id === id)
    if (item) setDetail(educationDetail(item))
  }

  const workRows: DatabaseRow[] = workExperiences.map((work) => ({
    id: work.id,
    clickable: true,
    cells: [work.period, work.company, work.role],
  }))

  const skillRows: DatabaseRow[] = skills.map((skill) => ({
    id: skill.id,
    clickable: true,
    cells: [skill.category, skill.items.join('，')],
  }))

  const educationRows: DatabaseRow[] = educations.map((education) => ({
    id: education.id,
    clickable: true,
    cells: [education.period, education.school, education.degree],
  }))

  const projectRows: DatabaseRow[] = projects.map((project) => ({
    id: project.id,
    clickable: true,
    cells: [project.period, project.name, project.role],
  }))

  const properties = [
    { label: '姓名', value: `${profile.name}（${profile.gender} · ${profile.age} 岁）` },
    { label: '电话', value: profile.phone },
    { label: '邮箱', value: profile.email },
    { label: '意向岗位', value: profile.intention.position },
    { label: '意向城市', value: profile.intention.city },
    { label: '求职类型', value: `${profile.intention.type} · 期望薪资 ${profile.intention.salary}` },
  ]

  return (
    <div className="notion-page">
      <div className="notion-topbar">
        <Button
          size="small"
          icon={<GithubOutlined />}
          href="https://github.com/ch3ngtao/personal-agent"
          target="_blank"
          rel="noopener noreferrer"
        >
          GitHub
        </Button>
      </div>

      <div className="notion-cover">
        <img src="/cover.jpg" alt="" />
      </div>

      <div className="notion-body">
        <div className="notion-icon">{profile.icon}</div>
        <h1 className="notion-title">{profile.title}</h1>
        <p className="notion-summary">{profile.summary}</p>

        <div className="notion-props">
          {properties.map((property) => (
            <div key={property.label} className="notion-prop">
              <span className="notion-prop-key">{property.label}</span>
              <span className="notion-prop-val">{property.value}</span>
            </div>
          ))}
        </div>

        <div className="notion-grid">
          <DatabaseSection
            title="工作经历"
            viewLabel="List view"
            columns={[
              { key: 'period', label: '时间', width: '142px' },
              { key: 'company', label: '公司', width: 'auto' },
              { key: 'role', label: '职位', width: '96px' },
            ]}
            rows={workRows}
            onRowClick={openWork}
          />

          <DatabaseSection
            title="相关技能"
            viewLabel="List view"
            columns={[
              { key: 'category', label: '分类', width: '116px' },
              { key: 'items', label: '技能要点', width: 'auto' },
            ]}
            rows={skillRows}
            onRowClick={openSkill}
          />

          <DatabaseSection
            title="教育经历"
            viewLabel="List view"
            columns={[
              { key: 'period', label: '时间', width: '142px' },
              { key: 'school', label: '学校', width: 'auto' },
              { key: 'degree', label: '学历', width: '80px' },
            ]}
            rows={educationRows}
            onRowClick={openEducation}
          />

          <DatabaseSection
            title="项目经验"
            viewLabel={String(projects.length) + ' 个项目'}
            columns={[
              { key: 'period', label: '时间', width: '142px' },
              { key: 'name', label: '项目', width: 'auto' },
              { key: 'role', label: '角色', width: '88px' },
            ]}
            rows={projectRows}
            onRowClick={openProject}
          />
        </div>

        <div className="notion-footnote">
          <span className="notion-footnote-label">其他项目：</span>
          {otherProjects}
        </div>
      </div>

      <DetailDrawer detail={detail} onClose={() => setDetail(null)} />
      <ChatWidget />
    </div>
  )
}
