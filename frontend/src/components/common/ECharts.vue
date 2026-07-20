<!-- frontend/src/components/common/ECharts.vue -->
<!-- ECharts 轻封装：按需注册 Bar/Pie 组件控制包体；option 深监听重绘，卸载时移除监听并 dispose -->
<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>

<script setup>
// chart 实例用 shallowRef：深层响应式代理 ECharts 实例会拖慢渲染且可能破坏内部状态
import { ref, onMounted, onUnmounted, watch, shallowRef } from "vue"
import * as echarts from "echarts/core"
import { BarChart, PieChart } from "echarts/charts"
import { AxisPointerComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([BarChart, PieChart, AxisPointerComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: Number, default: 260 },
})

const chartRef = ref(null)
const chart = shallowRef(null)

function handleResize() {
  chart.value?.resize()
}

onMounted(() => {
  if (chartRef.value) {
    chart.value = echarts.init(chartRef.value)
    if (props.option) {
      chart.value.setOption(props.option)
    }
  }
  window.addEventListener("resize", handleResize)
})

watch(
  () => props.option,
  (opt) => {
    if (chart.value && opt) {
      chart.value.setOption(opt, true)
    }
  },
  { deep: true }
)

onUnmounted(() => {
  window.removeEventListener("resize", handleResize)
  chart.value?.dispose()
  chart.value = null
})
</script>
