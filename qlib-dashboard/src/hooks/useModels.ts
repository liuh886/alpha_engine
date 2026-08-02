import { useCallback, useEffect, useState } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, type ModelData } from '@/lib/data-parser';
import { subscribeResearchBundle } from '@/lib/research-bundle';
import { useGlobalStore } from '@/store/globalStore';

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);
  const selectedModelId = useGlobalStore((state) => state.selectedModelId);
  const setSelectedModelId = useGlobalStore((state) => state.setSelectedModelId);

  const fetchModels = useCallback(async (opts?: { selectLatest?: boolean }) => {
    try {
      const json = await modelsApi.getDashboardDb();
      useGlobalStore.getState().setDataGeneratedAt(String(json.generated_at || ''));
      const parsed = parseQlibData(json);
      setModels(parsed);

      if (parsed.length > 0) {
        const currentId = useGlobalStore.getState().selectedModelId;
        const stillExists = parsed.some((model) => model.id === currentId);
        setSelectedModelId(opts?.selectLatest || !stillExists ? parsed[0].id : currentId);
      } else {
        setSelectedModelId('');
      }
      return parsed;
    } catch (error) {
      console.error('Failed to load model evidence', error);
      return null;
    }
  }, [setSelectedModelId]);

  useEffect(
    () => subscribeResearchBundle(() => {
      void fetchModels({ selectLatest: true });
    }),
    [fetchModels],
  );

  return { models, selectedModelId, setSelectedModelId, fetchModels };
}
