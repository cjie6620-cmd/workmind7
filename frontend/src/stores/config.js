// frontend/src/stores/config.js
// 配置中心状态：统一管理 Agent、Workflow、Prompt 三类配置的 CRUD
import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/utils/http.js'
import { useAppStore } from './app.js'

export const useConfigStore = defineStore('config', () => {
  const appStore = useAppStore()

  // 按类型缓存配置列表
  const configMap = ref({})

  /**
   * 获取指定类型的配置列表
   * @param {'prompt'|'agent'|'workflow'} type
   */
  async function listConfigs(type) {
    try {
      const data = await http.get(`/configs?type=${type}`)
      configMap.value[type] = data.configs || []
      return configMap.value[type]
    } catch {
      return []
    }
  }

  /** 获取单条配置 */
  async function getConfig(id) {
    try {
      return await http.get(`/configs/${id}`)
    } catch {
      return null
    }
  }

  /** 创建配置 */
  async function createConfig(configType, name, configJson) {
    try {
      const data = await http.post('/configs', { configType, name, configJson })
      appStore.toast.success('配置已创建')
      await listConfigs(configType)
      return data.config
    } catch (err) {
      appStore.toast.error(err.response?.data?.error?.message || '创建失败')
      return null
    }
  }

  /** 更新配置 */
  async function updateConfig(id, { name, configJson } = {}) {
    try {
      const payload = {}
      if (name !== undefined) payload.name = name
      if (configJson !== undefined) payload.configJson = configJson
      const data = await http.put(`/configs/${id}`, payload)
      appStore.toast.success('配置已更新')
      return data.config
    } catch (err) {
      appStore.toast.error(err.response?.data?.error?.message || '更新失败')
      return null
    }
  }

  /** 删除配置 */
  async function deleteConfig(id, configType) {
    try {
      await http.delete(`/configs/${id}`)
      appStore.toast.success('配置已删除')
      if (configType) await listConfigs(configType)
      return true
    } catch (err) {
      appStore.toast.error(err.response?.data?.error?.message || '删除失败')
      return false
    }
  }

  /** 切换启用/停用 */
  async function toggleActive(id, active) {
    try {
      const endpoint = active ? `/configs/${id}/activate` : `/configs/${id}/deactivate`
      const data = await http.post(endpoint)
      return data.config
    } catch (err) {
      appStore.toast.error('操作失败')
      return null
    }
  }

  return {
    configMap,
    listConfigs, getConfig,
    createConfig, updateConfig, deleteConfig,
    toggleActive,
  }
})
