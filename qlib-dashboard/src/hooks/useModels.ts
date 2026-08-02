import { useCallback, useEffect, useState } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, ModelData } from '@/lib/data-parser';
import { useGlobalStore } from '@/store/globalStore';
import { subscribeResearchBundle } from '@/lib/research-bundle';

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);
  const selectedModelId = useGlobalStore((s) => s.selectedModelId);
  const setGlobalModelId = useGlobalStore((s) => s.setSelectedModelId);
  const setSelectedModelMarket = useGlobalStore((s) => s.setSelectedModelMarket);

  const setSelectedModelId = useCallback(
    (id: string) => {
      setGlobalModelId(id);
      const m = models.find((model) => model.id === id);
      if (m?.market) setSelectedModelMarket(m.market.toLowerCase());
    },
    [models, setGlobalModelId, setSelectedModelMarket],
  );

  const fetchModels = useCallback(
    async (opts?: { selectLatest?: boolean }) => {
      try {
        const json = await modelsApi.getDashboardDb();
        if (json.generated_at) useGlobalStore.getState().setDataGeneratedAt(String(json.generated_at));
        const parsed = parseQlibData(json);
        setModels(parsed);

        if (parsed.length > 0) {
          const currentGlobalId = useGlobalStore.getState().selectedModelId;
          const stillExists = parsed.some((model) => model.id === currentGlobalId);
          const nextId = opts?.selectLatest || !stillExists ? parsed[0].id : currentGlobalId;
          setGlobalModelId(nextId);
          const model = parsed.find((candidate) => candidate.id === nextId);
          if (model?.market) setSelectedModelMarket(model.market.toLowerCase());
        } else {
          setGlobalModelId('');
          setSelectedModelMarket('us');
        }
        return parsed;
      } catch (error) {
        console.error('Failed to fetch models', error);
        return null;
      }
    },
    [setGlobalModelId, setSelectedModelMarket],
  );

  useEffect(() => subscribeResearchBundle(() => { void fetchModels({ selectLatest: true }); }), [fetchModels]);

  const deleteModel = useCallback(
    async (versionId: string) => {
      try {
        const resp = await modelsApi.deleteModel(versionId);
        if (resp.ok) {
          await fetchModels({ selectLatest: true });
          return true;
        }
        return false;
      } catch {
        return false;
      }
    },
    [fetchModels],
  );

  return { models, selectedModelId, setSelectedModelId, fetchModels, deleteModel };
}
