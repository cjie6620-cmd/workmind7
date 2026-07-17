// frontend/src/utils/markdown.js
// 统一 Markdown 渲染 + DOMPurify XSS 净化
import { marked, Renderer } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github-dark.css'

for (const [name, language] of Object.entries({
  bash, css, java, javascript, json, markdown, python, sql, typescript, xml, yaml,
})) {
  hljs.registerLanguage(name, language)
}

let configured = false

function ensureMarkedOptions() {
  if (configured) return
  const renderer = new Renderer()
  renderer.code = (code, infoString) => {
    const language = (infoString || '').trim().split(/\s+/)[0].toLowerCase()
    const highlighted = language && hljs.getLanguage(language)
      ? hljs.highlight(code, { language }).value
      : hljs.highlightAuto(code).value
    const languageClass = language.replace(/[^a-z0-9_+-]/g, '')
    const className = languageClass ? ` language-${languageClass}` : ''
    return `<pre><code class="hljs${className}">${highlighted}</code></pre>\n`
  }

  marked.setOptions({
    renderer,
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
