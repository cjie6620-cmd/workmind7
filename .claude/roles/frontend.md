> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Frontend 规范（Vue3 + Vite + AI 聊天 UI 定制）

> 适用场景：Python RAG/Agent 项目的 Web 前端，重点支持 AI 聊天界面、SSE 流式消息、Markdown 渲染。
>
> 与 [backend-fastapi.md](backend-fastapi.md)（SSE 协议）/ [agent.md](agent.md)（消息事件类型）协同。

---

## 技术栈（必须遵守）

| 组件 | 版本 | 说明 | 不用 |
|------|------|------|------|
| **框架** | Vue 3.4+ | Composition API + `<script setup>` | ❌ Vue 2 / Options API |
| **语言** | TypeScript 5.4+ | 严格模式 `strict: true` | ❌ JavaScript |
| **构建** | Vite 5+ | 秒级 HMR | ❌ Webpack |
| **包管理** | pnpm 9+ | 高效、节省磁盘 | ❌ npm / yarn |
| **状态管理** | Pinia 2.2+ | 替代 Vuex | ❌ Vuex |
| **路由** | Vue Router 4.4+ | 组合式 API | — |
| **UI 组件** | Ant Design Vue 4+ | 企业级 | ❌ Element Plus / Naive UI |
| **样式** | TailwindCSS 3.4+ | 原子化 | ❌ SCSS 大量嵌套 |
| **HTTP** | ofetch 1.4+ | Fetch 封装、自动 JSON | ❌ axios（无类型推断） |
| **SSE** | @microsoft/fetch-event-source 1.1+ | 流式 fetch | ❌ 原生 EventSource（不支持 POST） |
| **Markdown** | markdown-it 14+ + highlight.js 11+ | 渲染 LLM 输出 | — |
| **代码高亮** | Shiki 1.x | 主题美观，体积可控 | — |
| **图标** | @ant-design/icons-vue | 与 UI 一致 | — |
| **测试** | Vitest 2+ + Vue Test Utils 2+ | 与 Vite 同源 | ❌ Jest |
| **E2E** | Playwright 1.45+ | 跨浏览器 | — |
| **代码规范** | ESLint 9+ + Prettier 3+ | — | — |

---

## 避坑清单

按严重程度排序：

### 🔴 致命

1. **禁止在生产直接渲染 LLM 返回的 HTML** → XSS 风险，**必须**用 markdown-it + DOMPurify 过滤
2. **禁止 SSE 断连无重连** → 用户网络抖动即丢失回复
3. **禁止 markdown 渲染不过滤 script 标签** → LLM 可能在生成内容里嵌入 `<script>`
4. **禁止 localStorage 存 JWT** → XSS 可窃取，**必须** httpOnly cookie 或内存
5. **禁止 API Key 出现在前端代码** → 任何 token 都必须后端代理

### 🟠 严重

6. **禁止流式消息累积不节流** → DOM 频繁更新卡顿，**必须**用 `requestAnimationFrame` 或 100ms 节流
7. **禁止 SSE 连接不取消** → 切换页面/会话后旧连接继续推送，**必须**用 AbortController
8. **禁止引用不存在的组件路径** → 拼写错误
9. **禁止 Pinia store 直接修改 props** → 状态污染
10. **禁止 Tailwind class 超长字符串** → 单行可读性差，**必须** 拆为 `@apply`

### 🟡 重要

11. **禁止组件 > 500 行** → 必须拆分
12. **禁止模板里写复杂表达式** → 抽到 computed
13. **禁止不用 `shallowRef` / `shallowReactive` 包裹大对象** → 深响应式性能差
14. **禁止路由懒加载不用动态 import** → 首屏加载慢
15. **禁止表单提交不用 `e.preventDefault()`** → 页面刷新

---

## 开发命令

```bash
# 项目初始化
pnpm create vite my-app --template vue-ts
cd my-app
pnpm add pinia vue-router ant-design-vue ofetch @microsoft/fetch-event-source markdown-it highlight.js dompurify @vueuse/core

# 开发
pnpm dev

# 构建
pnpm build

# 预览构建产物
pnpm preview

# 测试
pnpm test
pnpm test:unit
pnpm test:e2e

# 代码质量
pnpm lint
pnpm format
pnpm type-check  # vue-tsc
```

---

## 项目结构

