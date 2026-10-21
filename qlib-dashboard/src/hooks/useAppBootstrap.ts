import { useCallback, useEffect, useState } from 'react';
import { useModels } from './useModels';

export function useAppBootstrap() {
  const workspace = useModels();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    setLoading(true);
    const runs = await workspace.fetchModels();
    setLoadError(runs === null ? 'Verified formal strategy evidence is unavailable.' : null);
    setLoading(false);
  }, [workspace.fetchModels]);
  useEffect(() => { void reload(); }, [reload]);
  return { ...workspace, loading, loadError, reload };
}
