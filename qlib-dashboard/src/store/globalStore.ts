import { create } from 'zustand';

function readSession<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeSession(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Session persistence is optional in sandboxed and non-browser contexts.
  }
}

interface GlobalState {
  theme: 'dark' | 'light';
  setTheme: (theme: 'dark' | 'light') => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  dataGeneratedAt: string;
  setDataGeneratedAt: (timestamp: string) => void;
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
}

export const useGlobalStore = create<GlobalState>((set) => ({
  theme: readSession<'dark' | 'light'>('theme', 'light'),
  setTheme: (theme) => {
    writeSession('theme', theme);
    set({ theme });
  },
  sidebarCollapsed: readSession<boolean>('sidebarCollapsed', false),
  setSidebarCollapsed: (sidebarCollapsed) => {
    writeSession('sidebarCollapsed', sidebarCollapsed);
    set({ sidebarCollapsed });
  },
  dataGeneratedAt: '',
  setDataGeneratedAt: (dataGeneratedAt) => set({ dataGeneratedAt }),
  selectedModelId: '',
  setSelectedModelId: (selectedModelId) => set({ selectedModelId }),
}));