```
my-app/
├── src/
│   ├── main.ts                   # 入口
│   ├── App.vue
│   ├── api/                      # API 客户端
│   │   ├── chat.ts               # 流式对话
│   │   ├── document.ts
│   │   └── http.ts               # ofetch 封装
│   ├── sse/                      # SSE 封装
│   │   ├── EventStream.ts
│   │   └── parsers.ts            # 4 类事件解析
│   ├── markdown/                 # Markdown 渲染
│   │   ├── renderer.ts           # markdown-it 配置
│   │   └── highlight.ts          # 代码高亮
│   ├── stores/                   # Pinia
│   │   ├── chat.ts               # 对话状态（流式累积）
│   │   ├── user.ts
│   │   └── document.ts
│   ├── views/                    # 页面
│   │   ├── ChatView.vue          # 聊天主页
│   │   ├── DocumentManageView.vue
│   │   └── LoginView.vue
│   ├── components/
│   │   ├── chat/
│   │   │   ├── MessageList.vue
│   │   │   ├── MessageItem.vue   # 单条消息
│   │   │   ├── MessageInput.vue
│   │   │   ├── ReferenceList.vue # 引用溯源
│   │   │   └── CardRenderer.vue  # [CARD] 事件
│   │   └── common/
│   ├── router/
│   │   └── index.ts
│   ├── types/                    # TS 类型定义
│   │   ├── api.ts                # 与后端 R[T] 对齐
│   │   └── sse.ts                # SSE 事件类型
│   ├── utils/
│   ├── composables/              # 组合式函数
│   │   ├── useChat.ts
│   │   └── useSSE.ts
│   └── assets/
├── tests/
├── public/
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── .env.example
└── package.json
```

---

## 组件规范

### 标准组件模板

```vue
<script setup lang="ts">
// 1. 类型导入
import type { PropType } from 'vue'
import { ref, computed, watch } from 'vue'

// 2. 第三方库
import { useDebounceFn } from '@vueuse/core'

// 3. 内部模块（按 api -> stores -> components -> utils 顺序）
import { useChatStore } from '@/stores/chat'
import { fetchChat } from '@/api/chat'
import MessageItem from './MessageItem.vue'

// 4. Props
interface Props {
  conversationId: string
  model?: string
}
const props = withDefaults(defineProps<Props>(), {
  model: 'deepseek-chat',  // 默认主力：DeepSeek（**禁止使用任何国外模型**）
})

// 5. Emits
const emit = defineEmits<{
  (e: 'message-sent', content: string): void
  (e: 'error', err: Error): void
}>()

// 6. Refs / Reactive
const messages = ref<Message[]>([])
const input = ref('')

// 7. Computed
const isEmpty = computed(() => messages.value.length === 0)

// 8. Watch
watch(() => props.conversationId, () => {
  messages.value = []
})

// 9. Methods
const send = async () => {
  if (!input.value.trim()) return
  // ...
  emit('message-sent', input.value)
}

// 10. Lifecycle
onMounted(() => { /* ... */ })
</script>

<template>
  <div class="message-list">
    <MessageItem v-for="msg in messages" :key="msg.id" :message="msg" />
  </div>
</template>

<style scoped>
.message-list {
  @apply flex flex-col gap-2 p-4;
}
</style>
```

### 命名规范

| 类型 | 命名 | 示例 |
|------|------|------|
| 组件文件 | PascalCase | `MessageItem.vue` |
| composable | camelCase，以 `use` 开头 | `useChat.ts` |
| store | camelCase，以 `use` 开头 | `useChatStore` |
| 工具函数 | camelCase | `formatDate` |
| 类型/接口 | PascalCase | `MessageItem` |
| 常量 | UPPER_SNAKE | `MAX_MESSAGES` |
| CSS 类（Tailwind） | 原子类直接用 | `flex items-center` |
| 自定义类（@apply） | kebab-case | `.message-item` |

### Props 与 Emits

```vue
<script setup lang="ts">
// ✅ Props 用 interface + withDefaults
interface Props {
  title: string
  count?: number
  items: Item[]
  status: 'pending' | 'success' | 'error'
}
const props = withDefaults(defineProps<Props>(), {
  count: 0,
  status: 'pending',
})

// ✅ Emits 用类型签名
const emit = defineEmits<{
  (e: 'update', value: string): void
  (e: 'delete', id: number): void
}>()
</script>
```

❌ 禁止：
- `defineProps` 不声明类型
- 用 `as any` 绕过类型检查
- Props 名称与事件名称重名

