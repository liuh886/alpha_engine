import { apiClient } from '@/lib/api-client';
import type { DataStatus } from '@/lib/api-types';
import type { JobEnvelope } from './jobsApi';

export const dataApi = {
  getStatus: () => apiClient.get<{ ok: boolean, data: DataStatus }>('/api/data/status'),
  updateData: (full: boolean, lookback_days: number) => 
    apiClient.post<JobEnvelope>('/api/data/update', { full, lookback_days }),
};
