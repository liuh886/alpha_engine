import { useEffect, useState } from 'react';
import { useModels } from './useModels';

/** Bootstrap the read-only artifact workspace without probing a server. */
export function useAppBootstrap() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const workspace = useModels();

  useEffect(() => {
    let active = true;
    const bootstrap = async () => {
      setLoading(true);
      setLoadError(null);
      const parsed = await workspace.fetchModels();
      if (!active) return;
      if (parsed === null) setLoadError('No compatible governed research bundle was found.');
      setLoading(false);
    };

    void bootstrap();
    return () => {
      active = false;
    };
  }, [workspace.fetchModels]);

  return {
    loading,
    loadError,
    ...workspace,
  };
}
