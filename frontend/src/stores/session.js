// frontend/src/stores/session.js
// 账号切换/登出时的业务 store 统一复位入口（由 auth.logout 动态 import，避免循环依赖）
import { useAgentStore } from './agent.js'
import { useChatStore } from './chat.js'
import { useConfigStore } from './config.js'
import { useErpStore } from './erp.js'
import { useKnowledgeStore } from './knowledge.js'
import { useMonitorStore } from './monitor.js'
import { usePromptStore } from './prompt.js'
import { useWorkflowStore } from './workflow.js'

/**
 * 统一终止流并清除账号相关状态，防止同一 SPA 中切换账号后残留数据。
 */
export async function resetBusinessStores({ remoteCleanup = true } = {}) {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const erpStore = useErpStore()
  const knowledgeStore = useKnowledgeStore()
  const promptStore = usePromptStore()
  const workflowStore = useWorkflowStore()

  // 先同步中止所有长连接，避免等待远端清理时继续写入旧账号状态。
  agentStore.stopTask()
  chatStore.stopGenerate()
  erpStore.stopApproval()
  knowledgeStore.stopQuery()
  knowledgeStore.stopUpload()
  promptStore.stopStreams()
  workflowStore.stopStream()

  if (remoteCleanup) await workflowStore.cancelWorkflow()
  workflowStore.reset()

  agentStore.reset()
  chatStore.reset()
  erpStore.resetSession()
  knowledgeStore.reset()
  promptStore.reset()
  useConfigStore().reset()
  useMonitorStore().reset()
}
