import { useState, useEffect, useRef } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { apiClient } from '@/lib/api-client';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import { useModels } from './useModels';
import { useJobs } from './useJobs';
import { useDataStatus } from './useDataStatus';

export function useAppBootstrap() {
  const [loading, setLoading] = useState(true);
  const { setApiError, setUsername, setDemoMode } = useGlobalStore();
  
  const { models, selectedModelId, setSelectedModelId, fetchModels, deleteModel } = useModels();
  const { activeJobId, isPolling, startPolling, submitAndPoll, pollActiveJobsCount } = useJobs();
  const { loadDataStatus } = useDataStatus();

  // Collect all callbacks in a ref so the bootstrap effect below can call the
  // latest version of each function without listing them as deps (which would
  // re-run the one-time bootstrap on every render cycle).
  const callbacksRef = useRef({ loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError, setDemoMode });
  useEffect(() => {
    callbacksRef.current = { loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError, setDemoMode };
  });

  useEffect(() => {
    const bootstrap = async () => {
      const {
        loadDataStatus: loadData,
        fetchModels: fetchM,
        pollActiveJobsCount: pollJobs,
        setUsername: setU,
        setApiError: setErr,
        setDemoMode: setDemo,
      } = callbacksRef.current;

      try {
        setLoading(true);

        if (!runtimeCapabilities.backendApi) {
          const parsed = await fetchM();
          setU('Artifact Studio');
          setDemo(true);
          setErr(parsed === null ? 'No compatible static research bundle was found.' : null);
          return;
        }

        await Promise.all([
          loadData(),
          fetchM(),
          pollJobs(),
          apiClient.get<{ username: string }>('/api/system/me').then(data => {
            if (data?.username) setU(data.username);
          }).catch(() => {}),
          apiClient.get<{ demo_mode: boolean }>('/api/system/health').then(data => {
            if (data?.demo_mode) setDemo(true);
          }).catch(() => {}),
        ]);

        setErr(null);
      } catch (err) {
        callbacksRef.current.setApiError(
          runtimeCapabilities.backendApi
            ? 'Cannot reach server. Check if the backend is running.'
            : 'Cannot load the exported research bundle.',
        );
      } finally {
        setLoading(false);
      }
    };
    
    bootstrap();
  }, []);

  return {
    loading,
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
    loadDataStatus,
    deleteModel,
    jobs: {
      activeJobId,
      isPolling,
      startPolling,
      submitAndPoll
    }
  };
}
