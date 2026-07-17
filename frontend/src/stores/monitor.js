// frontend/src/stores/monitor.js
// 成本监控 store（第七章完整实现，这里先放基础结构）
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import http from '@/utils/http.js'

export const useMonitorStore = defineStore('monitor', () => {
  const dailyBudget = ref(50)     // ¥50 日预算
  const todaySpend  = ref(0)      // 今日消费（¥）
  const totalCalls  = ref(0)      // 总调用次数
  const cacheHits   = ref(0)      // 缓存命中次数

  // 超过日预算 80% 时触发预警
  const budgetWarning = computed(() => {
    const ratio = todaySpend.value / dailyBudget.value
    if (ratio >= 0.8) {
      return `¥${todaySpend.value.toFixed(2)} / ¥${dailyBudget.value}`
    }
    return null
  })

  let refreshTimer = null

  async function loadStats() {
    try {
      const data = await http.get('/monitor/stats')
      const overview = data.overview || {}
      dailyBudget.value = Number(overview.dailyBudget || 0)
      todaySpend.value = Number(overview.costCNYToday || 0)
      totalCalls.value = Number(overview.totalCallsToday || 0)
      cacheHits.value = Number(overview.cacheHitsToday || 0)
      return data
    } catch {
      return null
    }
  }

  // 价格只由后端统一计算；业务完成后防抖刷新权威监控数据。
  function recordCall() {
    if (refreshTimer) return
    refreshTimer = setTimeout(async () => {
      refreshTimer = null
      await loadStats()
    }, 300)
  }

  function reset() {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = null
    dailyBudget.value = 50
    todaySpend.value = 0
    totalCalls.value = 0
    cacheHits.value = 0
  }

  return {
    dailyBudget, todaySpend, totalCalls, cacheHits,
    budgetWarning, loadStats, recordCall, reset,
  }
})
