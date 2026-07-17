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

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem(TOKEN_KEY) || '')
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) || '')
  const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))
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
    if (!remoteCleanup) _clearCredentials()

    logoutPromise = (async () => {
      try {
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

  /** 启动时用 refresh 同步角色与有效会话，失败则清凭据 */
  async function ensureSession() {
    if (!refreshToken.value) {
      if (accessToken.value) _clearCredentials()
      return false
    }
    try {
      await refresh()
      return true
    } catch {
      _clearCredentials()
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
