// workflow store 测试：停用模板下 pendingRun 的恢复/取消/终态回退语义
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  delete: vi.fn(),
  fetchStream: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/utils/http.js', () => ({
  default: {
    get: mocks.get,
    delete: mocks.delete,
  },
  fetchStream: mocks.fetchStream,
}))

vi.mock('@/stores/app.js', () => ({
  useAppStore: () => ({
    toast: { error: mocks.toastError },
  }),
}))

import { useWorkflowStore } from '@/stores/workflow.js'

const pendingRun = {
  threadId: 'wf-thread-1',
  workflowId: 'weekly_report',
}

async function restoreDisabledPausedRun(store) {
  localStorage.setItem('wm_workflow_pending_run', JSON.stringify(pendingRun))
  mocks.get.mockImplementation(async (url) => {
    if (url === '/workflow/templates') return { templates: [] }
    return {
      run: {
        ...pendingRun,
        status: 'paused',
        intermediates: [{ key: 'highlights', label: '工作亮点', value: '完成上线' }],
      },
    }
  })

  await store.loadTemplates()
  return store.restorePendingRun()
}

describe('workflow disabled-template recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    mocks.delete.mockResolvedValue({ success: true })
  })

  it('keeps built-in runtime metadata so an accepted disabled run can resume and finish', async () => {
    const store = useWorkflowStore()

    await expect(restoreDisabledPausedRun(store)).resolves.toBe(true)
    expect(store.templates).toEqual([])
    expect(store.selectedTemplate).toBe('weekly_report')
    expect(store.getTemplateMeta('weekly_report')?.title).toBe('周报生成')
    expect(store.nodeStates.human_review).toBe('waiting')

    mocks.fetchStream.mockImplementation(async (url, body, handlers) => {
      expect(url).toBe('/api/workflow/resume/stream')
      expect(body).toEqual({ threadId: pendingRun.threadId, feedback: '确认' })
      handlers.onEvent('completed', { result: '最终周报' })
      handlers.onDone()
      return { status: 'done' }
    })

    await store.resumeWorkflow('确认')

    expect(store.result).toBe('最终周报')
    expect(store.currentThreadId).toBe('')
    expect(localStorage.getItem('wm_workflow_pending_run')).toBeNull()

    store.restartWorkflow()
    expect(store.selectedTemplate).toBe('')
    expect(store.result).toBe('')
  })

  it('fully clears selection and pending state when a disabled accepted run is cancelled', async () => {
    const store = useWorkflowStore()
    await restoreDisabledPausedRun(store)

    await expect(store.cancelWorkflow()).resolves.toBe(true)

    expect(mocks.delete).toHaveBeenCalledWith(`/workflow/runs/${pendingRun.threadId}`)
    expect(store.selectedTemplate).toBe('')
    expect(store.currentThreadId).toBe('')
    expect(store.paused).toBe(false)
    expect(localStorage.getItem('wm_workflow_pending_run')).toBeNull()
  })

  it.each(['failed', 'cancelled'])(
    'returns to template selection when a disabled run restores as %s',
    async (status) => {
      const store = useWorkflowStore()
      store.selectedTemplate = 'weekly_report'
      localStorage.setItem('wm_workflow_pending_run', JSON.stringify(pendingRun))
      mocks.get.mockImplementation(async (url) => {
        if (url === '/workflow/templates') return { templates: [] }
        if (status === 'cancelled') {
          const error = new Error('工作流不存在或已过期')
          error.response = { status: 404 }
          throw error
        }
        return {
          run: {
            ...pendingRun,
            status,
            error: '执行失败',
          },
        }
      })

      await store.loadTemplates()
      await expect(store.restorePendingRun()).resolves.toBe(false)

      expect(store.selectedTemplate).toBe('')
      expect(store.currentThreadId).toBe('')
      expect(localStorage.getItem('wm_workflow_pending_run')).toBeNull()
    },
  )

  it('uses a full reset for account-bound workflow state', () => {
    const store = useWorkflowStore()
    store.selectedTemplate = 'weekly_report'
    localStorage.setItem('wm_workflow_pending_run', JSON.stringify(pendingRun))

    store.reset()

    expect(store.selectedTemplate).toBe('')
    expect(store.currentThreadId).toBe('')
    expect(localStorage.getItem('wm_workflow_pending_run')).toBeNull()
  })
})
