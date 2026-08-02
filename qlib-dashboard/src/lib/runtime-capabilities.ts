export type RuntimeMode = 'static_artifact' | 'local_artifact' | 'connected_research';

export interface RuntimeCapabilities {
  mode: RuntimeMode;
  readOnly: boolean;
  requiresAuthentication: boolean;
  backendApi: boolean;
  jobs: boolean;
  mutations: boolean;
  localFiles: boolean;
  offlineShell: boolean;
}

const RUNTIME_STORAGE_KEY = 'alpha-engine-runtime-mode';
const VALID_MODES: RuntimeMode[] = ['static_artifact', 'local_artifact', 'connected_research'];

function isRuntimeMode(value: string | null | undefined): value is RuntimeMode {
  return Boolean(value && VALID_MODES.includes(value as RuntimeMode));
}

function detectRuntimeMode(): RuntimeMode {
  const configured = import.meta.env.VITE_RUNTIME_MODE;
  if (isRuntimeMode(configured)) return configured;

  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(RUNTIME_STORAGE_KEY);
    if (isRuntimeMode(stored)) return stored;

    if (window.location.hostname.endsWith('github.io')) {
      return 'static_artifact';
    }
  }

  return 'connected_research';
}

export const runtimeMode = detectRuntimeMode();

export const runtimeCapabilities: RuntimeCapabilities = {
  mode: runtimeMode,
  readOnly: runtimeMode !== 'connected_research',
  requiresAuthentication: runtimeMode === 'connected_research',
  backendApi: runtimeMode === 'connected_research',
  jobs: runtimeMode === 'connected_research',
  mutations: runtimeMode === 'connected_research',
  localFiles: runtimeMode === 'local_artifact',
  offlineShell: runtimeMode !== 'connected_research',
};

export function setPreferredRuntimeMode(mode: RuntimeMode): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(RUNTIME_STORAGE_KEY, mode);
}

export function clearPreferredRuntimeMode(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(RUNTIME_STORAGE_KEY);
}

export function assetUrl(path: string): string {
  const cleanPath = path.replace(/^\/+/, '');
  return new URL(cleanPath, document.baseURI).toString();
}
