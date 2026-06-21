import { apiClient } from '@/lib/api-client';

export interface JobEnvelope {
  job_id: string;
  status: string;
  started_at: number;
  source: string;
  intent: string;
  next_action: string;
}

export const jobsApi = {
  getJob: (jobId: string) => apiClient.get<{ ok: boolean, job: any }>(`/api/jobs/${encodeURIComponent(jobId)}`),
  getActiveJobs: () => apiClient.get<{ ok: boolean, jobs: any[] }>('/api/jobs?status=running'),
  cancelJob: (jobId: string) => apiClient.post<{ ok: boolean }>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`),
  rerunJob: (jobId: string) => apiClient.post<{ ok: boolean }>(`/api/jobs/${encodeURIComponent(jobId)}/rerun`),
};
