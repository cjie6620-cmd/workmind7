// frontend/src/utils/http.js
// 统一封装 axios：请求拦截、响应拦截、错误处理、SSE 流式请求
import axios from 'axios'
import { useAppStore } from '@/stores/app.js'
import { useAuthStore } from '@/stores/auth.js'

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

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (originalRequest.url?.includes('/auth/refresh') || originalRequest.url?.includes('/auth/login')) {
        authStore.logout()
        window.location.href = '/login'
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return http(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        await authStore.refresh()
        const newToken = authStore.getAccessToken()
        processQueue(null, newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return http(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        authStore.logout()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
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
export async function fetchStream(url, body, { onToken, onEvent, onDone, onError, signal } = {}) {
  const authStore = useAuthStore()
  const token = authStore.getAccessToken()

  try {
    const fetchUrl = import.meta.env.DEV
      ? url.replace('/api', 'http://localhost:3001/api')
      : url

    const headers = { 'Content-Type': 'application/json' }
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(fetchUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      if (response.status === 401) {
        try {
          await authStore.refresh()
          return fetchStream(url, body, { onToken, onEvent, onDone, onError, signal })
        } catch {
          authStore.logout()
          window.location.href = '/login'
          return
        }
      }
      throw new Error(data.error?.message || data.detail?.error?.message || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      if (signal?.aborted) {
        reader.cancel()
        break
      }

      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const normalized = buffer.replace(/\r\n/g, '\n')
      const parts = normalized.split('\n\n')
      buffer = parts.pop() ?? ''

      for (const part of parts) {
        if (!part.trim()) continue

        const lines = part.split('\n')
        let event = 'message'
        const dataLines = []

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            event = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            dataLines.push(line.slice(6))
          }
        }

        const dataStr = dataLines.join('\n')
        if (!dataStr) continue

        let data
        try { data = JSON.parse(dataStr) } catch { continue }

        if (event === 'token' && onToken) {
          onToken(data.token || '')
        } else if (event === 'done' && onDone) {
          onDone(data)
        } else if (event === 'error') {
          onError?.(new Error(data.message || '流式请求出错'))
          return
        } else if (onEvent) {
          onEvent(event, data)
        }
      }
    }

    if (buffer.trim()) {
      const normalized = buffer.replace(/\r\n/g, '\n')
      const lines = normalized.split('\n')
      let event = 'message'
      const dataLines = []

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          event = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          dataLines.push(line.slice(6))
        }
      }

      const dataStr = dataLines.join('\n')
      if (dataStr) {
        try {
          const data = JSON.parse(dataStr)
          if (event === 'token' && onToken) onToken(data.token || '')
          else if (event === 'done' && onDone) onDone(data)
          else if (event === 'error') onError?.(new Error(data.message || '流式请求出错'))
          else if (onEvent) onEvent(event, data)
        } catch { /* ignore */ }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') return
    onError?.(err)
  }
}

export default http
