import { useCallback } from 'react';
import { useState } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, ModelData } from '@/lib/data-parser';
import { useGlobalStore } from '@/store/globalStore';

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);

  // selectedModelId lives exclusively in the global store to avoid
  // dual-write divergence between a local useState and the store.
  const selectedModelId = useGlobalStore((s) => s.selectedModelId);
  const setGlobalModelId = useGlobalStore((s) => s.setSelectedModelId);
  const setSelectedModelMarket = useGlobalStore((s) => s.setSelectedModelMarket);

  /**
   * Select a model by id: update the global store (single source of truth)
   * and also sync the market derived from the model list.
   */
  const setSelectedModelId = useCallback(
    (id: string) => {
      setGlobalModelId(id);
      const m = models.find((m) => m.id === id);
      if (m?.market) {
        setSelectedModelMarket(m.market.toLowerCase());
      }
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
          let nextId: string;
          if (opts?.selectLatest) {
            nextId = parsed[0].id;
          } else {
            const currentGlobalId = useGlobalStore.getState().selectedModelId;
            const stillExists = parsed.some((m) => m.id === currentGlobalId);
            nextId = stillExists ? currentGlobalId : parsed[0].id;
          }

          setGlobalModelId(nextId);
          const m = parsed.find((x) => x.id === nextId);
          // Always write lowercase to stay consistent with the store default
          if (m?.market) setSelectedModelMarket(m.market.toLowerCase());
        } else {
          setModels([]);
          setGlobalModelId('');
          // Use lowercase 'us' – matches the store initial value
          setSelectedModelMarket('us');
        }
        return parsed;
      } catch (e) {
        console.error('Failed to fetch models', e);
        return null;
      }
    },
    [setGlobalModelId, setSelectedModelMarket],
  );

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

  return {
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
    deleteModel,
  };
}
