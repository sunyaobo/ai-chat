import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5176,
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://39.96.63.42/enterprise', changeOrigin: true }
    }
  }
})