---

## Pinia Store 规范

### chatStore（流式消息累积 — LLM 应用核心）

```typescript
// stores/chat.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, StreamEvent } from '@/types/sse'

export const useChatStore = defineStore('chat', () => {
  // ============ State ============
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const currentAbort = ref<AbortController | null>(null)

  // ============ Getters ============
  const lastMessage = computed(() => messages.value[messages.value.length - 1])
  const totalTokens = computed(() =>
    messages.value.reduce((sum, m) => sum + (m.tokens ?? 0), 0)
  )

  // ============ Actions ============
  function addUserMessage(content: string) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: Date.now(),
    })
  }

  function startAssistantMessage() {
    const msg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      references: [],
      cards: [],
      timestamp: Date.now(),
      isStreaming: true,
    }
    messages.value.push(msg)
    return msg.id
  }

  function appendToken(msgId: string, token: string) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.content += token
    }
  }

  function addReference(msgId: string, ref: Reference) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.references?.push(ref)
    }
  }

  function addCard(msgId: string, card: Card) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.cards?.push(card)
    }
  }

  function finishStreaming(msgId: string) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.isStreaming = false
    }
    isStreaming.value = false
  }

  function cancelStream() {
    currentAbort.value?.abort()
    isStreaming.value = false
  }

  function clear() {
    cancelStream()
    messages.value = []
  }

  return {
    // state
    messages,
    isStreaming,
    currentAbort,
    // getters
    lastMessage,
    totalTokens,
    // actions
    addUserMessage,
    startAssistantMessage,
    appendToken,
    addReference,
    addCard,
    finishStreaming,
    cancelStream,
    clear,
  }
})
```

强制：
- 使用 **Setup Store** 风格（组合式），不用 Options Store
- state 用 `ref`，getters 用 `computed`，actions 直接写函数
- 跨 store 调用用 `useOtherStore()`，**禁止**循环依赖

---

## TypeScript 规范

```json
// tsconfig.json（关键配置）
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

强制：
- 禁止 `any`（必要时用 `unknown` + 类型守卫）
- 禁止 `@ts-ignore`（必要时用 `@ts-expect-error` 并说明原因）
- 所有 API 响应必须有类型定义

---

## API 请求规范

### ofetch 封装

```typescript
// api/http.ts
import { ofetch, type $Fetch } from 'ofetch'

export const http: $Fetch = ofetch.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
  retry: 1,
  onRequest({ options }) {
    const token = localStorage.getItem('access_token')
    if (token) {
      options.headers.set('Authorization', `Bearer ${token}`)
    }
  },
  onResponseError({ response }) {
    if (response.status === 401) {
      // 跳转登录
    }
    if (response.status >= 500) {
      console.error('Server error:', response._data)
    }
  },
})

// 类型必须与后端 R[T] 对齐
export interface R<T> {
  code: number
  message: string
  data: T | null
  trace_id?: string
}
```

---

## SSE 流式消息规范

### SSE 事件类型（与 [agent.md §九](agent.md#九可观测性langfuse-必接) / [backend-fastapi.md §SSE](backend-fastapi.md#sse-流式响应规范) 对齐）

| 事件 | 格式 | 说明 |
|------|------|------|
| `[PROGRESS]` | `data: [PROGRESS]:正在路由您的问题...` | 检索/改写/路由进度 |
| `[REFERENCE]` | `data: [REFERENCE]:[{...}, {...}]` | RAG 引用溯源 |
| `[CARD]` | `data: [CARD]:{"type":"{card_type}","data":{...}}` | 结构化卡片 |
| **Token** | `data: {"token": "..."}` 或纯文本 | LLM 逐字输出 |
| `[DONE]` | `data: [DONE]` | 流结束标记 |
| `[ERROR]` | `data: [ERROR]:message` | 错误 |

### EventSource 封装

```typescript
// sse/EventStream.ts
import { fetchEventSource } from '@microsoft/fetch-event-source'
import type { StreamEvent } from '@/types/sse'

export interface SSEHandlers {
  onProgress?: (msg: string) => void
  onReference?: (refs: Reference[]) => void
  onCard?: (card: Card) => void
  onToken?: (token: string) => void
  onDone?: () => void
  onError?: (err: Error) => void
}

export class EventStream {
  private controller: AbortController | null = null

