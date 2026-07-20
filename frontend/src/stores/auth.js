/**
 * 认证状态管理
 *
 * Token 存储在 localStorage（刷新页面保持登录）。
 * 注意：localStorage 可被 XSS 读取，生产环境须确保所有 v-html 经 DOMPurify 净化。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import http from '@/utils/http.js'

const TOKEN_KEY = 'wm_access_token'
const REFRESH_KEY = 'wm_refresh_token'
const USER_KEY = 'wm_user'

function _readStoredUser() {
  // localStorage 被外部写坏时 JSON.parse 会抛异常导致整站白屏；容错回退 null。
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem(TOKEN_KEY) || '')
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) || '')
  const user = ref(_readStoredUser())
  let logoutPromise = null
  let refreshPromise = null
  let authVersion = 0

  const isLoggedIn = computed(() => !!accessToken.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  function _persist() {
    if (accessToken.value) {
      localStorage.setItem(TOKEN_KEY, accessToken.value)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
    if (refreshToken.value) {
      localStorage.setItem(REFRESH_KEY, refreshToken.value)
    } else {
      localStorage.removeItem(REFRESH_KEY)
    }
    if (user.value) {
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    } else {
      localStorage.removeItem(USER_KEY)
    }
  }

  function _clearCredentials() {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    _persist()
  }

  async function login(username, password) {
    // authVersion 竞态守卫：登录请求在途时若发生登出/再次登录，版本号变化，
    // 迟到的响应被丢弃，避免旧凭据覆盖新会话
    const version = ++authVersion
    const data = await http.post('/auth/login', { username, password })
    if (version !== authVersion) throw new Error('登录状态已变更，请重试')
    accessToken.value = data.accessToken
    refreshToken.value = data.refreshToken
    user.value = { userId: data.userId, username, role: data.role }
    _persist()
    return data
  }

  async function refresh() {
    if (refreshPromise) return refreshPromise
    if (!refreshToken.value) {
      throw new Error('无 refresh token')
    }

    const version = authVersion
    refreshPromise = (async () => {
      try {
        const data = await http.post('/auth/refresh', { refreshToken: refreshToken.value })
        if (version !== authVersion) throw new Error('认证状态已变更')
        accessToken.value = data.accessToken
        refreshToken.value = data.refreshToken
        if (user.value) {
          user.value.role = data.role
          user.value.userId = data.userId
        }
        _persist()
        return data
      } finally {
        refreshPromise = null
      }
    })()

    return refreshPromise
  }

  async function logout({ remoteCleanup = true } = {}) {
    if (logoutPromise) {
      // 认证失效跳转不能等待远端清理；同步清除凭据，避免重载后短暂恢复旧会话。
      if (!remoteCleanup) _clearCredentials()
      return logoutPromise
    }

    authVersion += 1
    // 显式登出时先记住 refresh token，用于服务端吊销其 jti。
    const revokeToken = remoteCleanup ? refreshToken.value : ''
    if (!remoteCleanup) _clearCredentials()

    logoutPromise = (async () => {
      try {
        if (revokeToken) {
          // 尽力吊销服务端 refresh jti；失败不阻断本地登出。
          await http.post('/auth/logout', { refreshToken: revokeToken }, { silent: true }).catch(() => {})
        }
        const { resetBusinessStores } = await import('./session.js')
        await resetBusinessStores({ remoteCleanup })
      } finally {
        _clearCredentials()
        logoutPromise = null
      }
    })()

    return logoutPromise
  }

  function getAccessToken() {
    return accessToken.value
  }

  /** 启动时用 refresh 同步角色与有效会话；仅认证失效才清凭据，网络抖动保留会话 */
  async function ensureSession() {
    if (!refreshToken.value) {
      if (accessToken.value) _clearCredentials()
      return false
    }
    try {
      await refresh()
      return true
    } catch (err) {
      // 只有 401（refresh 确实失效）才清凭据；网络/5xx 等瞬时错误保留 token，
      // 避免后端重启或断网时把可恢复的会话强制登出。
      if (err?.response?.status === 401 || err?.status === 401) {
        _clearCredentials()
      }
      return false
    }
  }

  return {
    accessToken,
    refreshToken,
    user,
    isLoggedIn,
    isAdmin,
    login,
    refresh,
    logout,
    getAccessToken,
    ensureSession,
  }
})
