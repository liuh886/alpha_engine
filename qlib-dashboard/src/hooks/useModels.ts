import { useState, useCallback } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, ModelData } from '@/lib/data-parser';
import { useGlobalStore } from '@/store/globalStore';

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);
  const [selectedModelId, setSelectedModelIdState] = useState<string>("");
  const { setSelectedModelId: setGlobalModelId, setSelectedModelMarket } = useGlobalStore();

  const setSelectedModelId = useCallback((id: string) => {
    setSelectedModelIdState(id);
    setGlobalModelId(id);
    const selectedModel = models.find(m => m.id === id);
    if (selectedModel?.market) {
      setSelectedModelMarket(selectedModel.market);
    }
  }, [models, setGlobalModelId, setSelectedModelMarket]);

  const fetchModels = useCallback(async (opts?: { selectLatest?: boolean }) => {
    try {
      const json = await modelsApi.getDashboardDb();
      const parsed = parseQlibData(json);
      setModels(parsed);
      
      if (parsed.length > 0) {
        if (opts?.selectLatest) {
          setSelectedModelId(parsed[0].id);
        } else {
          // preserve selection or pick first
          setSelectedModelIdState(prev => {
            const stillExists = parsed.some(m => m.id === prev);
            const nextId = stillExists ? prev : parsed[0].id;
            
            // manually sync global since we are in state setter
            setGlobalModelId(nextId);
            const m = parsed.find(x => x.id === nextId);
            if (m?.market) setSelectedModelMarket(m.market);
            
            return nextId;
          });
        }
      } else {
        setModels([]);
        setSelectedModelIdState("");
        setGlobalModelId("");
        setSelectedModelMarket("US");
      }
      return parsed;
    } catch (e) {
      console.error("Failed to fetch models", e);
      return null;
    }
  }, [setGlobalModelId, setSelectedModelMarket]);

  const deleteModel = useCallback(async (versionId: string) => {
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
  }, [fetchModels]);

  return {
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
    deleteModel
  };
}
