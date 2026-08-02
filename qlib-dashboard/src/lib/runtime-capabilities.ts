export type RuntimeMode = 'static_artifact' | 'local_artifact';

export interface RuntimeCapabilities {
  mode: RuntimeMode;
  readOnly: true;
  requiresAuthentication: false;
  backendApi: false;
  jobs: false;
  mutations: false;
  localFiles: boolean;
  offlineShell: true;
}

const RUNTIME_STORAGE_KEY = 'alpha-engine-runtime-mode';
const VALID_MODES: RuntimeMode[] = ['static_artifact', 'local_artifact'];

function isRuntimeMode(value: string | null | undefined): value is RuntimeMode {
  return Boolean(value && VALID_MODES.includes(value as RuntimeMode));
}

function detectRuntimeMode(): RuntimeMode {
  const configured = import.meta.env.VITE_RUNTIME_MODE;
  if (isRuntimeMode(configured)) return configured;

  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(RUNTIME_STORAGE_KEY);
    if (isRuntimeMode(stored)) return stored;
  }

  return 'static_artifact';
}

export const runtimeMode = detectRuntimeMode();

/**
 * The browser product is permanently read-only. Python CLI commands and
 * scheduled workflows own data refresh, training, backtests and export.
 */
export const runtimeCapabilities: RuntimeCapabilities = {
  mode: runtimeMode,
  readOnly: true,
  requiresAuthentication: false,
  backendApi: false,
  jobs: false,
  mutations: false,
  localFiles: runtimeMode === 'local_artifact',
  offlineShell: true,
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
