// SSE 解析器测试：跨 chunk 分隔、CRLF 兼容、损坏 JSON 抛错（防把断流当正常完成）
import { describe, expect, it, vi } from 'vitest'
import { createSseParser, parseSseEventBlock } from '@/utils/sse.js'

describe('SSE parser', () => {
  it('parses event and JSON data fields', () => {
    expect(parseSseEventBlock('event: token\ndata: {"token":"你好"}')).toEqual({
      event: 'token',
      data: { token: '你好' },
    })
  })

  it('handles CRLF delimiters split across chunks', () => {
    const onEvent = vi.fn()
    const parser = createSseParser(onEvent)

    parser.push('event: token\r\ndata: {"token":"A"}\r')
    parser.push('\n\r\nevent: done\ndata: {"sessionId":"s1"}\n\n')
    parser.finish()

    expect(onEvent).toHaveBeenNthCalledWith(1, 'token', { token: 'A' })
    expect(onEvent).toHaveBeenNthCalledWith(2, 'done', { sessionId: 's1' })
  })

  it('flushes a final event without a blank line', () => {
    const onEvent = vi.fn()
    const parser = createSseParser(onEvent)

    parser.push('event: done\ndata: {"ok":true}')
    parser.finish()

    expect(onEvent).toHaveBeenCalledOnce()
    expect(onEvent).toHaveBeenCalledWith('done', { ok: true })
  })

  it('rejects malformed JSON payloads', () => {
    expect(() => parseSseEventBlock('event: token\ndata: not-json')).toThrow('SSE 数据格式错误')
  })
})
