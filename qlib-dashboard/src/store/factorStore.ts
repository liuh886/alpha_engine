import { create } from 'zustand';

interface FactorICResult {
  factor_name: string;
  ic: number;
  rank_ic: number;
  ic_std: number;
  ic_ir: number;
  positive_ic_ratio: number;
  t_stat: number;
}

interface FactorAnalysisReport {
  market: string;
  date_range: string[];
  forward_days: number;
  n_periods: number;
  factors: FactorICResult[];
  top_factors: FactorICResult[];
  generated_at: string;
}

interface DecayPoint {
  lag_days: number;
  ic: number;
}

interface FactorStore {
  market: string;
  report: FactorAnalysisReport | null;
  selectedFactor: string | null;
  decayData: DecayPoint[];
  loading: boolean;
  decayLoading: boolean;
  error: string | null;

  setMarket: (market: string) => void;
  fetchReport: (market: string) => Promise<void>;
  selectFactor: (factor: string) => Promise<void>;
  clearSelection: () => void;
}

export const useFactorStore = create<FactorStore>((set, get) => ({
  market: 'us',
  report: null,
  selectedFactor: null,
  decayData: [],
  loading: false,
  decayLoading: false,
  error: null,

  setMarket: (market) => set({ market }),

  fetchReport: async (market: string) => {
    set({ loading: true, error: null });
    try {
      const resp = await fetch(
        `/api/factors/ic/top?market=${encodeURIComponent(market)}&n=30`,
        { cache: 'no-store' }
      );
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${text}`);
      }
      const json = await resp.json();
      if (!json.ok) {
        throw new Error(json.detail || 'Failed to fetch factors');
      }

      // The top endpoint returns a flat list; build a minimal report
      const topFactors = json.top_factors || [];
      set({
        report: {
          market,
          date_range: ['', ''],
          forward_days: 10,
          n_periods: 0,
          factors: topFactors,
          top_factors: topFactors,
          generated_at: '',
        },
        loading: false,
      });
    } catch (err: unknown) {
      set({ error: err instanceof Error ? err.message : 'Unknown error', loading: false });
    }
  },

  selectFactor: async (factor: string) => {
    const { market } = get();
    set({ selectedFactor: factor, decayData: [], decayLoading: true });
    try {
      const resp = await fetch(
        `/api/factors/decay?market=${encodeURIComponent(market)}&factor=${encodeURIComponent(factor)}&max_lag=20`,
        { cache: 'no-store' }
      );
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const json = await resp.json();
      if (!json.ok) {
        throw new Error(json.detail || 'Failed to fetch decay');
      }
      set({ decayData: json.decay || [], decayLoading: false });
    } catch (err: unknown) {
      set({ decayData: [], decayLoading: false });
    }
  },

  clearSelection: () => set({ selectedFactor: null, decayData: [] }),
}));

export type { FactorICResult, FactorAnalysisReport, DecayPoint };
