import { apiClient } from '@/lib/api-client';
import type { JobEnvelope } from './jobsApi';

export const backtestApi = {
  runBacktest: (market: string, runId: string) => 
    apiClient.post<JobEnvelope>('/api/backtest/run', {
      market, 
      model_type: "lgbm", 
      mode: "rebacktest",
      run_id: runId, 
      start: "2025-01-01", 
      end: "latest",
    }),
};
