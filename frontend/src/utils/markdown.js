// frontend/src/utils/markdown.js
// 统一 Markdown 渲染 + DOMPurify XSS 净化
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

let configured = false

function ensureMarkedOptions() {
  if (configured) return
  marked.setOptions({
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return hljs.highlightAuto(code).value
    },
    breaks: true,
    gfm: true,
  })
  configured = true
}

/**
 * 将 Markdown 转为安全 HTML（marked + DOMPurify）
 */
export function renderMarkdown(content) {
  if (!content) return ''
  ensureMarkedOptions()
  try {
    const raw = marked.parse(content)
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
  } catch {
    return DOMPurify.sanitize(String(content))
  }
}
