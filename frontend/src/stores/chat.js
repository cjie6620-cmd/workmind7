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

  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentId.value) || null
  )

  const messages = computed(() =>
    currentSession.value?.messages || []
  )

  // ── 初始化：从后端加载会话列表 ──────────────────────────────
  async function init() {
    try {
      // 从后端获取会话列表
      const data = await http.get('/chat/sessions')
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
        newSession()
      }
    } catch (err) {
      console.error('加载会话列表失败', err)
      newSession()
    }
  }

  function newSession() {
    const id = `session_${Date.now()}`
    sessions.value.unshift({
      id,
      title: '新对话',
      messages: [],
      createdAt: new Date().toISOString(),
    })
    currentId.value = id
    return id
  }

  async function switchSession(id) {
    if (currentId.value === id) return
    currentId.value = id
    await loadHistory(id)
  }

  async function loadHistory(sessionId) {
    const session = sessions.value.find(s => s.id === sessionId)
    if (!session) return

    try {
      const data = await http.get(`/chat/history/${sessionId}`)
      session.messages = (data.messages || []).map(m => ({
        id: m.id || `msg_${Date.now()}_${Math.random()}`,
        role: m.role,
        content: m.content,
        time: m.createdAt,
      }))
    } catch (err) {
      // 404 说明是新会话或会话已被清除，属于正常情况
      if (err.response?.status !== 404) {
        console.warn('加载历史消息失败', sessionId, err.message)
      }
    }
  }

  async function deleteSession(id) {
    const idx = sessions.value.findIndex(s => s.id === id)
    if (idx === -1) return
    sessions.value.splice(idx, 1)

    // 如果删的是当前会话，切到第一个
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id || null
      if (!currentId.value) newSession()
    }

    // 同步删除服务端会话历史
    try {
      await http.delete(`/chat/sessions/${id}`)
    } catch (err) {
      console.error('删除会话失败', err)
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
    try {
      const data = await http.get('/chat/roles')
      roles.value = data.roles
    } catch {}
  }

  // ── 用户画像 ──────────────────────────────────────────────────
  const profile = ref({})
  const userId  = ref('user-demo')

  async function loadProfile() {
    try {
      const data = await http.get(`/chat/profile/${userId.value}`)
      profile.value = data
    } catch {}
  }

  // ── 发送消息（核心）──────────────────────────────────────────
  const loading = ref(false)

  async function sendMessage(text) {
    if (!text.trim() || loading.value) return
    if (!currentId.value) newSession()

    const session = currentSession.value
    loading.value = true

    // 添加用户消息
    const userMsg = {
      id:      `msg_${Date.now()}`,
      role:    'user',
      content: text,
      time:    new Date().toISOString(),
    }
    session.messages.push(userMsg)
    updateTitle(currentId.value, text)

    // 添加 AI 消息占位（流式填充）
    const aiMsg = {
      id:         `msg_${Date.now() + 1}`,
      role:       'assistant',
      content:    '',
      fromCache:  false,
      streaming:  true,
      time:       new Date().toISOString(),
    }
    session.messages.push(aiMsg)

    // 获取数组中实际的消息对象引用（确保响应式）
    const aiMsgRef = session.messages[session.messages.length - 1]

    await fetchStream(
      '/api/chat/stream',
      {
        message:   text,
        sessionId: currentId.value,
        role:      selectedRole.value,
        userId:    userId.value,
      },
      {
        onToken: (token) => {
          aiMsgRef.content += token
        },
        onEvent: (event, data) => {
          if (event === 'cache_hit') aiMsgRef.fromCache = true
          if (event === 'start')     aiMsgRef.streaming = true
        },
        onDone: (data) => {
          aiMsgRef.streaming = false
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
          aiMsgRef.streaming = false
          aiMsgRef.content   = aiMsgRef.content || '抱歉，出现了一些问题，请重试。'
          appStore.toast.error(err.message || '发送失败')
        },
      }
    )

    loading.value = false
  }

  // 重新生成最后一条 AI 回复
  async function regenerate() {
    const msgs = currentSession.value?.messages || []
    // 找最后一条用户消息
    const lastUser = [...msgs].reverse().find(m => m.role === 'user')
    if (!lastUser) return

    // 移除最后一条 AI 消息
    const lastAiIdx = msgs.length - 1
    if (msgs[lastAiIdx]?.role === 'assistant') {
      msgs.splice(lastAiIdx, 1)
    }

    await sendMessage(lastUser.content)
  }

  // 复制消息内容
  async function copyMessage(content) {
    await navigator.clipboard.writeText(content)
    appStore.toast.success('已复制到剪贴板')
  }

  return {
    sessions, currentId, currentSession, messages,
    selectedRole, roles,
    profile, userId,
    loading,
    init, newSession, switchSession, deleteSession,
    loadRoles, loadProfile,
    sendMessage, regenerate, copyMessage,
  }
})