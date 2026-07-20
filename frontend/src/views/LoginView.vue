<!-- frontend/src/views/LoginView.vue -->
<!-- 登录页：用户名密码表单（el-form 校验），成功后按 redirect 参数回跳原页面 -->
<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <div class="logo">🧠</div>
        <h1>Mr.Chen AI</h1>
        <p>智能办公助手 · 内网登录</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <div data-testid="login-username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              prefix-icon="User"
              autocomplete="username"
            />
          </div>
        </el-form-item>
        <el-form-item prop="password">
          <div data-testid="login-password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              prefix-icon="Lock"
              show-password
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            />
          </div>
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="login-btn"
          data-testid="login-submit"
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>

      <p class="login-hint">默认账号见 server-py/.env.example</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import { useAppStore } from '@/stores/app.js'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const appStore = useAppStore()

const loading = ref(false)
const formRef = ref(null)
const form = reactive({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    appStore.toast.success('登录成功')
    const redirect = route.query.redirect || '/chat'
    router.replace(redirect)
  } catch (err) {
    appStore.toast.error(err.response?.data?.error?.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2937 0%, #4f46e5 100%);
  padding: var(--space-lg);
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-2xl) var(--space-xl);
  box-shadow: var(--shadow-lg);
}

.login-header {
  text-align: center;
  margin-bottom: var(--space-xl);
}

.logo {
  font-size: 48px;
  margin-bottom: var(--space-sm);
}

.login-header h1 {
  font-size: 24px;
  color: var(--color-text);
  margin-bottom: var(--space-xs);
}

.login-header p {
  color: var(--color-text-sub);
  font-size: 14px;
}

.login-btn {
  width: 100%;
  margin-top: var(--space-sm);
}

.login-hint {
  margin-top: var(--space-lg);
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
