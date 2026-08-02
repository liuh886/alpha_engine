import { useCallback, useEffect, useState } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, type ModelData } from '@/lib/data-parser';
import { useGlobalStore } from '@/store/globalStore';
import { subscribeResearchBundle } from '@/lib/research-bundle';

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);
  const selectedModelId = useGlobalStore((state) => state.selectedModelId);
  const setGlobalModelId = useGlobalStore((state) => state.setSelectedModelId);
  const setSelectedModelMarket = useGlobalStore((state) => state.setSelectedModelMarket);

  const setSelectedModelId = useCallback(
    (id: string) => {
      setGlobalModelId(id);
      const model = models.find((candidate) => candidate.id === id);
      if (model?.market) setSelectedModelMarket(model.market.toLowerCase());
    },
    [models, setGlobalModelId, setSelectedModelMarket],
  );

  const fetchModels = useCallback(
    async (opts?: { selectLatest?: boolean }) => {
      try {
        const json = await modelsApi.getDashboardDb();
        if (json.generated_at) {
          useGlobalStore.getState().setDataGeneratedAt(String(json.generated_at));
        }

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
        console.error('Failed to load model evidence', error);
        return null;
      }
    },
    [setGlobalModelId, setSelectedModelMarket],
  );

  useEffect(
    () => subscribeResearchBundle(() => {
      void fetchModels({ selectLatest: true });
    }),
    [fetchModels],
  );

  return {
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
  };
}
