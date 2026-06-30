/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Injected from package.json at build time via vite.config.ts */
  readonly VITE_APP_VERSION: string;
  /** Injected from git rev-parse HEAD at build time via vite.config.ts */
  readonly VITE_GIT_COMMIT_SHA: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
