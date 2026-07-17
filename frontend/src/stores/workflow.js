// frontend/src/stores/workflow.js
// 工作流模块状态：模板选择、节点执行状态、人工审核、结果
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { fetchStream } from '@/utils/http.js'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'

export const useWorkflowStore = defineStore('workflow', () => {
  const appStore = useAppStore()

  // ── 模板列表（默认值保证始终可见）────────────────────────
  const templates = ref([
    {
      id: 'weekly_report', title: '周报生成', icon: '📊',
      desc: '输入本周工作要点，自动提炼亮点、识别风险，生成规范周报',
      inputLabel: '本周工作要点', inputPlaceholder: '请简单描述本周完成的主要工作，一条一行...',
      extraField: { key: 'dept', label: '部门名称', placeholder: '如：前端研发组' },
      nodes: [
        { id: 'extract_highlights', label: '提炼工作亮点' },
        { id: 'identify_risks',     label: '识别风险阻塞' },
        { id: 'human_review',       label: '人工审核', isHuman: true },
        { id: 'generate_report',    label: '生成周报' },
      ],
      resultKey: 'report',
    },
    {
      id: 'meeting_minutes', title: '会议纪要', icon: '📝',
      desc: '粘贴会议原始记录，自动提取结论和 Action Items，生成正式纪要',
      inputLabel: '会议原始记录', inputPlaceholder: '粘贴会议记录，包括讨论内容、发言摘要等...',
      extraField: { key: 'meeting_title', label: '会议名称', placeholder: '如：产品周会 2024-03' },
      nodes: [
        { id: 'extract_attendees',   label: '提取参会人与议题' },
        { id: 'extract_conclusions', label: '提取会议结论' },
        { id: 'extract_actions',     label: '整理 Action Items' },
        { id: 'human_review',        label: '人工审核', isHuman: true },
        { id: 'generate_minutes',    label: '生成纪要' },
      ],
      resultKey: 'minutes',
    },
    {
      id: 'email_polish', title: '邮件润色', icon: '✉️',
      desc: '输入邮件草稿，AI 分析语气和问题，润色成正式邮件',
      inputLabel: '邮件草稿', inputPlaceholder: '粘贴你的邮件草稿...',
      extraField: { key: 'recipient', label: '收件人/场景', placeholder: '如：客户、上级、合作方' },
      nodes: [
        { id: 'analyze_intent', label: '分析写作意图' },
        { id: 'check_issues',   label: '检查问题' },
        { id: 'human_review',   label: '人工审核', isHuman: true },
        { id: 'polish_email',   label: '生成润色版本' },
      ],
      resultKey: 'polished',
    },
    {
      id: 'prd_skeleton', title: 'PRD 骨架', icon: '📋',
      desc: '输入需求描述，自动提取功能点和约束，生成结构化 PRD 文档',
      inputLabel: '需求描述', inputPlaceholder: '用自然语言描述你的产品需求...',
      nodes: [
        { id: 'extract_features',     label: '提取功能点' },
        { id: 'identify_constraints', label: '识别约束条件' },
        { id: 'human_review',         label: '人工审核', isHuman: true },
        { id: 'generate_prd',         label: '生成 PRD' },
      ],
      resultKey: 'prd',
    },
  ])

  // 配置中心只返回当前可启动的模板；已受理任务仍需使用受版本控制的内置元数据收尾。
  const builtInTemplates = templates.value.map(template => ({
    ...template,
    nodes: template.nodes.map(node => ({ ...node })),
  }))

  function getTemplateMeta(id) {
    return templates.value.find(template => template.id === id)
      || builtInTemplates.find(template => template.id === id)
      || null
  }

  async function loadTemplates() {
    const version = stateVersion
    try {
      const data = await http.get('/workflow/templates')
      if (version !== stateVersion) return
      if (Array.isArray(data.templates)) templates.value = data.templates
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载工作流模板失败', err.message)
    }
  }

  // ── 当前工作流运行状态 ─────────────────────────────────────
  // selectedTemplate：当前选择的模板 id
  const selectedTemplate = ref('')
  // nodeStates：{ [nodeId]: 'idle' | 'running' | 'done' | 'waiting' }
  const nodeStates  = reactive({})
  // nodeOutputs：{ [nodeId]: '节点输出预览文本' }
  const nodeOutputs = reactive({})
  // running：工作流是否正在执行
  const running  = ref(false)
  // paused：是否暂停在 human_review
  const paused   = ref(false)
  // currentThreadId：当前工作流的线程 ID（恢复时用）
  const currentThreadId = ref('')
  // intermediates：暂停时的中间产物（供人工审核查看）
  const intermediates = ref([])
  // result：最终生成的内容
  const result   = ref('')
  // streamBuffer：最后一个节点流式输出的累积内容
  const streamBuffer = ref('')
  const PENDING_RUN_KEY = 'wm_workflow_pending_run'
  let abortController = null
  let pendingPollTimer = null
  let stateVersion = 0

  function initializeNodeStates() {
    for (const key of Object.keys(nodeStates)) delete nodeStates[key]
    for (const key of Object.keys(nodeOutputs)) delete nodeOutputs[key]

    const templateMeta = getTemplateMeta(selectedTemplate.value)
    templateMeta?.nodes.forEach((node) => {
      nodeStates[node.id] = 'idle'
      nodeOutputs[node.id] = ''
    })
  }

  function clearPendingRun() {
    localStorage.removeItem(PENDING_RUN_KEY)
    if (pendingPollTimer) {
      clearTimeout(pendingPollTimer)
      pendingPollTimer = null
    }
  }

  function persistPendingRun() {
    if (!currentThreadId.value || !selectedTemplate.value) return
    localStorage.setItem(PENDING_RUN_KEY, JSON.stringify({
      threadId: currentThreadId.value,
      workflowId: selectedTemplate.value,
    }))
  }

  // ── 重置状态 ────────────────────────────────────────────────
  function resetRunState({ clearSelection = false } = {}) {
    stateVersion += 1
    stopStream()
    if (clearSelection) selectedTemplate.value = ''
    initializeNodeStates()
    running.value       = false
    paused.value        = false
    currentThreadId.value = ''
    intermediates.value = []
    result.value        = ''
    streamBuffer.value  = ''
    clearPendingRun()
  }

  // 完整重置用于退出登录、取消任务等边界，不能把上一个账号/已停用模板的选择遗留在 SPA 中。
  function reset() {
    resetRunState({ clearSelection: true })
  }

  function restartWorkflow() {
    const activeTemplateId = templates.value.some(t => t.id === selectedTemplate.value)
      ? selectedTemplate.value
      : ''
    reset()
    if (activeTemplateId) {
      selectedTemplate.value = activeTemplateId
      initializeNodeStates()
    }
  }

  async function selectTemplate(id) {
    if (currentThreadId.value) {
      if (!await cancelWorkflow()) return false
    } else {
      reset()
    }
    selectedTemplate.value = id
    initializeNodeStates()
    return true
  }

  // ── 启动工作流 ─────────────────────────────────────────────
  async function startWorkflow(input) {
    if (running.value) return
    if (!selectedTemplate.value) return
    resetRunState()
    running.value = true
    const controller = new AbortController()
    abortController = controller
    const version = stateVersion

    await fetchStream(
      '/api/workflow/start/stream',
      { workflowId: selectedTemplate.value, input },
      {
        signal: controller.signal,
        onEvent: (event, data) => {
          if (version !== stateVersion) return
          if (event === 'start') {
            currentThreadId.value = data.threadId
            persistPendingRun()
          }

          if (event === 'node_start') {
            nodeStates[data.nodeId] = 'running'
          }

          if (event === 'node_done') {
            nodeStates[data.nodeId] = 'done'
            if (data.preview) nodeOutputs[data.nodeId] = data.preview
          }

          if (event === 'paused') {
            // 到达 human_review，工作流暂停
            currentThreadId.value   = data.threadId
            intermediates.value     = data.intermediates || []
            paused.value            = true
            running.value           = false
            // 把 human_review 节点标记为 waiting
            nodeStates['human_review'] = 'waiting'
            persistPendingRun()
          }

          if (event === 'completed') {
            result.value  = data.result
            running.value = false
            currentThreadId.value = ''
            clearPendingRun()
          }
        },
        onDone: () => {
          if (version !== stateVersion) return
          running.value = false
        },
        onError: (err) => {
          if (version !== stateVersion) return
          running.value = false
          appStore.toast.error(err.message || '工作流执行失败')
        },
      }
    )

    if (abortController === controller) abortController = null
  }

  // ── 恢复工作流（注入人工反馈后继续）──────────────────────
  async function resumeWorkflow(feedback = '') {
    if (!currentThreadId.value || running.value) return
    running.value = true
    paused.value  = false
    nodeStates['human_review'] = 'done'
    streamBuffer.value = ''
    const controller = new AbortController()
    abortController = controller
    const version = stateVersion

    await fetchStream(
      '/api/workflow/resume/stream',
      { threadId: currentThreadId.value, feedback },
      {
        signal: controller.signal,
        onToken: (token) => {
          if (version !== stateVersion) return
          streamBuffer.value += token
        },
        onEvent: (event, data) => {
          if (version !== stateVersion) return
          if (event === 'node_start') {
            nodeStates[data.nodeId] = 'running'
          }
          if (event === 'node_done') {
            nodeStates[data.nodeId] = 'done'
          }
          if (event === 'completed') {
            result.value       = data.result || streamBuffer.value
            streamBuffer.value = ''
            running.value      = false
            currentThreadId.value = ''
            clearPendingRun()
          }
          if (event === 'paused') {
            currentThreadId.value = data.threadId || currentThreadId.value
            intermediates.value = data.intermediates || []
            paused.value = true
            running.value = false
            nodeStates.human_review = 'waiting'
            persistPendingRun()
          }
        },
        onDone: () => {
          if (version !== stateVersion) return
          if (!paused.value && streamBuffer.value && !result.value) {
            result.value = streamBuffer.value
          }
          running.value = false
        },
        onError: (err) => {
          if (version !== stateVersion) return
          running.value = false
          if (err.status === 404) {
            currentThreadId.value = ''
            paused.value = false
            clearPendingRun()
          } else {
            paused.value = true
            nodeStates.human_review = 'waiting'
            persistPendingRun()
          }
          appStore.toast.error(err.message || '恢复失败')
        },
      }
    )

    if (abortController === controller) abortController = null
  }

  function stopStream() {
    abortController?.abort()
    abortController = null
    running.value = false
    clearPendingRun()
  }

  async function cancelWorkflow() {
    const threadId = currentThreadId.value
    stopStream()

    if (threadId) {
      try {
        await http.delete(`/workflow/runs/${threadId}`)
      } catch (err) {
        if (err.response?.status !== 404) {
          return false
        }
      }
    }

    reset()
    return true
  }

  async function restorePendingRun() {
    const version = stateVersion
    const raw = localStorage.getItem(PENDING_RUN_KEY)
    if (!raw) return false

    let pending
    try {
      pending = JSON.parse(raw)
    } catch {
      clearPendingRun()
      return false
    }

    if (!pending?.threadId) {
      clearPendingRun()
      return false
    }

    try {
      const data = await http.get(`/workflow/runs/${pending.threadId}`)
      if (version !== stateVersion) return false
      const run = data.run || data
      selectedTemplate.value = run.workflowId || pending.workflowId
      initializeNodeStates()

      if (run.status === 'completed') {
        result.value = run.result || ''
        currentThreadId.value = ''
        paused.value = false
        running.value = false
        clearPendingRun()
        return true
      }

      if (run.status === 'running') {
        currentThreadId.value = run.threadId
        paused.value = false
        running.value = true
        persistPendingRun()
        pendingPollTimer = setTimeout(() => {
          pendingPollTimer = null
          if (version === stateVersion) restorePendingRun()
        }, 1500)
        return true
      }

      if (run.status !== 'paused') {
        const errorMessage = run.status === 'failed'
          ? run.error || '工作流执行失败，请重新启动'
          : ''
        // 终态只保留仍可再次启动的模板；停用模板必须回到选择页。
        restartWorkflow()
        if (run.status === 'failed') {
          appStore.toast.error(errorMessage)
        }
        return false
      }

      currentThreadId.value = run.threadId
      intermediates.value = run.intermediates || []
      paused.value = true
      running.value = false

      const nodes = getTemplateMeta(selectedTemplate.value)?.nodes || []
      const reviewIndex = nodes.findIndex(node => node.id === 'human_review')
      nodes.forEach((node, index) => {
        nodeStates[node.id] = index < reviewIndex ? 'done' : 'idle'
      })
      if (reviewIndex >= 0) nodeStates.human_review = 'waiting'
      persistPendingRun()
      return true
    } catch (err) {
      if (version !== stateVersion) return false
      if (err.response?.status === 404) restartWorkflow()
      else appStore.toast.error(err.message || '恢复待审核工作流失败')
      return false
    }
  }

  return {
    templates, selectedTemplate,
    nodeStates, nodeOutputs, running, paused,
    currentThreadId, intermediates, result, streamBuffer,
    loadTemplates, getTemplateMeta, selectTemplate, startWorkflow, resumeWorkflow,
    restorePendingRun, cancelWorkflow, restartWorkflow, stopStream, reset,
  }
})
