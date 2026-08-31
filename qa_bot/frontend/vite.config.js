import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    host: '127.0.0.1',
    // 反向代理：把 /api 转发到 FastAPI 后端，避免跨域
    proxy: {
      '/api': { target: 'http://39.96.63.42/qa', changeOrigin: true }
    }
  }
})
