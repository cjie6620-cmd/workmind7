// frontend/src/stores/chat.js
// 对话模块全局状态：会话列表、当前会话消息、角色、用户画像
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchStream } from '@/utils/http.js'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'
import { useMonitorStore } from './monitor.js'

export const useChatStore = defineStore('chat', () => {
  const appStore     = useAppStore()
  const monitorStore = useMonitorStore()

  // ── 会话列表 ──────────────────────────────────────────────────
  // 每个会话：{ id, title, messages: [], createdAt }
  const sessions    = ref([])
  const currentId   = ref(null)
  const creatingSession = ref(false)
  let initialized = false
  let stateVersion = 0
  let newSessionPromise = null

  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentId.value) || null
  )

  const messages = computed(() =>
    currentSession.value?.messages || []
  )

  // ── 初始化：从后端加载会话列表 ──────────────────────────────
  async function init() {
    if (initialized) return
    const version = stateVersion
    try {
      // 从后端获取会话列表
      const data = await http.get('/chat/sessions')
      if (version !== stateVersion) return
      if (data.sessions && data.sessions.length > 0) {
        sessions.value = data.sessions.map(s => ({
          id: s.id,
          title: s.title || '新对话',
          messages: [],
          createdAt: s.createdAt,
          messageCount: s.messageCount,
        }))
        // 加载第一个会话的历史消息
        currentId.value = sessions.value[0].id
        await loadHistory(sessions.value[0].id)
      } else {
        await newSession()
      }
      initialized = Boolean(currentId.value)
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.error('加载会话列表失败', err)
      sessions.value = []
      currentId.value = null
      await newSession()
      initialized = Boolean(currentId.value)
    }
  }

  async function newSession() {
    if (newSessionPromise) return newSessionPromise

    stopGenerate()
    creatingSession.value = true
    const version = stateVersion
    let requestPromise
    requestPromise = (async () => {
      try {
        const data = await http.post('/chat/sessions')
        if (version !== stateVersion) return null
        const session = {
          id: data.id,
          title: data.title || '新对话',
          messages: [],
          messageCount: 0,
          createdAt: data.createdAt || new Date().toISOString(),
        }
        sessions.value.unshift(session)
        currentId.value = session.id
        return session.id
      } catch (err) {
        if (version !== stateVersion || err.code === 'ERR_CANCELED') return null
        appStore.toast.error(err.message || '创建会话失败')
        return null
      } finally {
        if (newSessionPromise === requestPromise) {
          creatingSession.value = false
          newSessionPromise = null
        }
      }
    })()
    newSessionPromise = requestPromise

    return newSessionPromise
  }

  async function switchSession(id) {
    if (currentId.value === id) return
    stopGenerate()
    currentId.value = id
    await loadHistory(id)
  }

  async function loadHistory(sessionId) {
    const session = sessions.value.find(s => s.id === sessionId)
    if (!session) return

    const version = stateVersion
    try {
      const data = await http.get(`/chat/history/${sessionId}`)
      if (version !== stateVersion) return
      session.messages = (data.messages || []).map(m => ({
        id: m.id || `msg_${Date.now()}_${Math.random()}`,
        role: m.role,
        content: m.content,
        time: m.createdAt,
        rating: m.metadata?.feedback || null,
        persisted: true,
      }))
      session.messageCount = session.messages.length
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      // 404 说明是新会话或会话已被清除，属于正常情况
      if (err.response?.status !== 404) {
        console.warn('加载历史消息失败', sessionId, err.message)
      }
    }
  }

  async function deleteSession(id) {
    const idx = sessions.value.findIndex(s => s.id === id)
    if (idx === -1) return

    if (currentId.value === id) stopGenerate()

    const version = stateVersion
    try {
      await http.delete(`/chat/sessions/${id}`)
      if (version !== stateVersion) return
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      appStore.toast.error(err.message || '删除会话失败')
      return
    }

    const currentIndex = sessions.value.findIndex(session => session.id === id)
    if (currentIndex !== -1) sessions.value.splice(currentIndex, 1)

    // 如果删的是当前会话，切到第一个
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id || null
      if (currentId.value) await loadHistory(currentId.value)
      else await newSession()
    }
  }

  // 根据第一条消息自动生成会话标题
  function updateTitle(sessionId, firstMessage) {
    const s = sessions.value.find(s => s.id === sessionId)
    if (s && s.title === '新对话') {
      s.title = firstMessage.slice(0, 20) + (firstMessage.length > 20 ? '...' : '')
    }
  }

  // ── 角色 ──────────────────────────────────────────────────────
  const selectedRole = ref('default')
  const roles = ref([])

  async function loadRoles() {
    const version = stateVersion
    try {
      const data = await http.get('/chat/roles')
      if (version !== stateVersion) return
      roles.value = data.roles
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载角色失败', err.message)
    }
  }

  // ── 用户画像 ──────────────────────────────────────────────────
  const profile = ref({})
  const profileClearing = ref(false)

  async function loadProfile() {
    const version = stateVersion
    try {
      const data = await http.get('/chat/profile')
      if (version !== stateVersion) return
      profile.value = data
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载画像失败', err.message)
    }
  }

  async function clearProfile() {
    if (profileClearing.value) return false
    const version = stateVersion
    profileClearing.value = true
    try {
      await http.delete('/chat/profile')
      if (version !== stateVersion) return false
      profile.value = {}
      appStore.toast.success('用户画像已清除')
      return true
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return false
      appStore.toast.error(err.response?.data?.error?.message || '清除画像失败')
      return false
    } finally {
      if (version === stateVersion) profileClearing.value = false
    }
  }

  async function submitFeedback(message, rating) {
    if (!message?.id || !['helpful', 'unhelpful'].includes(rating)) return false
    try {
      const data = await http.post(`/chat/messages/${encodeURIComponent(message.id)}/feedback`, { rating })
      message.rating = data.rating
      return true
    } catch {
      return false
    }
  }

  // ── 发送消息（核心）──────────────────────────────────────────
  const loading = ref(false)
  let abortController = null

  function stopGenerate() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    loading.value = false
    const msgs = currentSession.value?.messages || []
    const lastAi = [...msgs].reverse().find((m) => m.role === 'assistant')
    if (lastAi?.streaming) {
      lastAi.streaming = false
    }
  }

  async function sendMessage(text) {
    if (!text.trim() || loading.value) return
    if (!currentId.value && !await newSession()) return

    const session = currentSession.value
    if (!session) return
    loading.value = true

    // 添加用户消息
    const userMsg = {
      id:      `msg_${Date.now()}`,
      role:    'user',
      content: text,
      time:    new Date().toISOString(),
    }
    session.messages.push(userMsg)
    session.messageCount = session.messages.length
    updateTitle(currentId.value, text)

    // 添加 AI 消息占位（流式填充）
    const aiMsg = {
      id:         `msg_${Date.now() + 1}`,
      role:       'assistant',
      content:    '',
      fromCache:  false,
      streaming:  true,
      persisted:  false,
      time:       new Date().toISOString(),
    }
    session.messages.push(aiMsg)
    session.messageCount = session.messages.length

    // 获取数组中实际的消息对象引用（确保响应式）
    const aiMsgRef = session.messages[session.messages.length - 1]

    const controller = new AbortController()
    abortController = controller
    const version = stateVersion

    await fetchStream(
      '/api/chat/stream',
      {
        message:   text,
        sessionId: currentId.value,
        role:      selectedRole.value,
      },
      {
        signal: controller.signal,
        onToken: (token) => {
          if (version !== stateVersion) return
          aiMsgRef.content += token
        },
        onEvent: (event) => {
          if (version !== stateVersion) return
          if (event === 'cache_hit') aiMsgRef.fromCache = true
          if (event === 'start')     aiMsgRef.streaming = true
        },
        onDone: (data) => {
          if (version !== stateVersion) return
          aiMsgRef.streaming = false
          if (data.assistantMessageId) {
            aiMsgRef.id = data.assistantMessageId
            aiMsgRef.persisted = true
          }
          // 记录用量
          if (!data.fromCache) {
            monitorStore.recordCall({
              inputTokens:  data.inputTokens || 0,
              outputTokens: data.outputTokens || 0,
              fromCache:    false,
              feature:      'chat',
            })
          } else {
            monitorStore.recordCall({ fromCache: true, feature: 'chat' })
          }
          // 刷新画像（后台可能更新了）
          loadProfile()
        },
        onError: (err) => {
          if (version !== stateVersion) return
          aiMsgRef.streaming = false
          aiMsgRef.content   = aiMsgRef.content || '抱歉，出现了一些问题，请重试。'
          appStore.toast.error(err.message || '发送失败')
        },
      }
    )

    if (abortController === controller) {
      loading.value = false
      abortController = null
    }
  }

  // 复制消息内容
  async function copyMessage(content) {
    await navigator.clipboard.writeText(content)
    appStore.toast.success('已复制到剪贴板')
  }

  function reset() {
    stateVersion += 1
    stopGenerate()
    sessions.value = []
    currentId.value = null
    selectedRole.value = 'default'
    roles.value = []
    profile.value = {}
    profileClearing.value = false
    initialized = false
    creatingSession.value = false
    newSessionPromise = null
  }

  return {
    sessions, currentId, currentSession, messages,
    selectedRole, roles,
    profile, profileClearing,
    loading, creatingSession,
    init, newSession, switchSession, deleteSession,
    loadRoles, loadProfile, clearProfile, submitFeedback,
    sendMessage, copyMessage, stopGenerate, reset,
  }
})