  start(url: string, body: unknown, handlers: SSEHandlers) {
    this.controller = new AbortController()

    return fetchEventSource(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(body),
      signal: this.controller.signal,
      // 必须：服务端心跳保活
      openWhenHidden: true,

      onmessage(msg) {
        const data = msg.data

        if (data === '[DONE]') {
          handlers.onDone?.()
          return
        }

        if (data.startsWith('[PROGRESS]:')) {
          handlers.onProgress?.(data.slice(11))
        } else if (data.startsWith('[REFERENCE]:')) {
          try {
            handlers.onReference?.(JSON.parse(data.slice(12)))
          } catch (e) {
            console.error('Parse reference failed', e)
          }
        } else if (data.startsWith('[CARD]:')) {
          try {
            handlers.onCard?.(JSON.parse(data.slice(7)))
          } catch (e) {
            console.error('Parse card failed', e)
          }
        } else if (data.startsWith('[ERROR]:')) {
          handlers.onError?.(new Error(data.slice(8)))
        } else {
          // 普通 token
          try {
            const obj = JSON.parse(data)
            handlers.onToken?.(obj.token ?? data)
          } catch {
            handlers.onToken?.(data)
          }
        }
      },

      onerror(err) {
        handlers.onError?.(err)
        throw err  // 触发重连
      },
    })
  }

  cancel() {
    this.controller?.abort()
    this.controller = null
  }
}
```

### useChat composable

```typescript
// composables/useChat.ts
import { ref, onUnmounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { EventStream } from '@/sse/EventStream'

export function useChat() {
  const chatStore = useChatStore()
  const stream = new EventStream()
  const pendingThrottledUpdate = ref<ReturnType<typeof setTimeout> | null>(null)

  // ✅ 强制：节流更新避免 DOM 频繁刷新
  const throttledTokenAppend = (msgId: string, token: string) => {
    if (pendingThrottledUpdate.value) return
    pendingThrottledUpdate.value = setTimeout(() => {
      chatStore.appendToken(msgId, token)
      pendingThrottledUpdate.value = null
    }, 30)  // 30ms 节流
  }

  async function sendMessage(content: string) {
    chatStore.addUserMessage(content)
    const msgId = chatStore.startAssistantMessage()
    chatStore.isStreaming = true

    try {
      await stream.start(
        '/api/v1/chat/stream',
        { message: content, conversationId: 'xxx' },
        {
          onToken: (token) => throttledTokenAppend(msgId, token),
          onReference: (refs) => {
            for (const ref of refs) chatStore.addReference(msgId, ref)
          },
          onCard: (card) => chatStore.addCard(msgId, card),
          onProgress: (msg) => console.log('[progress]', msg),
          onDone: () => chatStore.finishStreaming(msgId),
          onError: (err) => {
            console.error(err)
            chatStore.finishStreaming(msgId)
          },
        }
      )
    } catch (err) {
      console.error(err)
      chatStore.finishStreaming(msgId)
    }
  }

  function cancel() {
    stream.cancel()
    chatStore.cancelStream()
  }

  // ✅ 组件卸载时强制取消，避免内存泄漏
  onUnmounted(() => {
    stream.cancel()
  })

  return { sendMessage, cancel }
}
```

---

## Markdown & 代码高亮规范

```typescript
// markdown/renderer.ts
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'

const md = new MarkdownIt({
  html: false,        // ❌ 禁止渲染 HTML，防 XSS
  linkify: true,
  typographer: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch {}
    }
    return ''
  },
})

/**
 * 渲染 LLM 输出
 * 强制：DOMPurify 必须再次过滤（防 XSS）
 */
export function renderMarkdown(content: string): string {
  const html = md.render(content)
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','ul','ol','li',
                   'strong','em','code','pre','blockquote','a','table',
                   'thead','tbody','tr','th','td','br','hr'],
    ALLOWED_ATTR: ['href','title','class'],
  })
}
```

❌ 禁止：
- `html: true`（LLM 输出可注入 `<script>`）
- 不用 DOMPurify
- 代码块无高亮（用户体验差）

---

## 路由规范

```typescript
// router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),  // ✅ 懒加载
      meta: { requiresAuth: true },
    },
    {
      path: '/chat/:conversationId?',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
  ],
})

