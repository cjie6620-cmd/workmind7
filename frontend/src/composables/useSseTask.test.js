// useSseTask 契约测试：version 过期守卫、onSettled 归属判断、abort/detach 语义
import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ fetchStream: vi.fn() }))

vi.mock('@/utils/http.js', () => ({
  fetchStream: mocks.fetchStream,
  default: {},
}))

import { useSseTask } from '@/composables/useSseTask.js'

describe('useSseTask', () => {
  it('正常结束时回调透传且 onSettled 被调用', async () => {
    let version = 0
    const task = useSseTask(() => version)
    mocks.fetchStream.mockImplementation(async (url, body, handlers) => {
      handlers.onToken('a')
      handlers.onDone({ ok: true })
      return { status: 'done' }
    })

    const seen = []
    await task.run('/api/x', {}, {
      onToken: (t) => seen.push(['token', t]),
      onDone: (d) => seen.push(['done', d]),
      onSettled: () => seen.push(['settled']),
    })

    expect(seen).toEqual([['token', 'a'], ['done', { ok: true }], ['settled']])
  })

  it('version 变化后（reset/切换账号）流式回调被丢弃', async () => {
    let version = 0
    const task = useSseTask(() => version)
    mocks.fetchStream.mockImplementation(async (url, body, handlers) => {
      handlers.onToken('early')
      version += 1 // 模拟运行中 store.reset()
      handlers.onToken('late')
      handlers.onDone({})
      return { status: 'done' }
    })

    const seen = []
    await task.run('/api/x', {}, {
      onToken: (t) => seen.push(t),
      onDone: () => seen.push('done'),
    })

    expect(seen).toEqual(['early'])
  })

  it('运行中被 abort 后不执行 onSettled（控制权已被 stop 方接管）', async () => {
    let version = 0
    const task = useSseTask(() => version)
    mocks.fetchStream.mockImplementation(async (url, body, handlers) => {
      task.abort() // 模拟用户点击停止
      expect(handlers.signal.aborted).toBe(true)
      return { status: 'aborted' }
    })

    const settled = vi.fn()
    await task.run('/api/x', {}, { onSettled: settled })

    expect(settled).not.toHaveBeenCalled()
  })

  it('detach 放弃控制权但不中断连接，onSettled 不再执行', async () => {
    let version = 0
    const task = useSseTask(() => version)
    mocks.fetchStream.mockImplementation(async (url, body, handlers) => {
      task.detach() // 模拟离开页面但保留服务端任务
      expect(handlers.signal.aborted).toBe(false)
      return { status: 'done' }
    })

    const settled = vi.fn()
    await task.run('/api/x', {}, { onSettled: settled })

    expect(settled).not.toHaveBeenCalled()
  })

  it('新 run 接管后，旧 run 结束不触发自己的 onSettled', async () => {
    let version = 0
    const task = useSseTask(() => version)

    let releaseFirst
    const firstDone = new Promise((resolve) => { releaseFirst = resolve })
    mocks.fetchStream
      .mockImplementationOnce(async () => { await firstDone; return { status: 'done' } })
      .mockImplementationOnce(async () => ({ status: 'done' }))

    const settledFirst = vi.fn()
    const settledSecond = vi.fn()
    const first = task.run('/api/x', {}, { onSettled: settledFirst })
    const second = task.run('/api/x', {}, { onSettled: settledSecond })

    await second
    releaseFirst()
    await first

    expect(settledSecond).toHaveBeenCalledTimes(1)
    expect(settledFirst).not.toHaveBeenCalled()
  })
})
