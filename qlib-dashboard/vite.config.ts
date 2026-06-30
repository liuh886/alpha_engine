import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from "vite-plugin-singlefile"
import path from "path"
import { execSync } from "child_process"

try {
  process.env.VITE_GIT_COMMIT_SHA = execSync('git rev-parse --short HEAD').toString().trim();
} catch (e) {
  process.env.VITE_GIT_COMMIT_SHA = 'unknown';
}

// Inject version from package.json so VITE_APP_VERSION is always in sync
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const pkg = require('./package.json') as { version: string };
  process.env.VITE_APP_VERSION = pkg.version;
} catch (e) {
  process.env.VITE_APP_VERSION = 'unknown';
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/artifacts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