// 路由守卫
router.beforeEach((to, from, next) => {
  if (to.meta.requiresAuth && !isAuthenticated()) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else {
    next()
  }
})
```

强制：
- 所有页面组件**必须**懒加载（`() => import(...)`）
- 路由 meta 携带权限信息
- 命名路由用 `name`，不用 path 字符串拼接

---

## TailwindCSS 规范

```javascript
// tailwind.config.js
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: { 50: '#e6f4ff', 500: '#1677ff', 600: '#0958d9' },
      },
    },
  },
  plugins: [],
}
```

强制：
- 优先用 Tailwind 原子类，**禁止**大量写 `<style scoped>`
- 自定义类用 `@apply` 在 `<style>` 中抽取
- 颜色 / 字体 / 间距统一在 `tailwind.config.js` 定义
- 禁止 `!important`（避免时用 `!` 前缀如 `!text-red-500`）

---

## 卡片渲染（CARD 事件）

```vue
<!-- components/chat/CardRenderer.vue -->
<script setup lang="ts">
import type { Card } from '@/types/sse'

interface Props {
  card: Card
}
const props = defineProps<Props>()

// 根据卡片类型动态渲染
const component = computed(() => {
  switch (props.card.type) {
    case '{card_type_1}': return {Type1}Card
    case '{card_type_2}': return {Type2}Card
    case '{card_type_3}': return {Type3}Card
    case '{card_type_4}': return {Type4}Card
    default: return null
  }
})
</script>

<template>
  <component :is="component" v-if="component" v-bind="card.data" />
  <div v-else class="text-red-500">未知卡片类型：{{ card.type }}</div>
</template>
```

---

## 测试规范（Vitest）

```typescript
// tests/components/MessageItem.test.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageItem from '@/components/chat/MessageItem.vue'

describe('MessageItem', () => {
  it('渲染用户消息', () => {
    const wrapper = mount(MessageItem, {
      props: {
        message: { id: '1', role: 'user', content: 'hello', timestamp: Date.now() },
      },
    })
    expect(wrapper.text()).toContain('hello')
  })

  it('渲染助手消息含 Markdown', () => {
    const wrapper = mount(MessageItem, {
      props: {
        message: { id: '2', role: 'assistant', content: '**bold**', timestamp: Date.now() },
      },
    })
    expect(wrapper.html()).toContain('<strong>bold</strong>')
  })
})
```

---

## 性能规范

| 项 | 强制 |
|------|------|
| **路由懒加载** | ✅ 必填 |
| **组件按需引入** | ✅ Ant Design Vue 用 `unplugin-vue-components` |
| **大列表虚拟滚动** | ✅ 超过 100 条用 `vue-virtual-scroller` |
| **图片懒加载** | ✅ `loading="lazy"` |
| **防抖 / 节流** | ✅ 搜索 300ms 防抖，SSE token 30ms 节流 |
| **shallowRef** | ✅ 大对象 / 不可变数据用 shallowRef |
| **v-once / v-memo** | ✅ 静态内容用 |
| **构建分析** | ✅ `rollup-plugin-visualizer` 看包大小 |

---

## 禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **Vue** | ❌ Options API；❌ 不写 `<script setup>`；❌ `ref` / `reactive` 滥用（首选 `ref`） |
| **TS** | ❌ `any` 类型；❌ `@ts-ignore`；❌ 类型断言无依据（`as`） |
| **Pinia** | ❌ Options Store；❌ 跨 store 循环依赖；❌ store 直接修改 props |
| **API** | ❌ axios（用 ofetch）；❌ 业务代码直接 fetch；❌ 错误不统一处理 |
| **样式** | ❌ 内联 style 写大段 CSS；❌ `!important` 滥用；❌ SCSS 大量嵌套 |
| **路由** | ❌ 路由组件同步 import；❌ 不用命名路由 |
| **Markdown** | ❌ `html: true`（XSS）；❌ 不用 DOMPurify 过滤；❌ 直接 `v-html` LLM 输出 |
| **SSE** | ❌ 断连不重连；❌ 切换页面不取消（内存泄漏）；❌ token 累积不节流 |
| **安全** | ❌ localStorage 存 JWT（用 httpOnly cookie）；❌ API Key 暴露前端；❌ dangerouslySetInnerHTML 等价物 |
| **性能** | ❌ 大对象用 `reactive`（用 `shallowRef`）；❌ 静态内容不用 `v-once`；❌ 不分析构建产物 |
| **测试** | ❌ 测试调真实 API；❌ 不写组件测试；❌ 覆盖率 < 60% 阻断合并 |
