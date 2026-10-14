import { rmSync } from 'node:fs'
import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { loadEnv, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

// The app is served by FastAPI under /app (MODULES.md §5). In development,
// VITE_MOCK=0 sends /api to the agent's own backend; anything else (the
// default) answers /api from the MSW mocks in src/api/mocks/.

const DEV_PORT = 9511
const DEFAULT_BACKEND = 'http://127.0.0.1:9510'

// The mock Service Worker lives in public/ so the dev server can serve it,
// but it must never ship: drop it from the production bundle.
function dropMockWorker(): Plugin {
  let outDir = 'dist'
  return {
    name: 'drop-mock-worker',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir)
    },
    closeBundle() {
      rmSync(resolve(outDir, 'mockServiceWorker.js'), { force: true })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const useMocks = env.VITE_MOCK !== '0'
  const backend = env.VITE_BACKEND || DEFAULT_BACKEND

  return {
    base: '/app/',
    plugins: [react(), dropMockWorker()],
    server: {
      host: '127.0.0.1',
      port: DEV_PORT,
      strictPort: true,
      proxy: useMocks ? undefined : { '/api': { target: backend } },
    },
    preview: { host: '127.0.0.1', port: DEV_PORT, strictPort: true },
    build: {
      rolldownOptions: {
        output: {
          // The libraries change rarely; keep them in their own cached files.
          codeSplitting: {
            groups: [
              { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
              { name: 'antd', test: /node_modules[\\/](antd|@ant-design|@rc-component|rc-[^\\/]+|dayjs)[\\/]/ },
              { name: 'vendor', test: /node_modules[\\/]/ },
            ],
          },
        },
      },
      // antd alone is about 800 kB minified (about 250 kB compressed).
      chunkSizeWarningLimit: 1000,
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
      testTimeout: 15000,
    },
  }
})
