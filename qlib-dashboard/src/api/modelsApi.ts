import { apiClient } from '@/lib/api-client';

export const modelsApi = {
  getDashboardDb: () => apiClient.get<any>('/api/artifacts/dashboard-db'),
  deleteModel: (versionId: string) => apiClient.post<{ ok: boolean }>('/api/models/delete', { artifact_id: versionId }),
};
