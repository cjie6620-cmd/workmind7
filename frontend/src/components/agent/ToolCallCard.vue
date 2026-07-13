<!-- frontend/src/components/agent/ToolCallCard.vue -->
<!-- 单次工具调用卡片：工具名、入参、出参、执行时间、状态 -->
<template>
  <div class="tool-card" :class="[step.status, { report: isReport }]">
    <!-- 卡片头部 -->
    <div class="card-header" @click="toggle">
      <div class="left">
        <!-- 状态指示点 -->
        <span class="status-dot" :class="`dot-${step.status}`" />
        <!-- 步骤编号 -->
        <span class="step-num">#{{ step.id }}</span>
        <span class="tool-label">{{ step.label || step.toolName }}</span>
      </div>
      <div class="right">
        <!-- 执行时间 -->
        <span v-if="step.durationMs" class="duration">{{ step.durationMs }}ms</span>
        <!-- 状态标签 -->
        <span class="status-tag" :class="step.status">
          {{ statusText }}
        </span>
        <!-- 展开箭头 -->
        <span class="arrow">{{ expanded ? '▴' : '▾' }}</span>
      </div>
    </div>

    <!-- 展开内容：入参 + 出参 -->
    <Transition name="slide">
      <div v-if="expanded" class="card-body">
        <!-- 入参 -->
        <div v-if="argsText" class="detail-section">
          <div class="section-label">输入参数</div>
          <pre class="code-block args">{{ argsText }}</pre>
        </div>

        <!-- 报告特殊展示 -->
        <div v-if="isReport" class="detail-section report-section">
          <div class="section-header">
            <span class="section-label report-badge">报告已生成</span>
            <button class="btn-download" @click="downloadReport">下载 .md</button>
          </div>
          <div class="report-preview">
            <div class="report-title">{{ step.report.title }}</div>
            <div class="report-body markdown-body" :class="{ collapsed: !showFullReport }" v-html="renderMd(step.report.content)" />
            <button v-if="!showFullReport" class="btn-expand-report" @click="showFullReport = true">展开完整报告 ▾</button>
          </div>
        </div>

        <!-- 出参（非报告工具的执行结果） -->
        <div v-else-if="step.result" class="detail-section">
          <div class="section-label">执行结果</div>
          <pre class="code-block result">{{ resultText }}</pre>
        </div>

        <!-- 执行中：等待动画 -->
        <div v-if="step.status === 'running'" class="loading-row">
          <div class="spinner" />
          <span>正在执行...</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { renderMarkdown } from '@/utils/markdown.js'

const props = defineProps({
  step: { type: Object, required: true },
})

const expanded = ref(false)

watch(() => props.step.status, (s) => { if (s === 'running') expanded.value = true })

const showFullReport = ref(false)

function renderMd(t) {
  return renderMarkdown(t)
}

function toggle() {
  if (props.step.status !== 'running') {
    expanded.value = !expanded.value
  }
}

function downloadReport() {
  const r = props.step.report
  const blob = new Blob([r.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${r.title}.md`
  a.click()
  URL.revokeObjectURL(url)
}

const isReport = computed(() => !!props.step.report)

const statusText = computed(() => ({
  running: '执行中',
  done:    '完成',
  error:   '失败',
}[props.step.status] || props.step.status))

const argsText = computed(() => {
  const args = props.step.args
  if (!args) return ''
  if (typeof args === 'string') return args
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
})

const resultText = computed(() => {
  const r = props.step.result
  if (!r) return ''
  if (typeof r === 'string') {
    try {
      return JSON.stringify(JSON.parse(r), null, 2)
    } catch {
      return r
    }
  }
  try { return JSON.stringify(r, null, 2) }
  catch { return String(r) }
})
</script>

<style scoped>
.tool-card {
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--color-surface);
  transition: all var(--transition);
}

/* 执行中：蓝色边框发光 */
.tool-card.running {
  border-color: var(--color-info);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, .12);
}

/* 完成：绿色边框 */
.tool-card.done {
  border-color: #86efac;
  background: #f0fdf4;
}

/* 卡片头部 */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  background: rgba(0, 0, 0, .015);
}

.left, .right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.step-num {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.tool-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.duration {
  font-size: 10px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.status-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.status-tag.running { background: #dbeafe; color: #1d4ed8; }
.status-tag.done    { background: #dcfce7; color: #166534; }
.status-tag.error   { background: #fee2e2; color: #991b1b; }

.arrow { font-size: 10px; color: var(--color-text-muted); }

/* 卡片内容 */
.card-body {
  padding: 10px 14px;
  border-top: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-section {}

.section-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--color-text-muted);
  margin-bottom: 5px;
}

.code-block {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 8px 10px;
  font-size: 12px;
  font-family: var(--font-mono);
  overflow-x: auto;
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  color: var(--color-text);
}

.code-block.result {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.loading-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-muted);
  padding: 4px 0;
}

/* 展开/收起动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all .25s ease;
  overflow: hidden;
}
.slide-enter-from,
.slide-leave-to {
  max-height: 0;
  opacity: 0;
}
.slide-enter-to,
.slide-leave-from {
  max-height: 500px;
  opacity: 1;
}

/* 报告卡片样式 */
.tool-card.report {
  border-color: #c4b5fd;
  background: #f5f3ff;
}

.report-section {
  background: #faf5ff;
  border: 1px solid #e9d5ff;
  border-radius: var(--radius-md);
  padding: 10px 12px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.report-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  padding: 2px 10px;
  background: #8b5cf6;
  color: #fff;
  border-radius: var(--radius-full);
}

.btn-download {
  padding: 3px 12px;
  font-size: 11px;
  font-weight: 600;
  background: #8b5cf6;
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition);
}
.btn-download:hover { background: #7c3aed; }

.report-preview {
  background: #fff;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
}

.report-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e9d5ff;
}

.report-body {
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text);
}

.report-body.collapsed {
  max-height: 200px;
  overflow: hidden;
  position: relative;
}
.report-body.collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(transparent, #fff);
}

.btn-expand-report {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 5px 0;
  font-size: 11px;
  color: #8b5cf6;
  background: none;
  border: none;
  cursor: pointer;
  font-weight: 600;
}
.btn-expand-report:hover { color: #7c3aed; }

/* 标记正文内的 markdown 样式 */
.markdown-body h1 { font-size: 16px; margin: 8px 0 4px; }
.markdown-body h2 { font-size: 14px; margin: 6px 0 4px; }
.markdown-body p  { margin: 4px 0; }
.markdown-body blockquote { border-left: 3px solid #e9d5ff; padding-left: 10px; color: var(--color-text-muted); margin: 6px 0; }
.markdown-body hr { border: none; border-top: 1px solid #e9d5ff; margin: 8px 0; }
.markdown-body code { background: #f5f3ff; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
.markdown-body pre { background: #1e1b4b; color: #e0e7ff; padding: 8px 12px; border-radius: var(--radius-md); overflow-x: auto; font-size: 12px; }
.markdown-body pre code { background: none; padding: 0; }
</style>
