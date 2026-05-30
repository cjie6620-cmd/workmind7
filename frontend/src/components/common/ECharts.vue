<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, shallowRef } from "vue"
import * as echarts from "echarts"

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
