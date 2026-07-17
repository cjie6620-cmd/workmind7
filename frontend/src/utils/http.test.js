import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  authStore: {
    getAccessToken: vi.fn(() => 'access-token'),
    refresh: vi.fn(),
    logout: vi.fn(),
  },
  appStore: {
    toast: {
      error: vi.fn(),
      warning: vi.fn(),
    },
  },
}))

vi.mock('@/stores/auth.js', () => ({ useAuthStore: () => mocks.authStore }))
vi.mock('@/stores/app.js', () => ({ useAppStore: () => mocks.appStore }))

import http, { fetchStream } from '@/utils/http.js'

const defaultAdapter = http.defaults.adapter

function responseFromChunks(chunks, { status = 200, json = {} } = {}) {
  const encoded = chunks.map(chunk => new TextEncoder().encode(chunk))
  let index = 0
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn(async () => json),
    body: {
      getReader: () => ({
        read: vi.fn(async () => (
          index < encoded.length
            ? { value: encoded[index++], done: false }
            : { value: undefined, done: true }
        )),
        cancel: vi.fn(async () => undefined),
      }),
    },
  }
}

describe('fetchStream', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.authStore.getAccessToken.mockReturnValue('access-token')
    mocks.authStore.refresh.mockResolvedValue(undefined)
    mocks.authStore.logout.mockResolvedValue(undefined)
  })

  afterEach(() => {
    http.defaults.adapter = defaultAdapter
    window.history.replaceState({}, '', '/')
  })

  it('delivers tokens and the done payload exactly once', async () => {
    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    globalThis.fetch = vi.fn(async () => responseFromChunks([
      'event: token\ndata: {"token":"你"}\n\n',
      'event: done\ndata: {"sessionId":"s1"}\n\nevent: done\ndata: {"sessionId":"s2"}\n\n',
    ]))

    const result = await fetchStream('/api/test', {}, { onToken, onDone, onError })

    expect(result).toEqual({ status: 'done', data: { sessionId: 's1' } })
    expect(onToken).toHaveBeenCalledWith('你')
    expect(onDone).toHaveBeenCalledOnce()
    expect(onDone).toHaveBeenCalledWith({ sessionId: 's1' })
    expect(onError).not.toHaveBeenCalled()
  })

  it('reports a natural EOF before done as an error', async () => {
    const onError = vi.fn()
    globalThis.fetch = vi.fn(async () => responseFromChunks([
      'event: token\ndata: {"token":"partial"}\n\n',
    ]))

    const result = await fetchStream('/api/test', {}, { onError })

    expect(result.status).toBe('error')
    expect(onError).toHaveBeenCalledOnce()
    expect(onError.mock.calls[0][0].message).toContain('完成事件前已断开')
  })

  it('does not report an aborted request as an error', async () => {
    const controller = new AbortController()
    const onError = vi.fn()
    controller.abort()
    globalThis.fetch = vi.fn()

    const result = await fetchStream('/api/test', {}, {
      signal: controller.signal,
      onError,
    })

    expect(result).toEqual({ status: 'aborted' })
    expect(globalThis.fetch).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('refreshes once after a 401 and retries with the new token', async () => {
    mocks.authStore.refresh.mockImplementationOnce(async () => {
      mocks.authStore.getAccessToken.mockReturnValue('refreshed-token')
    })
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(responseFromChunks([], { status: 401 }))
      .mockResolvedValueOnce(responseFromChunks([
        'event: done\ndata: {"ok":true}\n\n',
      ]))

    const result = await fetchStream('/api/test', {}, {})

    expect(result.status).toBe('done')
    expect(mocks.authStore.refresh).toHaveBeenCalledOnce()
    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    expect(globalThis.fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer refreshed-token')
  })

  it('does not wait for an in-progress logout when the refresh endpoint returns 401', async () => {
    window.history.replaceState({}, '', '/login')
    mocks.authStore.logout.mockReturnValue(new Promise(() => {}))
    http.defaults.adapter = vi.fn(async (config) => Promise.reject({
      config,
      message: 'Unauthorized',
      response: { status: 401, data: {} },
    }))

    let timeoutId
    const outcome = await Promise.race([
      http.get('/auth/refresh').then(() => 'resolved', () => 'rejected'),
      new Promise((resolve) => {
        timeoutId = setTimeout(() => resolve('timeout'), 100)
      }),
    ])
    clearTimeout(timeoutId)

    expect(outcome).toBe('rejected')
    expect(mocks.authStore.logout).toHaveBeenCalledOnce()
    expect(mocks.authStore.logout).toHaveBeenCalledWith({ remoteCleanup: false })
  })
})
