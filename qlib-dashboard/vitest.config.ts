/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import path from 'path'
import { fileURLToPath } from 'url'

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(fileURLToPath(new URL('.', import.meta.url)), './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    exclude: ['e2e/**', 'node_modules/**'],
    // Recharts renders under jsdom are CPU-heavy; 5s is too tight on loaded
    // developer machines even though the assertions themselves are instant.
    testTimeout: 20000,
  },
})
