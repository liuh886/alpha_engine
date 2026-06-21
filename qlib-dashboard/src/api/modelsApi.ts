import { apiClient } from '@/lib/api-client';

export const modelsApi = {
  getDashboardDb: () => apiClient.get<any>('/artifacts/dashboard.json'),
  deleteModel: (versionId: string) => apiClient.post<{ ok: boolean }>('/api/models/delete', { artifact_id: versionId }),
};
