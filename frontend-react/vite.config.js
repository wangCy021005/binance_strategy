import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 本地开发时代理到 Flask API
    proxy: {
      '/api': 'http://localhost:5555',
    },
  },
})
