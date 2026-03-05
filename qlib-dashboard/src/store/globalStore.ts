import { create } from 'zustand';

interface GlobalState {
    theme: "dark" | "light";
    setTheme: (theme: "dark" | "light") => void;

    sidebarCollapsed: boolean;
    setSidebarCollapsed: (col: boolean) => void;

    qualityWarnings: string[];
    setQualityWarnings: (warnings: string[]) => void;

    latestCalendarDay: string;
    setLatestCalendarDay: (day: string) => void;

    qualityStatus: "ok" | "warning" | "error";
    setQualityStatus: (status: "ok" | "warning" | "error") => void;

    activeJobsCount: number;
    setActiveJobsCount: (count: number) => void;
}

export const useGlobalStore = create<GlobalState>((set) => ({
    theme: "dark",
    setTheme: (t) => set({ theme: t }),

    sidebarCollapsed: false,
    setSidebarCollapsed: (col) => set({ sidebarCollapsed: col }),

    qualityWarnings: [],
    setQualityWarnings: (warnings) => set({ qualityWarnings: warnings }),

    latestCalendarDay: "",
    setLatestCalendarDay: (day) => set({ latestCalendarDay: day }),

    qualityStatus: "ok",
    setQualityStatus: (status) => set({ qualityStatus: status }),

    activeJobsCount: 0,
    setActiveJobsCount: (count) => set({ activeJobsCount: count }),
}));
