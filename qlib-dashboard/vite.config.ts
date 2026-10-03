import { defineConfig, type Plugin } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { execSync } from 'child_process'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'

// One HTML entry and one application chunk are the entire supported contract.
// Inline only generated assets; public evidence and service-worker files keep
// their existing URLs. No glob parser or general-purpose packaging layer.
function inlineApplication(): Plugin {
  return {
    name: 'inline-application',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const entry = bundle['index.html']
      if (!entry || entry.type !== 'asset') throw new Error('Missing application HTML')
      let html = String(entry.source)
      for (const [filename, asset] of Object.entries(bundle)) {
        const escaped = filename.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const original = html
        if (asset.type === 'chunk') {
          const script = new RegExp(`<script([^>]*?) src="\\./${escaped}"([^>]*)></script>`)
          // Vite replaces preload markers after generateBundle. These chunks
          // are removed here, so resolve their now-unneeded preloads first.
          const code = asset.code.replace(/"?__VITE_PRELOAD__"?/g, 'void 0')
            .replace(/<(\/script>|!--)/g, '\\x3C$1')
          html = html.replace(script, (_match, before, after) => `<script${before}${after}>${code}</script>`)
        } else if (filename.endsWith('.css')) {
          const link = new RegExp(`<link[^>]* href="\\./${escaped}"[^>]*>`)
          html = html.replace(link, () => `<style>${String(asset.source)}</style>`)
        } else continue
        if (html === original) throw new Error(`Generated application asset was not inlined: ${filename}`)
        delete bundle[filename]
      }
      entry.source = html
    },
  }
}

try {
  process.env.VITE_GIT_COMMIT_SHA = execSync('git rev-parse --short HEAD').toString().trim()
} catch {
  process.env.VITE_GIT_COMMIT_SHA = 'unknown'
}

// Inject version from package.json so VITE_APP_VERSION is always in sync.
try {
  const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }
  process.env.VITE_APP_VERSION = pkg.version
} catch {
  process.env.VITE_APP_VERSION = 'unknown'
}

// The browser product is artifact-only. Vite's built-in esbuild pipeline
// compiles TSX; the React refresh plugin is not needed for CI or production.
// Relative URLs keep the single-file build, manifest, service worker and
// research bundle valid under the GitHub Pages project sub-path and locally.
export default defineConfig({
  base: './',
  plugins: [tailwindcss(), inlineApplication()],
  build: {
    assetsInlineLimit: () => true,
    assetsDir: '',
    cssCodeSplit: false,
    modulePreload: false,
    rolldownOptions: { output: { codeSplitting: false } },
  },
  resolve: {
    alias: {
      '@': path.resolve(fileURLToPath(new URL('.', import.meta.url)), './src'),
    },
  },
})
