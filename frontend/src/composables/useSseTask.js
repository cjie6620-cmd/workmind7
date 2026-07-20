// frontend/src/composables/useSseTask.js
// SSE 任务骨架组合式：统一各业务 store 重复实现的三件事——
// 1. AbortController 生命周期（创建 → 登记 → 结束时归属判断）
// 2. stateVersion 过期守卫（切换账号/reset 后丢弃迟到的流式回调）
// 3. 收尾语义（仅当本次运行未被 stop/detach/新运行接管时执行 onSettled）
import { fetchStream } from '@/utils/http.js'

/**
 * @param {() => number} getVersion 返回 store 当前 stateVersion 的函数
 */
export function useSseTask(getVersion) {
  let controller = null

  /**
   * 启动一次 SSE 任务。onToken/onEvent/onDone/onError 自动套 version 守卫；
   * onSettled 在流结束且控制权仍归本次运行时调用（用于复位 loading 类标志）。
   */
  async function run(url, body, { onToken, onEvent, onDone, onError, onSettled } = {}) {
    const own = new AbortController()
    controller = own
    const version = getVersion()
    const guard = (fn) => (fn ? (...args) => { if (version === getVersion()) fn(...args) } : undefined)

    await fetchStream(url, body, {
      signal: own.signal,
      onToken: guard(onToken),
      onEvent: guard(onEvent),
      onDone: guard(onDone),
      onError: guard(onError),
    })

    // 归属判断：期间被 abort()/detach()/新 run() 接管时跳过收尾，由接管方负责状态
    if (controller === own) {
      controller = null
      onSettled?.()
    }
  }

  /** 中止当前流（客户端断开连接；服务端已受理任务是否取消由后端语义决定） */
  function abort() {
    controller?.abort()
    controller = null
  }

  /** 放弃控制权但不断开连接（离开页面时保留服务端推送直至自然结束） */
  function detach() {
    controller = null
  }

  return { run, abort, detach }
}
