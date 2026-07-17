// frontend/src/stores/agent.js
// Agent 模块状态：任务历史、工具调用步骤、执行状态
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchStream } from '@/utils/http.js'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'

export const useAgentStore = defineStore('agent', () => {
  const appStore = useAppStore()

  // ── 工具列表（从后端加载，默认值保证始终可见）──────────────
  const toolList = ref([
    { name: 'web_search',   label: '联网搜索', description: '搜索最新技术资讯和信息' },
    { name: 'read_doc',     label: '文档检索', description: '从公司知识库检索文档' },
    { name: 'calculate',    label: '数学计算', description: '金额、工期等数学计算' },
    { name: 'get_date',     label: '日期查询', description: '日期查询和工作日计算' },
    { name: 'write_report', label: '生成报告', description: '生成并保存分析报告' },
    { name: 'send_notify',  label: '发送通知', description: '通知渠道尚未接入', available: false },
  ])

  // ── Agent 配置列表（从数据库加载）──────────────────────────
  const agentConfigs = ref([])
  const selectedConfigId = ref('')
  const activeAgentConfigs = computed(() =>
    agentConfigs.value.filter(config => config.isActive)
  )
  let stateVersion = 0

  async function loadAgentConfigs() {
    const version = stateVersion
    try {
      const data = await http.get('/agent/configs')
      if (version !== stateVersion) return
      agentConfigs.value = data.configs || []
      if (!activeAgentConfigs.value.some(config => config.id === selectedConfigId.value)) {
        selectedConfigId.value = activeAgentConfigs.value[0]?.id || ''
      }
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载 Agent 配置失败', err.message)
    }
  }
  const examples = ref([
    { title: '技术调研', task: '对比 Vue3 和 React 2024年的最新状态，分别查询它们的最新版本和主要特性，生成一份技术选型报告' },
    { title: '费用计算', task: '我出差3天，酒店每晚580元，机票往返1200元，餐费每天150元，帮我计算总报销金额，并查询一下公司差旅报销标准' },
    { title: '工期计算', task: '项目计划从2024年3月1日开始，需要45个工作日完成，帮我计算预计完成日期，并生成一份项目时间轴摘要' },
    { title: '知识查询', task: '从知识库查询公司的年假政策，并计算我今年还剩多少年假（假设今年已用6天，总共15天）' },
  ])

  async function loadMeta() {
    const version = stateVersion
    try {
      const [toolsRes, examplesRes] = await Promise.all([
        http.get('/agent/tools'),
        http.get('/agent/examples'),
      ])
      if (version !== stateVersion) return
      if (toolsRes.tools?.length)     toolList.value = toolsRes.tools
      if (examplesRes.examples?.length) examples.value = examplesRes.examples
    } catch (err) {
      if (version !== stateVersion || err.code === 'ERR_CANCELED') return
      console.warn('加载 Agent 元数据失败', err.message)
    }
    // 并行加载 Agent 配置
    loadAgentConfigs()
  }

  // ── 任务执行历史 ───────────────────────────────────────────
  // 每个任务是一条记录：{ id, task, steps, answer, status, startTime, duration }
  const tasks    = ref([])
  const running  = ref(false)
  const sessionId = ref('')  // 当前会话 ID

  // 当前正在执行的任务状态（实时更新）
  const currentTask = ref(null)
  let abortController = null

  let taskId = 0

  // 页面加载时恢复历史
  async function initSession() {
    const version = stateVersion
    const sid = localStorage.getItem('agent_session_id')
    if (sid) {
      try {
        const data = await http.get(`/agent/history/${sid}`)
        if (version !== stateVersion) return
        if (data.messages?.length) {
          sessionId.value = sid
          // 将历史消息转换为任务记录
          const pairs = []
          const msgs = data.messages
          for (let i = 0; i < msgs.length; i++) {
            if (msgs[i].role === 'user') {
              const answer = msgs[i + 1]?.role === 'assistant' ? msgs[i + 1].content : ''
              pairs.push({ task: msgs[i].content, answer })
            }
          }
          tasks.value = pairs.map((p, idx) => ({
            id: idx + 1,
            task: p.task,
            steps: [],
            answer: p.answer,
            status: 'done',
            startTime: new Date().toISOString(),
            duration: 0,
            reportMeta: null,
          }))
          taskId = pairs.length
          return
        }
      } catch {
        if (version !== stateVersion) return
      }
    }
    newSession()
  }

  function newSession() {
    stopTask()
    taskId = 0
    sessionId.value = ''
    tasks.value = []
    currentTask.value = null
    localStorage.removeItem('agent_session_id')
  }

  // ── 执行任务 ───────────────────────────────────────────────
  async function runTask(taskText) {
    if (!taskText.trim() || running.value) return

    running.value = true
    const id = ++taskId
    const startTime = Date.now()

    // 创建任务记录（先加进列表，实时更新）
    const task = {
      id,
      task:       taskText,
      steps:      [],       // 工具调用步骤数组
      answer:     '',       // 最终回答
      status:     'running',  // running | done | error
      startTime:  new Date().toISOString(),
      duration:   0,
      reportMeta: null,      // 报告元数据（含 id/title/content），用于下载
      configId: selectedConfigId.value || null,
      configName: activeAgentConfigs.value.find(config => config.id === selectedConfigId.value)?.name || '系统默认',
    }

    // unshift 后获取 Vue Proxy 包装后的响应式对象
    tasks.value.unshift(task)
    const rt = tasks.value[0]
    currentTask.value = rt
    const controller = new AbortController()
    abortController = controller
    const version = stateVersion

    await fetchStream(
      '/api/agent/run',
      {
        task: taskText,
        sessionId: sessionId.value || undefined,
        configId: selectedConfigId.value || undefined,
      },
      {
        signal: controller.signal,
        onToken: (token) => {
          if (version !== stateVersion) return
          rt.answer += token
        },

        onEvent: (event, data) => {
          if (version !== stateVersion) return
          if (event === 'start') {
            rt.status = 'running'
            if (data.config) {
              rt.configId = data.config.id
              rt.configName = data.config.name
            }
            // 保存后端返回的 sessionId
            if (data.sessionId) {
              sessionId.value = data.sessionId
              localStorage.setItem('agent_session_id', data.sessionId)
            }
          }

          if (event === 'tool_call') {
            rt.steps.push({
              id:       rt.steps.length + 1,
              toolName: data.toolName,
              label:    data.label,
              args:     data.args,
              result:   null,
              status:   'running',
              startMs:  Date.now(),
            })
          }

          if (event === 'tool_result') {
            const step = [...rt.steps].reverse().find(s => s.toolName === data.toolName && s.status === 'running')
            if (step) {
              step.result    = data.resultText
              step.status    = 'done'
              step.durationMs = Date.now() - step.startMs
              if (data.report) step.report = data.report
            }
            // 报告元数据存储到任务级别（无论是否有匹配的 step）
            if (data.report) rt.reportMeta = data.report
          }

          if (event === 'error') {
            rt.status = 'error'
            rt.answer = rt.answer || data.message || '任务执行失败'
            currentTask.value = null
            appStore.toast.error(data.message || '执行出错')
          }
        },

        onDone: (data) => {
          if (version !== stateVersion) return
          rt.status   = 'done'
          rt.duration = Date.now() - startTime
          if (data.lastReport && !rt.reportMeta) rt.reportMeta = data.lastReport
          currentTask.value = null
        },

        onError: (err) => {
          if (version !== stateVersion) return
          rt.status = 'error'
          rt.answer = rt.answer || '网络错误，请重试'
          currentTask.value = null
          appStore.toast.error(err.message)
        },
      }
    )

    if (abortController === controller) {
      abortController = null
      running.value = false
    }
  }

  function clearTasks() {
    newSession()
  }

  function stopTask() {
    abortController?.abort()
    abortController = null
    running.value = false
    if (currentTask.value?.status === 'running') {
      currentTask.value.status = 'cancelled'
      currentTask.value = null
    }
  }

  function reset() {
    stateVersion += 1
    stopTask()
    tasks.value = []
    currentTask.value = null
    sessionId.value = ''
    agentConfigs.value = []
    selectedConfigId.value = ''
    taskId = 0
    localStorage.removeItem('agent_session_id')
  }

  return {
    toolList, examples, agentConfigs, activeAgentConfigs, selectedConfigId,
    tasks, running, currentTask, sessionId,
    loadMeta, loadAgentConfigs, runTask, clearTasks, initSession, newSession,
    stopTask, reset,
  }
})
