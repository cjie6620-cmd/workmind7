// frontend/src/utils/http.js
// 统一封装 axios：请求拦截、响应拦截、错误处理、SSE 流式请求
import axios from 'axios'
import { useAppStore } from '@/stores/app.js'
import { useAuthStore } from '@/stores/auth.js'
import { createSseParser } from '@/utils/sse.js'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

let isRefreshing = false
let refreshQueue = []

function processQueue(error, token = null) {
  refreshQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  refreshQueue = []
}

function expireSession(authStore) {
  // 认证失效可能发生在手动登出的远端清理请求中。此处不能 await logout，
  // 否则会等待正在进行的同一个 logoutPromise，形成自等待。
  void authStore.logout({ remoteCleanup: false }).catch(() => {})
  if (window.location.pathname !== '/login') window.location.assign('/login')
}

// ── 请求拦截器 ─────────────────────────────────────────────────
http.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    const token = authStore.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ── 响应拦截器 ─────────────────────────────────────────────────
http.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const appStore = useAppStore()
    const authStore = useAuthStore()
    const originalRequest = error.config

    if (axios.isCancel(error) || error.code === 'ERR_CANCELED') {
      return Promise.reject(error)
    }

    // 401 处理：全局只允许一个刷新在途（isRefreshing 单飞），期间到达的 401 请求
    // 进入 refreshQueue 挂起；刷新成功后统一用新 token 重放，失败则统一登出。
    // 每个请求最多重试一次（_retry 标记），防止新 token 仍无效时进入刷新死循环。
    // 注：authStore.refresh() 内部还有一层 Promise 单飞，两层语义不同——
    // 这里控制"排队重放请求"，那里保证"并发调用共享同一个刷新请求"。
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (originalRequest.url?.includes('/auth/refresh') || originalRequest.url?.includes('/auth/login')) {
        expireSession(authStore)
        return Promise.reject(error)
      }

      // 排队请求也只能重试一次；否则刷新后的 token 仍无效时会再次刷新。
      originalRequest._retry = true
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers ||= {}
          originalRequest.headers.Authorization = `Bearer ${token}`
          return http(originalRequest)
        })
      }

      isRefreshing = true

      try {
        await authStore.refresh()
        const newToken = authStore.getAccessToken()
        processQueue(null, newToken)
        originalRequest.headers ||= {}
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return http(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        expireSession(authStore)
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // silent 请求由调用方自行提示，拦截器不再重复 toast（避免同一错误弹两条）
    if (error.config?.silent) {
      return Promise.reject(error)
    }

    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      appStore.toast.error('请求超时，请稍后重试')
    } else if (error.response) {
      const status = error.response.status
      const msg = error.response.data?.error?.message || error.response.data?.detail?.error?.message || '请求失败'

      if (status === 429) {
        appStore.toast.warning('请求太频繁，请稍后再试')
      } else if (status === 402) {
        appStore.toast.warning('今日预算已用尽，请联系管理员')
      } else if (status >= 500) {
        appStore.toast.error('服务器异常，请稍后重试')
      } else if (status !== 401) {
        appStore.toast.error(msg)
      }
    } else {
      appStore.toast.error('网络异常，请检查连接')
    }

    return Promise.reject(error)
  },
)

// ── SSE 流式请求工具 ───────────────────────────────────────────
/**
 * POST + ReadableStream 消费 SSE（EventSource 不支持 POST/自定义头）。
 *
 * 终态状态机 terminal ∈ {pending, done, error}：
 * - 服务端必须以 done 或 error 事件显式收尾；terminal 仍为 pending 时流被
 *   关闭（EOF）视为断流错误，绝不把断连当成功（防止半截回答被当完整结果）
 * - 401 自动刷新一次并重放；abort 返回 {status:'aborted'} 且不触发 onError
 */
export async function fetchStream(url, body, { onToken, onEvent, onDone, onError, signal } = {}) {
  const authStore = useAuthStore()
  const fetchUrl = import.meta.env.DEV
    ? url.replace('/api', 'http://localhost:3001/api')
    : url

  let terminal = 'pending'
  let terminalData = null
  let streamError = null
  let reader = null

  const isAborted = (err) => signal?.aborted || err?.name === 'AbortError'

  async function openResponse(attempt = 0) {
    const headers = { 'Content-Type': 'application/json' }
    const token = authStore.getAccessToken()
    if (token) headers.Authorization = `Bearer ${token}`

    const response = await fetch(fetchUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    })

    if (response.status === 401) {
      if (attempt === 0) {
        try {
          await authStore.refresh()
          return openResponse(1)
        } catch {
          // 下面统一执行登出和错误回调。
        }
      }

      await authStore.logout({ remoteCleanup: false })
      if (window.location.pathname !== '/login') window.location.assign('/login')
      const authError = new Error('登录已过期，请重新登录')
      authError.status = 401
      throw authError
    }

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      const requestError = new Error(
        data.error?.message || data.detail?.error?.message || `HTTP ${response.status}`,
      )
      requestError.status = response.status
      throw requestError
    }

    if (!response.body) throw new Error('服务端未返回流式响应体')
    return response
  }

  function dispatch(event, data) {
    if (terminal !== 'pending') return

    if (event === 'done') {
      terminal = 'done'
      terminalData = data
      onDone?.(data)
      return
    }

    if (event === 'error') {
      terminal = 'error'
      streamError = new Error(data.message || data.error?.message || '流式请求出错')
      return
    }

    if (event === 'token') onToken?.(data.token || '')
    else onEvent?.(event, data)
  }

  try {
    if (signal?.aborted) return { status: 'aborted' }

    const response = await openResponse()
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser(dispatch)

    while (terminal === 'pending') {
      const { value, done } = await reader.read()
      if (done) {
        parser.push(decoder.decode())
        parser.finish()
        break
      }
      parser.push(decoder.decode(value, { stream: true }))
    }

    if (terminal !== 'pending') await reader.cancel().catch(() => {})
    if (terminal === 'error') throw streamError
    if (terminal === 'done') return { status: 'done', data: terminalData }
    if (signal?.aborted) return { status: 'aborted' }

    throw new Error('流式连接在完成事件前已断开，请重试')
  } catch (err) {
    if (isAborted(err)) return { status: 'aborted' }
    terminal = 'error'
    streamError = err
    onError?.(err)
    return { status: 'error', error: err }
  } finally {
    if (reader) await reader.cancel().catch(() => {})
  }
}

export default http
