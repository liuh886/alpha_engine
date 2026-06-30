import { create } from 'zustand';

// ---------------------------------------------------------------------------
// sessionStorage helpers for lightweight persistence
// (localStorage is blocked in sandboxed iframes; sessionStorage is not)
// ---------------------------------------------------------------------------
function readSession<T>(key: string, fallback: T): T {
    try {
        const raw = sessionStorage.getItem(key);
        if (raw === null) return fallback;
        return JSON.parse(raw) as T;
    } catch {
        return fallback;
    }
}

function writeSession(key: string, value: unknown): void {
    try {
        sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
        // Ignore unavailable sessionStorage in sandboxed or non-browser contexts.
    }
}

interface GlobalState {
    theme: 'dark' | 'light';
    setTheme: (theme: 'dark' | 'light') => void;

    /** When true, internal routes are visible in the sidebar. */
    operatorMode: boolean;
    setOperatorMode: (on: boolean) => void;

    sidebarCollapsed: boolean;
    setSidebarCollapsed: (col: boolean) => void;

    qualityWarnings: string[];
    setQualityWarnings: (warnings: string[]) => void;

    latestCalendarDay: string;
    setLatestCalendarDay: (day: string) => void;

    qualityStatus: 'ok' | 'warning' | 'error';
    setQualityStatus: (status: 'ok' | 'warning' | 'error') => void;

    activeJobsCount: number;
    setActiveJobsCount: (count: number) => void;

    dataGeneratedAt: string;
    setDataGeneratedAt: (ts: string) => void;

    apiError: string | null;
    setApiError: (err: string | null) => void;

    username: string;
    setUsername: (name: string) => void;

    // Model selection (shared across pages)
    selectedModelId: string;
    setSelectedModelId: (id: string) => void;
    selectedModelMarket: string;
    setSelectedModelMarket: (market: string) => void;

    demoMode: boolean;
    setDemoMode: (demo: boolean) => void;
}

export const useGlobalStore = create<GlobalState>((set) => ({
    theme: 'light',
    setTheme: (t) => set({ theme: t }),

    // operatorMode: persisted in sessionStorage so refresh doesn't reset it
    operatorMode: readSession<boolean>('operatorMode', false),
    setOperatorMode: (on) => {
        writeSession('operatorMode', on);
        set({ operatorMode: on });
    },

    // sidebarCollapsed: persisted in sessionStorage
    sidebarCollapsed: readSession<boolean>('sidebarCollapsed', false),
    setSidebarCollapsed: (col) => {
        writeSession('sidebarCollapsed', col);
        set({ sidebarCollapsed: col });
    },

    qualityWarnings: [],
    setQualityWarnings: (warnings) => set({ qualityWarnings: warnings }),

    latestCalendarDay: '',
    setLatestCalendarDay: (day) => set({ latestCalendarDay: day }),

    qualityStatus: 'ok',
    setQualityStatus: (status) => set({ qualityStatus: status }),

    activeJobsCount: 0,
    setActiveJobsCount: (count) => set({ activeJobsCount: count }),

    dataGeneratedAt: '',
    setDataGeneratedAt: (ts) => set({ dataGeneratedAt: ts }),

    apiError: null,
    setApiError: (err) => set({ apiError: err }),

    username: 'User',
    setUsername: (name) => set({ username: name }),

    // Model selection
    selectedModelId: '',
    setSelectedModelId: (id) => set({ selectedModelId: id }),
    selectedModelMarket: 'us',
    setSelectedModelMarket: (market) => set({ selectedModelMarket: market }),

    demoMode: false,
    setDemoMode: (demo) => set({ demoMode: demo }),
}));
