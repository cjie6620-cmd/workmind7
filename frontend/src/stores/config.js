// frontend/src/stores/config.js
// 配置中心状态：Agent/Workflow/Prompt 三类配置的列表与删除。
// 创建/更新/启停当前无前端入口（由种子数据与后端接口管理），未实现的操作不预留死代码。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'

export const useConfigStore = defineStore('config', () => {
  const appStore = useAppStore()

  // 按类型缓存最近一次拉取的配置列表
  const configMap = ref({})
  // 状态版本号：reset() 时自增；异步回调用启动时的快照比对，丢弃切换账号后过期的响应
  let stateVersion = 0

  /**
   * 获取指定类型的配置列表
   * @param {'prompt'|'agent'|'workflow'} type
   */
  async function listConfigs(type) {
    const version = stateVersion
    try {
      const data = await http.get(`/configs?type=${type}`)
      if (version !== stateVersion) return []
      configMap.value[type] = data.configs || []
      return configMap.value[type]
    } catch {
      return []
    }
  }

  /** 删除配置 */
  async function deleteConfig(id, configType) {
    try {
      await http.delete(`/configs/${id}`, { silent: true })
      appStore.toast.success('配置已删除')
      if (configType) await listConfigs(configType)
      return true
    } catch (err) {
      appStore.toast.error(err.response?.data?.error?.message || '删除失败')
      return false
    }
  }

  function reset() {
    stateVersion += 1
    configMap.value = {}
  }

  return {
    configMap,
    listConfigs,
    deleteConfig,
    reset,
  }
})
