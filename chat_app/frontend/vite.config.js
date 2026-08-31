import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    // 反向代理：把 /api 与 /uploads 转发到 FastAPI，避免跨域与前端拼 host
    proxy: {
      '/api': { target: 'http://39.96.63.42/chat', changeOrigin: true },
      '/uploads': { target: 'http://39.96.63.42/chat', changeOrigin: true }
    }
  }
})
