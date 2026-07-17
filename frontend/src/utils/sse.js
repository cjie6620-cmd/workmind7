/**
 * 解析一个完整的 SSE 事件块。
 * 服务端约定 data 为 JSON；协议损坏时抛错，避免把断流误判为正常完成。
 */
export function parseSseEventBlock(block) {
  if (!block.trim()) return null

  let event = 'message'
  const dataLines = []

  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue

    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    let value = separator === -1 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value || 'message'
    if (field === 'data') dataLines.push(value)
  }

  if (!dataLines.length) return null

  const payload = dataLines.join('\n')
  try {
    return { event, data: JSON.parse(payload) }
  } catch {
    throw new Error(`SSE 数据格式错误：${payload.slice(0, 120)}`)
  }
}

/**
 * 增量 SSE 解析器，兼容 CRLF、跨 chunk 分隔符及末尾无空行的事件。
 */
export function createSseParser(onEvent) {
  let buffer = ''

  function emit(block) {
    const parsed = parseSseEventBlock(block)
    if (parsed) onEvent(parsed.event, parsed.data)
  }

  function push(chunk) {
    buffer += chunk

    let match = /\r?\n\r?\n/.exec(buffer)
    while (match) {
      emit(buffer.slice(0, match.index))
      buffer = buffer.slice(match.index + match[0].length)
      match = /\r?\n\r?\n/.exec(buffer)
    }
  }

  function finish() {
    if (buffer.trim()) emit(buffer)
    buffer = ''
  }

  return { push, finish }
}
