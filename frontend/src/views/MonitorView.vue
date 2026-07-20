<!-- frontend/src/views/MonitorView.vue -->
<!-- 用量看板（admin）：指标卡/预算编辑/费用与调用图表/近调用明细，10s 轮询后端权威统计 -->
<template>
  <div class="monitor-view">
    <div class="metrics-grid">
      <MetricCard label="今日 API 调用" :value="s.overview?.apiCallsToday ?? 0" :sub="`总计 ${s.overview?.totalCallsToday ?? 0} 次`" color="blue" />
      <MetricCard label="缓存命中率" :value="s.overview?.cacheHitRate ?? '0%'" :sub="`命中 ${s.overview?.cacheHitsToday ?? 0} 次`" color="purple" />
      <MetricCard label="今日费用" :value="`¥${s.overview?.costCNYToday ?? 0}`" :sub="`预算 ¥${s.overview?.dailyBudget ?? 50}`" color="amber" />
      <MetricCard label="平均响应" :value="`${s.latency?.avg ?? 0}ms`" :sub="`P99: ${s.latency?.p99 ?? 0}ms`" color="green" />
    </div>

    <div class="budget-bar-wrap">
      <!-- 模型信息 -->
      <div class="model-info">
        <span class="model-name">{{ s.overview?.model ?? '—' }}</span>
        <span class="model-pricing">输入 ${{ s.overview?.pricing?.input ?? 0.14 }}/M · 输出 ${{ s.overview?.pricing?.output ?? 0.28 }}/M</span>
      </div>

      <!-- Token 预算 -->
      <div class="budget-label">
        <span>Token 使用</span>
        <span class="budget-detail">{{ fmtNum(tokenUsed) }} / {{ fmtNum(s.overview?.tokenBudget ?? 0) }}</span>
        <span class="budget-pct" :class="{ warn: (s.overview?.tokenUsedPct??0) >= 80 }">{{ (s.overview?.tokenUsedPct ?? 0).toFixed(2) }}%</span>
      </div>
      <div class="budget-bar">
        <div class="budget-fill" :style="{ width: Math.min(s.overview?.tokenUsedPct??0, 100) + '%' }" :class="{ warn: (s.overview?.tokenUsedPct??0) >= 80, danger: (s.overview?.tokenUsedPct??0) >= 100 }" />
      </div>

      <!-- 金额预算 -->
      <div class="budget-label" style="margin-top:12px">
        <span>费用使用</span>
        <span class="budget-detail">¥{{ s.overview?.costCNYToday ?? 0 }} / ¥{{ s.overview?.dailyBudget ?? 50 }}</span>
        <span class="budget-pct" :class="{ warn: (s.overview?.budgetUsedPct??0) >= 80 }">{{ (s.overview?.budgetUsedPct ?? 0).toFixed(2) }}%</span>
        <button class="btn-text-xs" @click="showBE = !showBE">修改预算</button>
      </div>
      <div class="budget-bar">
        <div class="budget-fill" :style="{ width: Math.min(s.overview?.budgetUsedPct??0, 100) + '%' }" :class="{ warn: (s.overview?.budgetUsedPct??0) >= 80, danger: (s.overview?.budgetUsedPct??0) >= 100 }" />
      </div>

      <div v-if="showBE" class="budget-edit">
        <input type="number" v-model.number="newBudget" class="input budget-input" min="1" />
        <button class="btn btn-primary btn-xs" @click="updateBudget">保存</button>
        <button class="btn btn-ghost btn-xs" @click="showBE = false">取消</button>
      </div>
    </div>

    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">近 7 日 Token 消耗</div>
        <ECharts :option="tokenChartOption" :height="200" />
      </div>

      <div class="chart-card">
        <div class="chart-title">今日调用分布</div>
        <div v-if="!(s.byFeature?.length)" class="chart-empty">暂无今日数据</div>
        <ECharts v-else :option="featurePieOption" :height="200" />
      </div>

      <div class="chart-card">
        <div class="chart-title">响应时间</div>
        <div class="latency-stats">
          <div class="lat-item" v-for="(val, key) in latencyItems" :key="key">
            <div class="lat-label">{{ key }}</div>
            <div class="lat-value">{{ val }}ms</div>
          </div>
        </div>
      </div>
    </div>

    <div class="table-card">
      <div class="table-header">
        <span class="table-title">最近调用记录</span>
        <div class="table-filters">
          <select v-model="featureFilter" class="input filter-select">
            <option value="">全部功能</option>
            <option v-for="f in featureOptions" :key="f.feature" :value="f.feature">{{ f.label }}</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="loadStats">刷新</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="call-table">
          <thead><tr><th>时间（{{ s.overview?.businessTimezone || '业务时区' }}）</th><th>功能</th><th>输入 T</th><th>输出 T</th><th>费用</th><th>延迟</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-if="!filteredCalls.length"><td colspan="7" class="empty-row">暂无记录，进行操作后刷新</td></tr>
            <tr v-for="(c,i) in filteredCalls" :key="i" :class="{ 'from-cache': c.fromCache }">
              <td class="time-cell">{{ fmtTime(c.time) }}</td>
              <td><span class="feature-tag">{{ featureLabel(c.feature) }}</span></td>
              <td>{{ c.inputT }}</td><td>{{ c.outputT }}</td>
              <td>{{ c.fromCache ? '—' : `¥${c.costCNY}` }}</td>
              <td>{{ c.fromCache ? '—' : `${c.latencyMs}ms` }}</td>
              <td><span :class="c.fromCache ? 'cache-badge' : 'api-badge'">{{ c.fromCache ? '缓存' : 'API' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import http from '@/utils/http.js'
import ECharts from '@/components/common/ECharts.vue'
import { useAppStore } from '@/stores/app.js'
const appStore = useAppStore()
const s = ref({})
const showBE = ref(false)
const newBudget = ref(50)
const featureFilter = ref('')
let pollTimer = null
const featureNames = { chat:'对话助手', knowledge:'RAG 知识库', agent:'任务 Agent', workflow:'内容工作流', erp:'ERP 审批', prompt:'Prompt 调试' }
function featureLabel(f) { return featureNames[f] || f }
async function loadStats() {
  try {
    const d = await http.get('/monitor/stats')
    s.value = d
    newBudget.value = d.overview?.dailyBudget ?? 50
  } catch (err) {
    console.warn('加载监控统计失败', err.message)
  }
}
async function updateBudget() {
  try {
    await http.put('/monitor/budget', { dailyBudget: newBudget.value }, { silent: true })
    await loadStats()
    showBE.value = false
    appStore.toast.success('预算已更新')
  } catch (err) {
    appStore.toast.error(err.response?.data?.error?.message || '预算更新失败')
  }
}
// ── ECharts 图表配置 ──────────────────────────────────────────────
const CHART_COLORS = ['#6366f1', '#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

const tokenChartOption = computed(() => {
  const days = s.value.last7Days || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        let tip = params[0].axisValueLabel
        params.forEach(p => { tip += `<br/>${p.marker} ${p.seriesName}: ${p.value.toLocaleString()}` })
        return tip
      },
    },
    legend: { data: ['输入 Tokens', '输出 Tokens'], top: 0, textStyle: { fontSize: 11, color: '#64748b' } },
    grid: { left: 50, right: 16, top: 30, bottom: 16 },
    xAxis: { type: 'category', data: days.map(d => d.label), axisLabel: { fontSize: 10, color: '#94a3b8' } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#f1f5f9' } } },
    series: [
      { name: '输入 Tokens', type: 'bar', data: days.map(d => d.inputT), itemStyle: { color: CHART_COLORS[0] }, barMaxWidth: 24 },
      { name: '输出 Tokens', type: 'bar', data: days.map(d => d.outputT), itemStyle: { color: CHART_COLORS[1] }, barMaxWidth: 24 },
    ],
  }
})

const featurePieOption = computed(() => {
  const features = s.value.byFeature || []
  if (!features.length) return {}
  return {
    tooltip: {
      trigger: 'item',
      formatter(p) { return `${p.name}: ${p.value} 次<br/>¥${features.find(f => f.label === p.name)?.costCNY ?? 0}` },
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      data: features.map((f, i) => ({ name: f.label, value: f.calls, itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] } })),
      label: { fontSize: 11, formatter: '{b}\n{d}%', color: '#475569' },
      labelLine: { length: 8, length2: 12 },
    }],
  }
})
const latencyItems = computed(() => ({ P50: s.value.latency?.p50??0, P90: s.value.latency?.p90??0, P99: s.value.latency?.p99??0, AVG: s.value.latency?.avg??0 }))
const tokenUsed = computed(() => (s.value.overview?.tokenInputToday ?? 0) + (s.value.overview?.tokenOutputToday ?? 0))
function fmtNum(n) { return n == null ? '0' : n.toLocaleString() }
const filteredCalls = computed(() => { const c = s.value.recentCalls||[]; return featureFilter.value ? c.filter(x=>x.feature===featureFilter.value) : c })
const featureOptions = computed(() => [...new Set((s.value.recentCalls||[]).map(c=>c.feature))].map(f=>({ feature:f, label:featureLabel(f) })))
function fmtTime(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: s.value.overview?.businessTimezone || 'Asia/Shanghai',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(new Date(iso))
}
onMounted(() => { loadStats(); pollTimer = setInterval(loadStats, 10000) })
onUnmounted(() => clearInterval(pollTimer))
</script>
<script>
import { h } from 'vue'

