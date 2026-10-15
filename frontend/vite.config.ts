import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 默认把 /api 代理到本地后端，前端代码里不需要关心跨域。
const backendTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

/**
 * 把简历里的名字注入 index.html。
 *
 * 数据是构建时生成的、不在 git 里，所以标题不能写死在模板里：对外环境显示「李四」，
 * 自己的环境显示自己的名字。读不到生成结果时退回兜底数据，保证一定能构建。
 */
function resumeMetaPlugin() {
  const read = (file: string) => {
    try {
      return JSON.parse(readFileSync(new URL(file, import.meta.url), 'utf8'))
    } catch {
      return null
    }
  }

  return {
    name: 'resume-meta',
    transformIndexHtml(html: string) {
      const meta = read('./src/data/resume.meta.json')
      const fallback = read('./src/data/resume.default.json')
      const name: string = meta?.name ?? fallback?.profile?.name ?? '个人职业空间'
      const title: string = meta?.title ?? fallback?.profile?.title ?? '个人职业空间'
      const summary: string = meta?.summary ?? fallback?.profile?.summary ?? ''
      return html
        .replaceAll('%RESUME_TITLE%', `${name} · ${title}`)
        .replaceAll('%RESUME_DESCRIPTION%', summary ? `${name}的个人职业空间 —— ${summary}` : `${name} · ${title}`)
    },
  }
}

export default defineConfig({
  plugins: [react(), resumeMetaPlugin()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        // SSE 需要，关闭代理缓冲
        ws: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
