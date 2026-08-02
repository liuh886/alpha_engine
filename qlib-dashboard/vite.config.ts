import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'
import path from 'path'
import { execSync } from 'child_process'

try {
  process.env.VITE_GIT_COMMIT_SHA = execSync('git rev-parse --short HEAD').toString().trim()
} catch {
  process.env.VITE_GIT_COMMIT_SHA = 'unknown'
}

// Inject version from package.json so VITE_APP_VERSION is always in sync.
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const pkg = require('./package.json') as { version: string }
  process.env.VITE_APP_VERSION = pkg.version
} catch {
  process.env.VITE_APP_VERSION = 'unknown'
}

// The browser product is artifact-only. Relative URLs keep the single-file
// build, manifest, service worker and research bundle valid under the GitHub
// Pages project sub-path and when opened from a local bundle.
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