// 用渲染函数而非 template 字符串：生产 runtime-only 构建不含模板编译器，
// template 字符串组件会渲染为空白并告警。
const MetricCard = {
  props: ['label', 'value', 'sub', 'color'],
  render() {
    return h('div', { class: ['metric-card', `color-${this.color}`] }, [
      h('div', { class: 'metric-value' }, this.value),
      h('div', { class: 'metric-label' }, this.label),
      h('div', { class: 'metric-sub' }, this.sub),
    ])
  },
}
export default { components: { MetricCard } }
</script>
<style scoped>
.monitor-view { height:100%; overflow-y:auto; padding:var(--space-lg) var(--space-xl); display:flex; flex-direction:column; gap:var(--space-lg); background:var(--color-bg); }
.metrics-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:var(--space-md); }
.metric-card { background:var(--color-surface); border:1px solid var(--color-border); border-radius:var(--radius-lg); padding:var(--space-md) var(--space-lg); }
.color-blue   { border-top:3px solid var(--color-info); }
.color-purple { border-top:3px solid var(--color-primary); }
.color-amber  { border-top:3px solid var(--color-warning); }
.color-green  { border-top:3px solid var(--color-success); }
.metric-value { font-size:24px; font-weight:800; color:var(--color-text); line-height:1.2; }
.metric-label { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; color:var(--color-text-muted); margin-top:4px; }
.metric-sub { font-size:11px; color:var(--color-text-muted); margin-top:2px; }
.budget-bar-wrap { background:var(--color-surface); border:1px solid var(--color-border); border-radius:var(--radius-lg); padding:var(--space-md) var(--space-lg); }
.model-info { display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--color-border-light); }
.model-name { font-size:12px; font-weight:700; color:var(--color-primary); background:var(--color-primary-bg); padding:2px 8px; border-radius:var(--radius-full); }
.model-pricing { font-size:10px; color:var(--color-text-muted); }
.budget-label { display:flex; align-items:center; gap:8px; font-size:12px; color:var(--color-text-sub); margin-bottom:8px; }
.budget-detail { font-size:11px; color:var(--color-text-muted); margin-left:auto; }
.budget-pct { font-weight:700; color:var(--color-text); }
.budget-pct.warn { color:var(--color-warning); }
.btn-text-xs { font-size:11px; color:var(--color-primary); background:none; border:none; cursor:pointer; margin-left:auto; }
.budget-bar { height:6px; background:var(--color-border); border-radius:var(--radius-full); overflow:hidden; }
.budget-fill { height:100%; background:var(--color-primary); border-radius:var(--radius-full); transition:width .5s; }
.budget-fill.warn { background:var(--color-warning); }
.budget-fill.danger { background:var(--color-danger); }
.budget-edit { display:flex; align-items:center; gap:8px; margin-top:10px; }
.budget-input { width:100px; padding:5px 8px; }
.btn-xs { padding:4px 10px; font-size:11px; }
.charts-row { display:grid; grid-template-columns:2fr 1.5fr 1fr; gap:var(--space-md); }
.chart-card { background:var(--color-surface); border:1px solid var(--color-border); border-radius:var(--radius-lg); padding:var(--space-lg); }
.chart-title { font-size:12px; font-weight:600; color:var(--color-text); margin-bottom:var(--space-md); }
.chart-empty { font-size:12px; color:var(--color-text-muted); text-align:center; padding:24px 0; }
.latency-stats { display:grid; grid-template-columns:1fr 1fr; gap:var(--space-sm); }
.lat-item { text-align:center; padding:10px 6px; background:var(--color-bg); border-radius:var(--radius-md); border:1px solid var(--color-border-light); }
.lat-label { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--color-text-muted); }
.lat-value { font-size:18px; font-weight:800; color:var(--color-text); margin:4px 0; }
.table-card { background:var(--color-surface); border:1px solid var(--color-border); border-radius:var(--radius-lg); overflow:hidden; }
.table-header { display:flex; align-items:center; justify-content:space-between; padding:var(--space-md) var(--space-lg); border-bottom:1px solid var(--color-border-light); }
.table-title { font-size:13px; font-weight:600; color:var(--color-text); }
.table-filters { display:flex; gap:var(--space-sm); }
.filter-select { padding:5px 10px; font-size:12px; }
.btn-sm { padding:5px 12px; font-size:12px; }
.table-wrap { overflow-x:auto; }
.call-table { width:100%; border-collapse:collapse; font-size:12px; }
.call-table th { padding:8px 16px; background:var(--color-bg); font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; color:var(--color-text-muted); text-align:left; border-bottom:1px solid var(--color-border); }
.call-table td { padding:8px 16px; border-bottom:1px solid var(--color-border-light); color:var(--color-text-sub); }
.call-table tr.from-cache td { opacity:.7; }
.call-table tr:hover td { background:var(--color-border-light); }
.empty-row { text-align:center; color:var(--color-text-muted); padding:24px !important; }
.time-cell { font-family:var(--font-mono); color:var(--color-text-muted); }
.feature-tag { font-size:10px; padding:2px 7px; background:var(--color-primary-bg); color:var(--color-primary); border-radius:var(--radius-full); }
.cache-badge { font-size:10px; padding:2px 7px; background:#ede9fe; color:#6d28d9; border-radius:var(--radius-full); }
.api-badge { font-size:10px; padding:2px 7px; background:var(--color-border-light); color:var(--color-text-muted); border-radius:var(--radius-full); }
</style>
