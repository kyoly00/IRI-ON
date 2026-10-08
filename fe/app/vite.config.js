import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import process from 'node:process'

export default defineConfig(({ mode }) => {
  // process.cwd() 기준으로 .env 파일들의 환경변수를 읽어옵니다.
  const env = loadEnv(mode, process.cwd(), '')

  // Windows/Node 조합에서 IPv6 wildcard(::)가 EFAULT를 일으킬 수 있어 IPv4를 기본값으로 사용한다.
  const host = env.DEV_SERVER_HOST || '127.0.0.1'

  // BACKEND_PROXY_TARGET이 지정되어 있다면 우선 사용하고,
  // 없다면 PC 내부의 기본 백엔드 주소를 사용한다.
  const backendTarget = env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      host,
      port: 5173,
      strictPort: true,
      watch: {
        usePolling: true, // Windows에서 파일 감지 문제 해결
      },
      proxy: {
        '/api': {
          // proxy 요청은 PC 내부에서 백엔드로 가므로 localhost를 유지한다.
          target: backendTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ''),
        },
        '/custom-voice': {
          // 브라우저의 WSS 연결을 PC 내부 Uvicorn WebSocket으로 전달한다.
          target: backendTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
