import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    hmr: {
      clientPort: 5173,
    },
    watch: {
      usePolling: true, // Windows에서 파일 감지 문제 해결
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
        // HTTPS 백엔드면 secure: false 추가 검토
      },
      // '/ws': {
      //   target: 'ws://localhost:8000',
      //   ws: true,
      //   changeOrigin: true,
      //   // 필요한 경우 rewrite: (p) => p  또는 (p)=>p.replace(/^\/ws/,'/assistant/ws')
      // },
    },
  },
})
