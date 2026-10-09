import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // Backend the dev server proxies `/api` requests to. Override with
  // VITE_PROXY_TARGET to point at a different backend without editing config.
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss()],
    // `amazon-cognito-identity-js` references the Node `global` object, which
    // does not exist in the browser. Alias it to `globalThis` so the SDK loads
    // instead of throwing "global is not defined" at module init (blank screen).
    define: {
      global: 'globalThis',
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      allowedHosts: ['edc.qingyuan-zhang.com'],
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
