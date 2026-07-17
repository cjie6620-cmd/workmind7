import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown.js'

describe('renderMarkdown', () => {
  it('should sanitize script tags', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script>')
  })

  it('should render normal markdown', () => {
    const html = renderMarkdown('**bold**')
    expect(html).toContain('<strong>bold</strong>')
  })

  it('should highlight registered code languages', () => {
    const html = renderMarkdown('```js\nconst value = true\n```')
    expect(html).toContain('hljs-keyword')
  })
})
