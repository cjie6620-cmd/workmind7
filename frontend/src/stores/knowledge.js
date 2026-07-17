// frontend/src/stores/knowledge.js
// 知识库模块状态：文档列表、上传、问答
import { defineStore } from 'pinia'
import { ref } from 'vue'
import http, { fetchStream } from '@/utils/http.js'
import { useAppStore } from './app.js'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const appStore = useAppStore()

  // ── 文档管理 ───────────────────────────────────────────────
  const documents     = ref([])
  const categories    = ref([])
  const uploading     = ref(false)
  const uploadProgress = ref(0)  // 0-100
  let uploadController = null
  let stateVersion = 0

  async function loadDocuments(category = '') {
    const version = stateVersion
    try {
      const params = category ? `?category=${category}` : ''
      const data = await http.get(`/knowledge/documents${params}`)
      if (version !== stateVersion) return
      documents.value = data.documents
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      appStore.toast.error(err.response?.data?.error?.message || '加载文档失败')
    }
  }

  async function loadCategories() {
    const version = stateVersion
    try {
      const data = await http.get('/knowledge/categories')
      if (version !== stateVersion) return
      categories.value = data.categories
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      appStore.toast.error(err.response?.data?.error?.message || '加载分类失败')
    }
  }

  // 上传文件
  async function uploadFile(file, { title, category }) {
    uploading.value = true
    uploadProgress.value = 0

    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', title || file.name.replace(/\.[^.]+$/, ''))
    formData.append('category', category || '通用')

    const controller = new AbortController()
    const version = stateVersion
    uploadController = controller

    try {
      const result = await http.post('/knowledge/documents', formData, {
        signal: controller.signal,
        timeout: 120000,
        onUploadProgress: (event) => {
          if (event.total) {
            uploadProgress.value = Math.round((event.loaded / event.total) * 80)
          }
        },
      })
      if (version !== stateVersion) return null

      uploadProgress.value = 100
      await loadDocuments()
      await loadCategories()
      appStore.toast.success(`「${result.document.title}」已成功入库，共 ${result.document.chunks} 个片段`)
      return result.document
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return null
      appStore.toast.error(err.message || '上传失败')
      throw err
    } finally {
      if (uploadController === controller) {
        uploadController = null
        uploading.value = false
        uploadProgress.value = 0
      }
    }
  }

  // 上传纯文本内容
  async function uploadText({ title, category, content }) {
    uploading.value = true
    const controller = new AbortController()
    const version = stateVersion
    uploadController = controller
    try {
      const data = await http.post(
        '/knowledge/documents',
        { title, category, content },
        { signal: controller.signal, timeout: 120000 },
      )
      if (version !== stateVersion) return null
      await loadDocuments()
      await loadCategories()
      appStore.toast.success(`「${data.document.title}」已成功入库`)
      return data.document
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return null
      appStore.toast.error('入库失败：' + (err.message || '未知错误'))
      throw err
    } finally {
      if (uploadController === controller) {
        uploadController = null
        uploading.value = false
      }
    }
  }

  async function deleteDocument(docId) {
    const version = stateVersion
    const doc = documents.value.find(d => d.id === docId)
    try {
      await http.delete(`/knowledge/documents/${docId}`)
      if (version !== stateVersion) return false
      documents.value = documents.value.filter(d => d.id !== docId)
      appStore.toast.success(`「${doc?.title}」已删除`)
      return true
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return false
      appStore.toast.error(err.message || '删除文档失败')
      return false
    }
  }

  // ── RAG 问答 ───────────────────────────────────────────────
  const messages     = ref([])   // 问答历史
  const querying     = ref(false)
  const filterCategory = ref('')
  const sessionId    = ref('')   // 当前会话 ID
  let queryController = null

  let msgId = 0

  // 页面加载时恢复历史
  async function initSession() {
    const version = stateVersion
    const sid = localStorage.getItem('kn_session_id')
    if (sid) {
      try {
        const data = await http.get(`/knowledge/history/${sid}`)
        if (version !== stateVersion) return
        if (data.messages?.length) {
          sessionId.value = sid
          messages.value = data.messages.map(m => ({
            id: ++msgId,
            role: m.role,
            content: m.content,
            time: m.createdAt,
            ...(m.role === 'assistant' && m.metadata?.sources
              ? { sources: normalizeSources(m.metadata.sources) }
              : {}),
          }))
          return
        }
      } catch {
        if (version !== stateVersion) return
      }
    }
    // 没有历史或加载失败，用新的 sessionId
    newSession()
  }

  function newSession() {
    stopQuery()
    msgId = 0
    sessionId.value = ''
    messages.value = []
    localStorage.removeItem('kn_session_id')
  }

  async function query(question) {
    if (!question.trim() || querying.value) return
    querying.value = true

    messages.value.push({
      id:   ++msgId,
      role: 'user',
      content: question,
      time: new Date().toISOString(),
    })

    const aiMsg = {
      id:       ++msgId,
      role:     'assistant',
      content:  '',
      sources:  [],
      status:   '正在检索相关文档...',
      streaming: true,
    }
    messages.value.push(aiMsg)

    const controller = new AbortController()
    const version = stateVersion
    queryController = controller

    await fetchStream(
      '/api/knowledge/query/stream',
      { question, category: filterCategory.value || undefined, sessionId: sessionId.value || undefined },
      {
        signal: controller.signal,
        onToken: (token) => {
          if (version !== stateVersion) return
          aiMsg.content += token
          aiMsg.status = ''
        },
        onEvent: (event, data) => {
          if (version !== stateVersion) return
          if (event === 'sources') {
            aiMsg.sources = normalizeSources(data.sources)
          }
          if (event === 'status') {
            aiMsg.status = data.message
          }
        },
        onDone: (data) => {
          if (version !== stateVersion) return
          aiMsg.streaming = false
          aiMsg.status = ''
          if (data.sessionId) {
            sessionId.value = data.sessionId
            localStorage.setItem('kn_session_id', data.sessionId)
          }
        },
        onError: (err) => {
          if (version !== stateVersion) return
          aiMsg.streaming = false
          aiMsg.status = ''
          aiMsg.content = aiMsg.content || '查询失败，请重试。'
          appStore.toast.error(err.message)
        },
      }
    )

    if (queryController === controller) {
      queryController = null
      querying.value = false
    }
  }

  function clearMessages() {
    newSession()
  }

  function stopQuery() {
    queryController?.abort()
    queryController = null
    querying.value = false
    const lastMessage = messages.value[messages.value.length - 1]
    if (lastMessage?.streaming) {
      lastMessage.streaming = false
      lastMessage.status = ''
    }
  }

  function stopUpload() {
    uploadController?.abort()
    uploadController = null
    uploading.value = false
    uploadProgress.value = 0
  }

  function reset() {
    stateVersion += 1
    stopQuery()
    stopUpload()
    documents.value = []
    categories.value = []
    filterCategory.value = ''
    messages.value = []
    sessionId.value = ''
    msgId = 0
    localStorage.removeItem('kn_session_id')
  }

  return {
    documents, categories, uploading, uploadProgress,
    messages, querying, filterCategory, sessionId,
    loadDocuments, loadCategories,
    uploadFile, uploadText, deleteDocument,
    query, clearMessages, initSession, newSession,
    stopQuery, stopUpload, reset,
  }
})

function normalizeSources(sources = []) {
  return sources.map((source) => ({
    ...source,
    score: source.score
      ?? source.rerank_score
      ?? source.vector_score
      ?? source.similarity
      ?? null,
  }))
}
