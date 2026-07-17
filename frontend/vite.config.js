// frontend/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts')) return 'echarts'
          if (
            id.includes('node_modules/marked') ||
            id.includes('node_modules/dompurify') ||
            id.includes('node_modules/highlight.js')
          ) {
            return 'markdown'
          }
          if (id.includes('node_modules/vue') || id.includes('node_modules/@vue')) return 'vue-vendor'
          if (id.includes('node_modules/pinia')) return 'pinia'
        },
      },
    },
  },
  server: {
    port: 5173,
    // 开发时把 /api 请求代理到后端，避免跨域问题
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
      },
    },
  },
})
