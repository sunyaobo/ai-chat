import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5175,
    host: '127.0.0.1',
    // 反向代理：/api 与 /uploads 转发到 FastAPI(8002)，避免跨域
    proxy: {
      '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/uploads': { target: 'http://127.0.0.1:8002', changeOrigin: true }
    }
  }
})
