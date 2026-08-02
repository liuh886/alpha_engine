import { apiClient } from '@/lib/api-client';
import { assetUrl, runtimeCapabilities } from '@/lib/runtime-capabilities';

async function getStaticDashboardDb(): Promise<any> {
  const [manifestResponse, modelsResponse] = await Promise.all([
    fetch(assetUrl('data/manifest.json'), { cache: 'no-store' }),
    fetch(assetUrl('data/models.json'), { cache: 'no-store' }),
  ]);

  if (!manifestResponse.ok || !modelsResponse.ok) {
    throw new Error('Static research data is unavailable or incomplete.');
  }

  const [manifest, models] = await Promise.all([
    manifestResponse.json(),
    modelsResponse.json(),
  ]);

  if (!Array.isArray(models)) {
    throw new Error('Static models index is invalid.');
  }

  return {
    generated_at: manifest.generated_at ?? null,
    snapshot_id: manifest.snapshot_id ?? 'static',
    models,
  };
}

export const modelsApi = {
  getDashboardDb: () => (
    runtimeCapabilities.backendApi
      ? apiClient.get<any>('/api/artifacts/dashboard-db')
      : getStaticDashboardDb()
  ),
  deleteModel: (versionId: string) => {
    if (!runtimeCapabilities.mutations) {
      return Promise.resolve({ ok: false, reason: 'read_only_runtime' });
    }
    return apiClient.post<{ ok: boolean }>('/api/models/delete', { artifact_id: versionId });
  },
};
