// frontend/src/stores/erp.js
// ERP 模块状态：表单解析、审批流、申请记录
import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/utils/http.js'
import { useSseTask } from '@/composables/useSseTask.js'
import { useAppStore } from './app.js'

export const useErpStore = defineStore('erp', () => {
  const appStore = useAppStore()

  // ── 当前表单 ──────────────────────────────────────────────
  // 'expense' | 'leave'
  const formType   = ref('expense')
  // 解析出的结构化表单数据
  const parsedForm = ref(null)
  // 解析中
  const parsing    = ref(false)

  // ── 审批流状态 ────────────────────────────────────────────
  // 审批过程中产生的所有消息（对话气泡列表）
  const approvalMessages = ref([])
  // 当前审批流程步骤 [{ roleId, role, status: 'pending'|'running'|'approved'|'rejected' }]
  const approvalSteps    = ref([])
  // 审批是否进行中
  const approving  = ref(false)
  // 最终审批结果
  const finalResult = ref(null)
  // 当前申请编号
  const currentAppId = ref('')
  const approvalRequestId = ref('')
  // 状态版本号：reset() 时自增；异步回调用启动时的快照比对，丢弃切换账号后过期的响应
  let stateVersion = 0
  const approvalTask = useSseTask(() => stateVersion)

  // ── 申请列表 ──────────────────────────────────────────────
  const applications = ref([])

  // ── 解析表单 ──────────────────────────────────────────────
  async function parseForm(text) {
    if (!text.trim() || parsing.value) return

    parsing.value = true
    parsedForm.value = null
    approvalRequestId.value = ''
    const version = stateVersion

    try {
      const data = await http.post('/erp/parse', {
        text,
        formType: formType.value,
      })
      if (version !== stateVersion) return
      parsedForm.value = data.form
      return data.form
    } catch {
      if (version !== stateVersion) return
      appStore.toast.error('解析失败，请重新描述')
    } finally {
      if (version === stateVersion) parsing.value = false
    }
  }

  // ── 提交审批 ──────────────────────────────────────────────
  async function submitApproval(applicantName = '申请人') {
    if (!parsedForm.value || approving.value) return

    approving.value      = true
    approvalMessages.value = []
    approvalSteps.value    = []
    finalResult.value      = null
    // 幂等键：同一份表单重试（网络中断/重复点击）复用同一 requestId，
    // 服务端据此返回已有申请而不重复执行审批；解析新表单时才重新生成
    if (!approvalRequestId.value) approvalRequestId.value = createRequestId()

    await approvalTask.run(
      '/api/erp/submit/stream',
      {
        formData:      parsedForm.value,
        formType:      formType.value,
        applicantName,
        requestId:     approvalRequestId.value,
      },
      {
        onEvent: (event, data) => {
          if (event === 'start') {
            currentAppId.value = data.appId
          }

          // 公布审批流程（需要哪些审批人）
          if (event === 'plan') {
            approvalSteps.value = data.approvers.map(role => ({
              roleId: role.id,
              role,
              status: 'pending',
            }))
          }

          // 某个审批人开始审核
          if (event === 'approver_start') {
            const step = approvalSteps.value.find(s => s.roleId === data.roleId)
            if (step) step.status = 'running'
          }

          // 对话消息（最核心的部分）
          if (event === 'message') {
            approvalMessages.value.push({
              id:       `msg_${Date.now()}_${Math.random()}`,
              from:     data.from,
              role:     data.role,
              content:  data.content,
              type:     data.type,
              time:     new Date().toISOString(),
            })
          }

          // 某个审批人完成
          if (event === 'approver_done') {
            const step = approvalSteps.value.find(s => s.roleId === data.roleId)
            if (step) step.status = data.approved ? 'approved' : 'rejected'
          }

          // 最终结果
          if (event === 'final') {
            finalResult.value = data
            approving.value   = false
            // 刷新申请列表
            loadApplications()
          }

        },
        onDone: () => {
          approving.value = false
        },
        onError: (err) => {
          approving.value = false
          appStore.toast.error(err.message || '审批流程出错')
        },
        onSettled: () => {
          approving.value = false
        },
      }
    )
  }

  // ── 申请记录 ──────────────────────────────────────────────
  async function loadApplications() {
    const version = stateVersion
    try {
      const data = await http.get('/erp/applications')
      if (version !== stateVersion) return
      applications.value = data.applications
    } catch (err) {
      console.warn('加载审批记录失败', err.message)
    }
  }

  // 重置（开始新申请）
  function reset() {
    stopApproval()
    parsedForm.value       = null
    approvalMessages.value = []
    approvalSteps.value    = []
    finalResult.value      = null
    currentAppId.value     = ''
    approvalRequestId.value = ''
  }

  function detachApproval() {
    // 离开页面时只放弃控制权（不 abort）：预审已受理，让流自然跑完，回调受 version 守卫
    approvalTask.detach()
    approving.value = false
  }

  function stopApproval() {
    approvalTask.abort()
    approving.value = false
  }

  function resetSession() {
    stateVersion += 1
    reset()
    applications.value = []
    parsing.value = false
  }

  return {
    formType, parsedForm, parsing,
    approvalMessages, approvalSteps, approving, finalResult, currentAppId,
    approvalRequestId,
    applications,
    parseForm, submitApproval, loadApplications, reset,
    stopApproval, detachApproval, resetSession,
  }
})

function createRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `erp_${Date.now()}_${Math.random().toString(16).slice(2)}`
}
