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

  async function login(username, password) {
    const data = await http.post('/auth/login', { username, password })
    accessToken.value = data.accessToken
    refreshToken.value = data.refreshToken
    user.value = { userId: data.userId, username, role: data.role }
    _persist()
    return data
  }

  async function refresh() {
    if (!refreshToken.value) {
      throw new Error('无 refresh token')
    }
    const data = await http.post('/auth/refresh', { refreshToken: refreshToken.value })
    accessToken.value = data.accessToken
    refreshToken.value = data.refreshToken
    if (user.value) {
      user.value.role = data.role
      user.value.userId = data.userId
    }
    _persist()
    return data
  }

  function logout() {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    _persist()
  }

  function getAccessToken() {
    return accessToken.value
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
  }
})
