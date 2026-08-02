import { useEffect, useState } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { useModels } from './useModels';

/**
 * Bootstrap the read-only artifact workspace.
 *
 * The browser never probes a server, polls jobs or mutates research state. It
 * only opens the published bundle and reacts when the user switches to another
 * local bundle.
 */
export function useAppBootstrap() {
  const [loading, setLoading] = useState(true);
  const setApiError = useGlobalStore((state) => state.setApiError);
  const {
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
  } = useModels();

  useEffect(() => {
    let active = true;

    const bootstrap = async () => {
      try {
        setLoading(true);
        const parsed = await fetchModels();
        if (!active) return;
        setApiError(parsed === null ? 'No compatible research bundle was found.' : null);
      } catch {
        if (active) setApiError('Cannot load the research bundle.');
      } finally {
        if (active) setLoading(false);
      }
    };

    void bootstrap();
    return () => {
      active = false;
    };
  }, [fetchModels, setApiError]);

  return {
    loading,
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
  };
}
