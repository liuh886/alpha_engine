import { apiClient } from '@/lib/api-client';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import {
  getActiveResearchBundle,
  loadStaticResearchBundle,
  setActiveResearchBundle,
} from '@/lib/research-bundle';

async function getArtifactDashboardDb(): Promise<any> {
  let bundle = getActiveResearchBundle();
  if (!bundle) {
    bundle = await loadStaticResearchBundle();
    setActiveResearchBundle(bundle);
  }
  return bundle.dashboard;
}

export const modelsApi = {
  getDashboardDb: () => (
    runtimeCapabilities.backendApi
      ? apiClient.get<any>('/api/artifacts/dashboard-db')
      : getArtifactDashboardDb()
  ),
  deleteModel: (versionId: string) => {
    if (!runtimeCapabilities.mutations) {
      return Promise.resolve({ ok: false, reason: 'read_only_runtime' });
    }
    return apiClient.post<{ ok: boolean }>('/api/models/delete', { artifact_id: versionId });
  },
};
