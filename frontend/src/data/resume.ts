/**
 * 简历数据入口：类型 + 数据 + 详情组装。
 *
 * 数据不手写了，构建时由 ``scripts/generate-resume-data.mjs`` 从简历 PDF 生成，
 * 落在 ``resume.generated.ts``（构建产物，不进 git）；生成不出来时用
 * ``resume.default.json``（公开版本）兜底，保证页面永远有内容。
 * 页面结构与视觉参考 Notion「个人职业空间」模板。
 */

export type {
  Bullet,
  DetailSection,
  DetailView,
  Education,
  Profile,
  ProjectExperience,
  ResumeSource,
  SkillGroup,
  WorkExperience,
} from './resume.types'

export {
  educations,
  otherProjects,
  profile,
  projects,
  resumeSource,
  skills,
  workExperiences,
} from './resume.generated'

import type { DetailView, Education, ProjectExperience, SkillGroup, WorkExperience } from './resume.types'

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
