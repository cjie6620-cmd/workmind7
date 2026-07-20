// frontend/src/utils/download.js
// 浏览器端文件下载工具（Blob → 临时 URL → 触发 <a> 点击）

/** 把 Markdown 文本作为 {filename}.md 下载到本地 */
export function downloadMarkdown(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}.md`
  a.click()
  URL.revokeObjectURL(url)
}
