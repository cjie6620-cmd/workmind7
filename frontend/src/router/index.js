// frontend/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: '智能对话', icon: '💬' },
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库', icon: '📚' },
  },
  {
    path: '/agent',
    name: 'Agent',
    component: () => import('@/views/AgentView.vue'),
    meta: { title: '任务 Agent', icon: '🤖' },
  },
  {
    path: '/workflow',
    name: 'Workflow',
    component: () => import('@/views/WorkflowView.vue'),
    meta: { title: '内容工作流', icon: '⚙️' },
  },
  {
    path: '/erp',
    name: 'ERP',
    component: () => import('@/views/ErpView.vue'),
    meta: { title: 'ERP 审批预演（模拟）', icon: '📋' },
  },
  {
    path: '/prompt',
    name: 'Prompt',
    component: () => import('@/views/PromptView.vue'),
    meta: { title: 'Prompt 调试', icon: '🔧', adminOnly: true },
  },
  {
    path: '/monitor',
    name: 'Monitor',
    component: () => import('@/views/MonitorView.vue'),
    meta: { title: '用量看板', icon: '📊', adminOnly: true },
  },
  {
    // 未知路径兜底，避免 SPA 落到空白主区
    path: '/:pathMatch(.*)*',
    redirect: '/chat',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.public) {
    if (to.path === '/login' && authStore.isLoggedIn) {
      next('/chat')
    } else {
      next()
    }
    return
  }

  if (!authStore.isLoggedIn) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  if (to.meta.adminOnly && !authStore.isAdmin) {
    next('/chat')
    return
  }

  next()
})

router.afterEach((to) => {
  document.title = `${to.meta.title || 'Mr.Chen'} — Mr.Chen AI`
})

export default router
