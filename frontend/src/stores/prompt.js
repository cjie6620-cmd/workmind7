// frontend/src/stores/prompt.js
// Prompt 调试模块状态：单次测试、A/B 对比、模板管理
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { fetchStream } from '@/utils/http.js'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'

export const usePromptStore = defineStore('prompt', () => {
  const appStore = useAppStore()
  let stateVersion = 0

  // ── 单次测试状态 ────────────────────────────────────────────
  const testConfig = reactive({
    systemPrompt: '',
    userMessage:  '',
    temperature:  0.7,
    maxTokens:    1000,
  })

  const testResult = reactive({
    content:      '',
    streaming:    false,
    latencyMs:    0,
    inputTokens:  0,
    outputTokens: 0,
    totalTokens:  0,
    costCNY:      0,
  })

  const testing = ref(false)
  let testAbortController = null

  async function runTest() {
    if (!testConfig.userMessage.trim() || testing.value) return
    testing.value      = true
    testResult.content  = ''
    testResult.streaming = true

    const startMs = Date.now()
    const controller = new AbortController()
    const version = stateVersion
    testAbortController = controller

    await fetchStream(
      '/api/prompt/test/stream',
      {
        systemPrompt: testConfig.systemPrompt,
        userMessage:  testConfig.userMessage,
        temperature:  testConfig.temperature,
        maxTokens:    testConfig.maxTokens,
      },
      {
        signal: controller.signal,
        onToken: (token) => {
          if (version !== stateVersion) return
          testResult.content += token
        },
        onDone: (data) => {
          if (version !== stateVersion) return
          testResult.latencyMs    = data.latencyMs || (Date.now() - startMs)
          testResult.inputTokens  = data.inputTokens  || 0
          testResult.outputTokens = data.outputTokens || 0
          testResult.totalTokens  = data.totalTokens  || 0
          testResult.costCNY      = data.costCNY || 0
          testResult.streaming = false
          testing.value = false
        },
        onError: (err) => {
          if (version !== stateVersion) return
          testResult.streaming = false
          testing.value = false
          appStore.toast.error(err.message || '测试失败')
        },
      }
    )

    if (testAbortController === controller) {
      testAbortController = null
      testResult.streaming = false
      testing.value = false
    }
  }

  // ── A/B 测试状态 ────────────────────────────────────────────
  const abConfig = reactive({
    question:      '',
    systemPromptA: '',
    systemPromptB: '',
    temperature:   0,
    maxTokens:     800,
  })

  const abResult = reactive({
    answerA:    '',
    answerB:    '',
    evaluation: null,    // { scoreA, scoreB, winner, reason }
    streamingA: false,   // A 侧流式中
    streamingB: false,   // B 侧流式中
    scoring:    false,   // 评分中
    latencyMsA: 0,
    latencyMsB: 0,
  })

  const abTesting = ref(false)
  let abAbortController = null

  async function runAbTest() {
    if (!abConfig.question.trim() || abTesting.value) return
    abTesting.value = true
    abResult.answerA = ''
    abResult.answerB = ''
    abResult.evaluation = null
    abResult.streamingA = true
    abResult.streamingB = true
    abResult.scoring = false
    const controller = new AbortController()
    const version = stateVersion
    abAbortController = controller

    await fetchStream(
      '/api/prompt/ab-test/stream',
      {
        question:      abConfig.question,
        systemPromptA: abConfig.systemPromptA,
        systemPromptB: abConfig.systemPromptB,
        temperature:   abConfig.temperature,
        maxTokens:     abConfig.maxTokens,
      },
      {
        signal: controller.signal,
        onEvent(event, data) {
          if (version !== stateVersion) return
          switch (event) {
            case 'token_a': abResult.answerA += data.token; break
            case 'token_b': abResult.answerB += data.token; break
            case 'done_a':
              abResult.streamingA = false
              abResult.latencyMsA = data.latencyMs || 0
              if (data.error) appStore.toast.error('模型 A 出错：' + data.error)
              break
            case 'done_b':
              abResult.streamingB = false
              abResult.latencyMsB = data.latencyMs || 0
              if (data.error) appStore.toast.error('模型 B 出错：' + data.error)
              break
            case 'scoring':
              abResult.scoring = true
              break
            case 'eval_done':
              abResult.evaluation = data
              abResult.scoring = false
              break
          }
        },
        onDone() {
          if (version !== stateVersion) return
          abResult.streamingA = false
          abResult.streamingB = false
          abResult.scoring = false
          abTesting.value = false
        },
        onError(err) {
          if (version !== stateVersion) return
          abResult.streamingA = false
          abResult.streamingB = false
          abTesting.value = false
          appStore.toast.error(err.message || 'A/B 测试失败')
        },
      }
    )

    if (abAbortController === controller) {
      abAbortController = null
      abResult.streamingA = false
      abResult.streamingB = false
      abResult.scoring = false
      abTesting.value = false
    }
  }

  // ── 模板管理 ────────────────────────────────────────────────
  const templates    = ref([])
  const editingId    = ref('')   // 正在编辑的模板 ID（空=新建）
  const saving       = ref(false)
  const deleting     = ref(false)

  async function loadTemplates() {
    const version = stateVersion
    try {
      const data = await http.get('/prompt/templates')
      if (version !== stateVersion) return
      templates.value = data.templates
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载 Prompt 模板失败', err.message)
    }
  }

  // 把某个模板加载到测试区
  function applyTemplate(template) {
    testConfig.systemPrompt = template.systemPrompt
    appStore.toast.success(`已加载模板「${template.name}」`)
  }

  // 把 A 或 B 区的 Prompt 加载到模板
  function applyAbTemplate(side, template) {
    if (side === 'A') abConfig.systemPromptA = template.systemPrompt
    else              abConfig.systemPromptB = template.systemPrompt
    appStore.toast.success(`已将「${template.name}」加载到 ${side} 区`)
  }

  async function saveTemplate(form) {
    if (saving.value) return false
    saving.value = true
    const version = stateVersion
    try {
      const url = editingId.value
        ? `/prompt/templates/${editingId.value}`
        : '/prompt/templates'
      const method = editingId.value ? 'put' : 'post'
      await http[method](url, form, { silent: true })
      if (version !== stateVersion) return false
      await loadTemplates()
      appStore.toast.success(editingId.value ? '模板已更新' : '模板已保存')
      editingId.value = ''
      return true
    } catch (err) {
      appStore.toast.error(err.message || '保存失败')
      return false
    } finally {
      if (version === stateVersion) saving.value = false
    }
  }

  async function deleteTemplate(id) {
    if (deleting.value) return false
    deleting.value = true
    const version = stateVersion
    try {
      await http.delete(`/prompt/templates/${id}`, { silent: true })
      if (version !== stateVersion) return false
      await loadTemplates()
      appStore.toast.success('模板已删除')
      return true
    } catch (err) {
      appStore.toast.error(err.response?.data?.error?.message || '删除失败')
      return false
    } finally {
      if (version === stateVersion) deleting.value = false
    }
  }

  // 把当前测试的 system prompt 快速另存为模板
  async function saveCurrentAsTemplate(name) {
    if (!testConfig.systemPrompt.trim()) {
      appStore.toast.warning('System Prompt 为空，无法保存')
      return false
    }
    return saveTemplate({ name, systemPrompt: testConfig.systemPrompt })
  }

  function stopStreams() {
    testAbortController?.abort()
    abAbortController?.abort()
    testAbortController = null
    abAbortController = null
    testing.value = false
    testResult.streaming = false
    abTesting.value = false
    abResult.streamingA = false
    abResult.streamingB = false
    abResult.scoring = false
  }

  function reset() {
    stateVersion += 1
    stopStreams()
    Object.assign(testConfig, { systemPrompt: '', userMessage: '', temperature: 0.7, maxTokens: 1000 })
    Object.assign(testResult, {
      content: '', streaming: false, latencyMs: 0,
      inputTokens: 0, outputTokens: 0, totalTokens: 0, costCNY: 0,
    })
    Object.assign(abConfig, {
      question: '', systemPromptA: '', systemPromptB: '', temperature: 0, maxTokens: 800,
    })
    Object.assign(abResult, {
      answerA: '', answerB: '', evaluation: null,
      streamingA: false, streamingB: false, scoring: false,
      latencyMsA: 0, latencyMsB: 0,
    })
    templates.value = []
    editingId.value = ''
    saving.value = false
    deleting.value = false
  }

  return {
    testConfig, testResult, testing,
    abConfig, abResult, abTesting,
    templates, editingId, saving, deleting,
    runTest, runAbTest,
    loadTemplates, applyTemplate, applyAbTemplate,
    saveTemplate, deleteTemplate, saveCurrentAsTemplate,
    stopStreams, reset,
  }
})
